#!/usr/bin/env python
import optparse
import json
import sys
import os
sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir))
from tools import asyncfetchpush
import time
import math
import getpass
import hashlib

from collections import defaultdict
from collections import OrderedDict

''' General Utils '''
#############################################################
def tree():
    return defaultdict(tree)

def size_to_string(num, suffix="B"):
    for unit in ['','Ki','Mi','Gi','Ti','Pi','Ei','Zi']:
        if abs(num) < 1024.0:
            return "%3.1f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f%s%s" % (num, 'Yi', suffix)

def filesize_check(path):
    try:
        return os.stat(path).st_size
    except OSError:
        print "Error: file {} does not exist".format(path)
        exit(1)

def shasum(filepath):
    try:
        fh = open(filepath,'r')
        h = hashlib.sha256(fh.read()).hexdigest()
        fh.close()
        return h
    except OSError:
        print "Error: file {} does not exist".format(path)
        exit(1)


def getJson(o):
    try:
        if type(o) == str:
            jf = open(o, 'r')
        else:
            jf = o
        ret = json.load(jf)
        jf.close()
        return ret if ret else {}
    except IOError as e:
        print "Can't open " + o
        print "I/O error({0}): {1}".format(e[0], e[1])
        return {}
    except:
        print "Unexpected error:", sys.exc_info()[0]
        return {}

