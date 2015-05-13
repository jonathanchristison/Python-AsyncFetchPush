Description
===========
The asyncfetchpush.py and asyncfetchpush_cmd.py scripts provide aim to provide a fast and efficient way of making asyncronous http file requests, namely PUT, GET, HEAD requests. The requests are queued and executed by grequests (gevent and requests).

The core, asyncfetchpush.py consists of two simple classes HttpGrabberPusher which can be thought of as a list of requests allowing appending of URL and filepath as well as http method, setting pool size, timeouts per request, username and password and number of times to attempt the request if it fails; the second class being AsyncGetPush which HTTPGrabberPusher uses. This represents the request object and contains the callback function to handle the request response.

Requirements
============
The scripts have a few requirements -

+ argparse==1.3.0
+ gevent==1.0
+ greenlet==0.4.5equests==0.2.0
+ progressbar2==2.7.3
+ pyOpenSSL==0.15.1
+ grequests==0.2.0
+ requests==2.5.3


asyncfetchpush_cmd.py
=====================
The command line utility asyncfetchpush_cmd.py abstracts these concepts of a url and filepath pair to something usable by command line, It provides stdins for json and new line separated file lists, file handling and logging, resume support and file verification.

The execution flow is generally

1. take a url : filepath pair and any other arguments like username and password (from a json file, flat file or command line options)
2. Load async.log.json if it exists
3. construct a object representing the file to upload, filesize and optional checksum
4. save to async.log.json
5. convert these url/filepath objects to a series of HttpGrabberPusher objects, one for each method and optionally chunked at a max filesize
6. make the requests
7. log the results to async.log.json using a timestamp on each filepath
8. change the method to HEAD and check the filesizes if --check is enabled
9. make the requests

input options
-------------
The url/filepath pair can be in putted in several formats -
+ flat file + baseurl ( --put and --baseurl) [STDIN]
+ json file (-i/--inputfile) [FILE]
+ json string (--stdinjson) [STDIN]

Input json file format example
------------------------------
    {
        "HTTPAsyncData": {
            "PUT": {
                "https://foo.com/bar.jar": "/tmp/bar.jar"
            }
        }
    }

+ "HTTPAsyncData" exists for scoping so if the script is chained with other utilities they can all share the same json file
+ "PUT" is the request method
+ "https://..." Where the request will be made to/from
+ "/tmp/..." The filepath where the file is/will be put

log file format
---------------
    "1429795306.081477": {
        "https://foo.com/bar.jar": {
             "completed_timestamp": null,
             "filepath": "/tmp/bar.jar",
             "filesize": 152364,
             "method": "HEAD"
          }
       },


+ "1429795306.081477" - The timestamp of the creation of the log/requests, this allows the last to be reexecuted with --resume (sans completed requests)
+ "https://re...." - Where the request will be made to/from
+ "{" - The HTTPRequestHelper object
+ "completed_timestamp" - A timestamp the request was successfully completed, null is treated as unprocessed and will be requested with --resume
+ "filepath" - path to the file to be got/put
+ "filesize" - If PUT or HEAD request the size of the file, this is used to verify a successful upload PUT -> HEAD and verified against the original filesize
+ "method" - the method of the request eg. PUT, GET, DELETE, HEAD etc

Examples
--------
Dry run -  `./asyncfetchpush_cmd.py --dry -i uploadlist.json`
Check the files don't exist on the remote first - `asyncfetchpush_cmd.py -i uploadlist.json --checkfirst`
Checking the files have been successfully uploaded (filesize verification) - `asyncfetchpush_cmd.py -i uploadlist.json --check`

Bugs and todo
=============

asynfetchpush
-------------
+ Get rid of the inefficient list hodgepodge going on and store urls+requests in a dictionary
+ Move away from grequests and towards requests and asyncio
+ Have user hookable response callbacks
+ Standardise response callbacks, remove the response bool and replace with the actual response (might be more memory intensive)
+ Replace grequests/gevents with asyncio

asyncfetchpush_cmd
-------------------
+ Move from optparse to argparse
+ Better exception handling
+ Abstract option handling and file handling from HTTPRequests to allow HTTPRequests class to be used in scripts that dont need json such as the Nexus upload script
+ implement flat file parsing + baseurl input (STDIN and file arguments)
+ Improve log file, various bugs where the log file is not read or overwritten with null


