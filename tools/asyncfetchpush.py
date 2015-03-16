import progressbar
import time
import sys
import os
import grequests

global pbar

'''
Fast implementation of HTTP GET/POST/PUT

Args:
    method - HTTP METHOD 'GET, 'PUT' etc
    url - The url of the resource
    filepath - the full path to download to/upload from
    kwargs - Arguments passed to the requests lib
    (http://docs.python-requests.org/en/latest/)

Example:

AsyncGetPush('GET', 'http://foo.com/bar.tgz', '/tmp/bar.tgz', timeout=1)
              ^method  ^url                    ^filepath       ^kwargs
'''
class AsyncGetPush(grequests.AsyncRequest):

    def __init__(self, method, url, filepath, **kwargs):
        self.method = method
        self.url = url
        self.filepath = filepath
        self.response = False

        if 'timeout' in kwargs:
            self.timeout = kwargs['timeout']

        self.request = grequests.AsyncRequest(self.method, self.url,
                hooks=dict(response=self.handle_response), timeout=self.timeout)

        #Use a filehandle instead of a filepath
        self.filehandle = kwargs.pop('filehandle', None)
        if self.filehandle is None:
                self.filehandle = open(self.filepath, 'wb')

    #Borked request, requires rerequesting
    def rerequest(self):
        self.request = grequests.AsyncRequest(self.method, self.url,
                hooks=dict(response=self.handle_response), timeout=self.timeout)

    def handle_response(self, r, **kwargs):
        global pbar
        if r.status_code == 200:
            self.response = True
        else:
            self.response = False

        if self.method is "GET" and self.response:
            self.filehandle.write(r.content)
            self.filehandle.close()
            pbar.update(pbar.currval+1)
        else:
            raise Exception("HTTP Request failed with :" + r.status_code)


'''
A quick and dirty wrapper around AsyncGetPush

Args:
    method - HTTP METHOD 'GET, 'PUT' etc
    comburlafile - A dictionary of file paths, using the url as the key
    limit - The amount of requests per pool
    timeout - The timeout per request in seconds
    retries - The number of times to send a group of requests

Example:

    Defaults:
    requests = asyncfetchpush.HttpGrabberPusher('GET')

    Initialised:
    someurlpaths = {'http://foo.com/bar.tgz':'/tmp/bar.tgz', 'https://foo.com/bar2.tgz:'/tmp/bar2.tgz'...
    requests = asyncfetchpush.HttpGrabberPusher('GET', someurlpaths, limit=10, timeout=3, retries=1)

    Appending:
    requests.append({'http://foo.com/bar.tgz : '/tmp/bar.tgz'})

    Making the requests:
    requests.make_requests()

    Iterating:
    for completed_request in requests:
        print completed_request.filepath
        print completed_request.url
'''

class HttpGrabberPusher(object):
    def __init__(self, method, comburlafile=None, limit=150, timeout=10, retries=3):
        self.method = method
        self.requestlist = []
        self.failedrequests = []
        self.limit = limit
        self.timeout = timeout
        self.retries = retries
        self.original = []

        if comburlafile:
            self.append(comburlafile)

    def __iter__(self):
        return iter(self.requestlist)

    def append(self, dic):
        self.original.append(dic)
        for key in dic:
            self.requestlist.append(
                    AsyncGetPush(
                        self.method, key, dic[key],
                        timeout=self.timeout
                        ))
    #Recurse
    def make_requests_r(self, rlist, count=0):

            failed = []
            if count < 1:
                pool = grequests.Pool(self.limit)
            elif count < 2:
                time.sleep(10)
                pool = grequests.Pool(self.limit/2)
                (r.rerequest() for r in rlist)
            elif count < 3 or count > 3:
                time.sleep(10)
                pool = grequests.Pool(1)
                (r.rerequest() for r in rlist)

            jobs = [grequests.send(r.request, pool, stream=False) for r in rlist]
            grequests.gevent.joinall(jobs)

            for r in rlist:
                if not r.response:
                    print "Request: " + r.url + " failed[" + str(count) + "]"
                    failed.append(r)
            return failed

    #Make the requests, use the recursive func
    def make_requests(self):
        global pbar
        pbar = progressbar.ProgressBar(
                            widgets=[
                                progressbar.Bar(),
                                progressbar.Percentage(),
                                ' reqs ',
                                progressbar.SimpleProgress()
                                ],
                            maxval=len(self.requestlist),
                            term_width=80)
        pbar = pbar.start()
        fr = self.make_requests_r(self.requestlist, 0)
        if len(fr) > 0:
            for x in xrange(self.retries):
                print "Trying Failed (try " + str(x) + " of " + str(self.retries) + " )"
                pbar = progressbar.ProgressBar(
                                    widgets=[
                                        progressbar.Bar(),
                                        progressbar.Percentage(),
                                        ' reqs ',
                                        progressbar.SimpleProgress()
                                        ],
                                    maxval=len(fr),
                                    term_width=40)
                fr = self.make_requests_r(fr, x)
        pbar.finish()
        if len(fr) > 0:
            print "Still Failures"