#############################################################
'''
This class encapsulates multiple HTTP requests

All operations are centerd around two dictionaries -
request_objects - URL : HTTPRequestHelper
    This contains information about the file
        - filesize
        - checksum
        - path
        - timestamp (of completed request)
        - method (GET, PUT, DELETE etc)

async_requests - METHOD(+num) : AsyncRequestObj
    These request objects are generated from the
    request_objects dict. The AsyncRequestObjects
    manage and make the actual requests. The object
    is then inspected after the requests have been made
    for the results.

a log file is also produced to allow resuming of requests
holding filesizes etc. This will always be async.log.json
in the execution directory.

The log is json format and ordered by timestamp key value
'''
class HTTPRequests:
    def __init__(self, filehandle, options):
        #This can be stdin or file
        self.filehandle = filehandle
        self.options = options

        #Contains the url/req used for logging/ops
        self.request_objects = OrderedDict()

        #Contains the actual Async requests (batched)
        self.async_requests = {}

        self.username = ""
        self.password = ""
        self.dry = True
        self.basedir = ""
        self.maxrequestsize = 0
        self.maxrequestsize_c = 0
        self.retries = 3

        #Logging stuff
        self.logfile = "async.log.json"
        self.lf_json_all = self._logfile_json()
        self.last_log_key = self._lastlogentry()
        self.log_time = time.time()

        #Produce the async requests
        self._compose_ordered_requets()

    def _set_username_password(self, j):
        if self.options.username:
            self.username = self.options.username
        j = j['HTTPAsyncData']
        if j.has_key('username'):
            self.username = j['username']

        if self.username and not j.has_key('password'):
            self.password = getpass.getpass(
                    prompt='Http Auth Password (leave blank for ''):')
        elif j.has_key('password'):
            self.password = j['password']


    def _logfile_json(self):
        return getJson(self.logfile)

    def _lastlogentry(self):
        if self.lf_json_all:
            od = OrderedDict(sorted(self.lf_json_all.items()))
            return self.lf_json_all.keys()[-1]


    def _incomplete_requests(self):
        for url, content in self.request_objects.iteritems():
            if content.completed_timestamp:
                self.request_objects.pop(url)


    def _compose_ordered_requets(self):
        '''
        json files are in a simple format -
        HTTPAsyncData
            - PUT
                - URL : FILE PATH
                - URL : FILE PATH
            - GET
            - HEAD
            - etc...

        This is to be combined with the log for resume and filesize/check support
        '''
        j = getJson(self.filehandle)
        if not j.has_key('HTTPAsyncData'):
            #Throw exception
            print "The json file doesn't contain valid HTTPAsync data section(s)"
        #Load the log if continue is specified
        self._set_username_password(j)
        if self.options.resume:
            for url, contents in self.lf_json_all[self.last_log_key].iteritems():
                self.request_objects.update({url:HTTPRequestHelper(**contents)})
            self._continue_requests()

        elif self.options.checkonly or self.options.checkfirst:
            #Try request only once
            self.retries = 0
            logfiler = {}
            #Try and load logfile first, this will save calculating the filesizes
            for url, contents in self.lf_json_all[self.last_log_key].iteritems():
                if contents['method'] == 'HEAD' or contents['method'] == 'PUT':
                    logfiler.update({url:HTTPRequestHelper(**contents)})

            for method, contents in j['HTTPAsyncData'].iteritems():
                if method == 'HEAD' or method == 'PUT':
                    for url, filepath in contents.iteritems():
                        if logfiler.has_key(url):
                            self.request_objects.update({url:logfiler[url]})
                        else:
                            self.request_objects.update({url:HTTPRequestHelper(method,filepath)})
                        self.request_objects[url].change_to_check()
            self._build_async_reqs()
            self._check_uploads()

            #If we got a 404 switch the HEAD back to PUT and build more requests
            if self.options.checkfirst:
                for url, rh in self.request_objects.iteritems():
                    if rh.method == 'HEAD':
                        rh.method = 'PUT'

                self.async_requests = {}
                self.retries = 3
                self._build_async_reqs()

        else:
            #Get the items in the provided file
            for method, contents in j['HTTPAsyncData'].iteritems():
                try:
                    for url, filepath in contents.iteritems():
                        self.request_objects.update({url:HTTPRequestHelper(method,
                            filepath)})
                except Exception as e:
                    print "Exception" + str(e) + " " + str(method) + " could not be iterated, skipping"
            self._build_async_reqs()
        self._write_to_log()




    def _build_async_reqs(self):
        for url, rh in self.request_objects.iteritems():
            self._build_async_req(url,rh)

    def _build_async_req(self, url, rh):
        #Create the request structure
        if not self.async_requests.has_key(rh.method):
            self.async_requests.update({rh.method:
                asyncfetchpush.HttpGrabberPusher(rh.method, limit=200, retries=self.retries, username=self.username, password=self.password)})

        self.async_requests[rh.method].append({url:rh.filepath})
        '''
        #if the max size has been reached make more key+count
        if self.request_total >= self.maxrequestsize:
            i = 0
            while true:
                if self.async_request.has_key(rh.method+str(i)):
                    i=+1
                else:
                    self.async_request.update(rh.method+str(i))
                        asyncfetchpush.HttpGrabberPusher(rh.method, limit=200)
                        break

            if self.
        else:'''



    def _continue_requests(self):
        self._incomplete_requests()
        for url, rh in self.request_objects.iteritems():
            self._build_async_req(url, rh)


    def _write_to_log(self):
        logfile_handle = open(self.logfile, 'w')
        self.lf_json_all[self.log_time] = self.request_objects
        logfile_handle.write(HTTPJsonEncoder(sort_keys=True, indent=3).encode(self.lf_json_all))
        logfile_handle.close()

    def make_requests(self):
        try:
            for method, requests in self.async_requests.iteritems():
                if not self.options.dry:
                    requests.make_requests()
                    responses = requests.request_response_dictionary()
                    #failed = requests.request_failed_dictionary()
                    for url, response in responses.iteritems():
                        if response is True:
                            self.request_objects[url].stamp()

                    #for url, rcode in failed.iteritems()
                    #    if rcode == 400:
                    #        print "{0} failed with err {1}, deleting remote failed"

            if self.options.check or self.options.checkonly:
                self._check_uploads()
        except KeyError as e:
            print "Key error: " + str(e) + " does't exist in requests"
        except Exception as e:
            print "Error " + str(e)
        finally:
            self._write_to_log()

    def _check_uploads(self):
        print "Checking uploaded files for filesize inconsistancies"
        #Change PUT to HEAD and make the requests
        for url, rh in self.request_objects.iteritems():
            if rh.method == 'PUT':
                rh.change_to_check()
                self._build_async_req(url, rh)
        self.async_requests['HEAD'].make_requests()
        headers = self.async_requests['HEAD'].request_header_dictionary()

        for url in headers.keys():
            try:
                #print "Checking {0} is {1}".format(url, size_to_string(self.request_objects[url].filesize))
                if int(headers[url]['content-length']) != int(self.request_objects[url].filesize):
                    print ("filesize for {0} do not match:"
                        "\nOriginal:\t\t{1}"
                        "\nHead response:\t\t{2}").format(url,
                                self.request_objects[url].filesize,
                                headers[url]['content-length'])
                else:
                    #Already exists so pop it from our list, avoid reuploading
                    del self.request_objects[url]

            except KeyError as e:
                print "url {} does not exist or did not return headers: Exception KeyError {}".format(url, e)

    def __str__(self):
        ret = ""
        tnr = 0
        for method in self.async_requests.keys():
            ret += "\n\n" + str(method) + ":\n\t"
            for request in self.async_requests[method].requestlist:
                ret += "\n\t" + str(request.url)
                tnr += 1

        tfs = 0
        for url, rh in self.request_objects.iteritems():
            tfs += rh.filesize

        ret += "\n\n\nSUMMARY\n"
        ret += ("Total transfer size:\t\t{0}"
            "\nTotal Number of requests:\t{1}"
            "\nUsing username:\t{2}").format(size_to_string(tfs),
                                            str(tnr),
                                            self.username)

        return ret

#Used to write the HTTPRequestHelper object to json
class HTTPJsonEncoder(json.JSONEncoder):

    def default(self, obj):
        return obj.__dict__

'''
This class is a helper to contain information about a single url/prerequest
object

It provides functions to be called by
'''
class HTTPRequestHelper(object):
    def __init__(self, method, filepath, completed_timestamp=None,
        filesize=0, checksum=None):

        self.filepath = filepath
        self.completed_timestamp = completed_timestamp
        self.method = method
        self.filesize = filesize
        if self.filesize == 0 and self.method == 'PUT':
            self.filesize = self._filesize()
            if checksum is True:
                self.checksum = self._checksum()

    def _filesize(self):
        return filesize_check(self.filepath)

    def _checksum(self):
        return shasum(self.filepath)

    def reverse_request(self):
        if self.method == 'GET':
            self.method = 'PUT'
        elif self.method == 'PUT':
            self.method = 'GET'

    def change_to_check(self):
        if self.method == 'PUT':
            self.method = 'HEAD'

    def stamp(self):
        self.completed_timestamp = time.time()

    #def change_to_delete(self):
    #    self.method = 'DELETE'

    #def __repr__(self):
    #        return json.dumps(self.__dict__)

def setUsernamePassword(async_obj, opts):
    if opts.username:
        async_obj.username = opts.username
        if not opts.password:
            opts.password = getpass.getpass(prompt='Http Auth Password (leave blank for ''):')
        async_obj.password = opts.password if opts.password else ''


def check_upload_integrity(urls, responses):
    for r in responses.requestlist:
        print r.headers['content-length']

        '''
        if r.response.contentsize == urls[r.url]
        else
            fail
        '''

def parse_args():
    op = optparse.OptionParser(description="Get/Push files in a asynchronous way.")

    #Just feed the script a premade JSON file, all options are set in here
    op.add_option('-i', "--inputfile", dest='json', help=("a .json metafile to parse" "see example.json"))

    #List our intentions
    op.add_option('-d', "--dry", action="store_true", default=False,
                    help=(  "Don't actually make PUT/GET requests, list intentions"
                            " and dump any generated files to the current dir"))

    op.add_option('-u', "--username", help=("Make the requests with a username"))

    op.add_option('-p', "--password", help=("Make the requests with a password"))
    op.add_option('', "--flatdirs", help=("Flatten the directory structure"), action="store_true", default=False)
    op.add_option('', "--resume", help=("Resume operations from async.log.json"), action="store_true", default=False)
    ''' Fetch (GET) opts'''
    fetchopt = optparse.OptionGroup(op, "HTTP GET options",
            "Options for fetching files, output dir, link file/list etc")

    fetchopt.add_option("", "--urlfile", type="string",
            help=("A list of urls, newline seperated"))

    fetchopt.add_option("", "--get", dest="gstdin",
            help=("Read a list of URLs from stdin"), action="store_true", default=False)

    fetchopt.add_option("", "--destination", type="string",
            help=("A destination directory for the fetched files\n"
                "Create a tempdir by default, this wont be cleaned up!"))

    op.add_option_group(fetchopt)

    ''' Put (PUT) opts'''
    putopt = optparse.OptionGroup(op, "HTTP PUT option",
            "Options for pushing files, input dir, link file/list etc")

    putopt.add_option("", "--basedir", type="string",
            help=("Base directory from which to upload all files and folders"))

    putopt.add_option("", "--put", dest="pstdin",
            help=("Read a list of files from stdin, newline seperated"), action="store_true", default=False)

    putopt.add_option('', "--size", type="int", help=("Aim to send number of files to send in MiB"))

    putstdinopt = optparse.OptionGroup(op, "HTTP PUT STDIN options",
            "Options for pusing files via stdin")

    putstdinopt.add_option("", "--stdinjson", dest="pstdin_json", action="store_true", default=False,
            help=("Read stdin as json"))

    putstdinopt.add_option("", "--baseurl", dest="baseurl",
            help=("The base URL for puts eg. http://foo.com/somedir/"))

    putstdinopt.add_option("", "--check",  help=("Check the uploads exist"
            "after the put requests have been made"), action="store_true",
            default=False)

    putstdinopt.add_option("", "--checkonly",  help=("Check the uploads exist"
            "after the put requests have been made"), action="store_true",
            default=False)

    putstdinopt.add_option("", "--checkfirst",  help=("Check the repo first"
            " make request list for files that return 404 only"),
            action="store_true", default=False)

    op.add_option_group(putopt)
    op.add_option_group(putstdinopt)

    (options, args) = op.parse_args()
    return options

def main():

    options = parse_args()

    hr = None
    if options.pstdin_json:
        hr = HTTPRequests(sys.stdin, options)

    elif options.json:
        hr = HTTPRequests(open(options.json, 'r'), options)

    else:
        hr = HTTPRequests(None, options)
    print(hr)

    if not options.dry or not options.checkonly:
        hr.make_requests()

if __name__ == "__main__":
    main()
