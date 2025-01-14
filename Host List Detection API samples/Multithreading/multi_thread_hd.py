'''
This script downloads Qualys assets and host detections.
Run this script with -h option to know other options.
'''
import os
import Queue
import base64
import urllib
import urllib2
import urlparse
from datetime import datetime
from optparse import OptionParser
from threading import current_thread
from threading import Thread
try:
    import xml.etree.cElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET

SERVER_ROOT = 'YOUR QUALYS API SERVER'
OUTPUT_DIR = './output'
API_USERNAME = 'YOUR QUALYS API USERNAME'
API_PASSWORD = 'YOUR QUALYS API PASSWORD'
NUM_ASSET_THREADS = 10
NUM_DETECTION_THREADS = 10
CHUNK_SIZE = 1000

SETTINGS = {
    'download_assets': True,
    'download_detections': True
}

def build_headers():
    '''
    This method builds the HTTP headers required by client function.
    '''
    auth = "Basic " + base64.urlsafe_b64encode(
        "%s:%s" % (API_USERNAME, API_PASSWORD)
    )
    headers = {
        'User-Agent': 'Kaiser python script client',
        'X-Requested-With': 'Kaiser python script',
        'Authorization': auth
    }
    return headers
# end of build_headers

def build_request(api_route, params):
    '''
    This method builds the urllib2 request object
    with complete url, parameters and headers.
    '''
    data = urllib.urlencode(params)
    return urllib2.Request(api_route, data=data, headers=build_headers())
# end of build_request

def call_api(api_route, params):
    '''
    This method does the actual API call. Returns response or raises error.
    Does not support proxy at this moment.
    '''
    print "[%s] Calling %s with %s" % (
        current_thread().getName(), api_route, params)

    req = build_request(api_route, params)

    try:
        response = urllib2.urlopen(req, timeout=100)

        if response.getcode() != 200:
            print "[%s] Got unexpected response from API: %s" % (
                current_thread().getName(), response.read)
            raise Exception("API request failed: %s" % response.read)
        # end of if

        print "[%s] Got response from API..." % current_thread().getName()
        return response.read()
    except urllib2.URLError, url_error:
        print "[%s] Error during request to %s: [%s] %s" % (
            current_thread().getName(), api_route,
            url_error.errno, url_error.reason)
        raise Exception(
            "Error during request to %s: [%s] %s" % (
                api_route, url_error.errno, url_error.reason)
        )
# end of call_api

def write_response(response, filename):
    '''
    This method writes given response into given file.
    If complete path to file does not exist, it will create it.
    '''
    if not os.path.exists(os.path.dirname(filename)):
        try:
            os.makedirs(os.path.dirname(filename))
        except OSError:
            print "[%s] Error while creating \
            output directory." % current_thread().getName()
            raise
    # end of if

    file_pointer = open(filename, 'w')
    file_pointer.write(response)
    file_pointer.close()
# end of write_response

def get_asset_ids():
    '''
    This method will fetch all the host ids in single API call.
    '''
    action = 'list'
    details = 'None'
    api_route = '/api/2.0/fo/asset/host/'
    params = {'action': action, 'details': details, 'truncation_limit': 0}
    asset_ids = []
    print "[%s] Fetching asset ids..." % current_thread().getName()
    response = call_api(SERVER_ROOT + api_route, params)
    filename = OUTPUT_DIR + "/assets/asset_ids_%s_%s.xml" % (
        os.getpid(), current_thread().getName())
    write_response(response, filename)
    print "[%s] Wrote API response to %s" % (
        current_thread().getName(), filename)
    print "[%s] Parsing IDs..." % current_thread().getName()
    tree = ET.parse(filename)
    root = tree.getroot()
    # root = ET.fromstring(response)
    response_element = root.find('RESPONSE')
    if response_element is None:
        print "[%s] RESPONSE tag not found" % current_thread().getName()
    id_set = response_element.find('ID_SET')
    if id_set is None:
        print "[%s] ID_SET not found" % current_thread().getName()
    else:
        for id_element in id_set.findall('ID'):
            asset_ids.append(id_element.text)
        # end of for loop
    # end of if-else
    return asset_ids
# end of get_asset_ids

def get_params_from_url(url):
    '''
    This method returns dictionary of URL parameters.
    '''
    return dict(urlparse.parse_qsl(urlparse.urlparse(url).query))
# end of get_params_from_url

def vm_detection_coordinator(detection_idset_queue):
    '''
    This method is entry point of each detection thread.
    It pops out an id range entry from detection queue, and calls
    download_host_detections passing id range as argument.
    '''
    keep_running = True
    while keep_running:
        try:
            print "[%s] Getting id set from \
            detection_idset_queue" % current_thread().getName()
            id_range = detection_idset_queue.get(False)
            print "[%s] Processing id set: %s" % (
                current_thread().getName(), id_range)
            download_host_detections(id_range)
            detection_idset_queue.task_done()
        except Queue.Empty:
            print "[%s] detection_idset_queue is empty. \
            Exiting." % current_thread().getName()
            keep_running = False
        # end of try-except
    # end of while loop
# end of vm_detection_coordinator

def download_host_detections(ids):
    '''
    This method will invoke call_api method for asset/host/vm/detection/ API.
    '''
    api_route = '/api/2.0/fo/asset/host/vm/detection/'

    params = {
        'action': 'list',
        'echo_request': 1,
        'show_tags': 1,
        'show_igs': 1,
        'truncation_limit': 500,
        'output_format': 'XML', # 'CSV_NO_METADATA'
        'ids': ids
    }

    batch = 1

    print "[%s] Downloading VM detections for ids %s" % (
        current_thread().getName(), ids)

    keep_running = True

    file_extension = 'xml'
    if params['output_format'] != 'XML':
        file_extension = 'csv'
        params['truncation_limit'] = 0

    while keep_running:
        response = call_api(SERVER_ROOT + api_route, params)

        filename = OUTPUT_DIR + "/vm_detections/\
        vm_detections_Range-%s_Process-%s_%s_Batch-%d.%s" % (
            ids, os.getpid(), current_thread().getName(), batch, file_extension)
        write_response(response, filename)
        print "[%s] Wrote API response to %s" % (
            current_thread().getName(), filename)

        if params['output_format'] == 'XML':
            print "[%s] Parsing response XML..." % current_thread().getName()
            tree = ET.parse(filename)
            root = tree.getroot()
            response_element = root.find('RESPONSE')

            if response_element is None:
                print "[%s] RESPONSE tag not found in %s. \
                Please check the file." % (current_thread().getName(), filename)
                keep_running = False

            warning_element = response_element.find('WARNING')
            if warning_element is None:
                print "[%s] End of pagination for ids %s" % (
                    current_thread().getName(), ids)
                keep_running = False
            else:
                next_page_url = warning_element.find('URL').text
                params = get_params_from_url(next_page_url)
                batch += 1
            # end of if-else
        # end of if
    # end of while
# end of download_host_detections

def assets_coordinator(assets_idset_queue):
    '''
    This method is entry point of each asset download thread.
    It pops out an id range entry from assets queue,
    and calls download_assets method passing id range as argument.
    '''
    keep_running = True
    while keep_running:
        try:
            print "[%s] Getting id set from \
            assets_idset_queue" % current_thread().getName()
            id_range = assets_idset_queue.get(False)
            print "[%s] Processing id set: %s" % (
                current_thread().getName(), id_range)
            download_assets(id_range)
            assets_idset_queue.task_done()
        except Queue.Empty:
            print "[%s] assets_idset_queue is empty. \
            Exiting." % current_thread().getName()
            keep_running = False
        # end of try-except
    # end of while loop
# end of vm_detection_coordinator

def download_assets(ids):
    '''
    This method will invoke call_api method for asset/host API.
    '''
    api_route = '/api/2.0/fo/asset/host/'
    params = {
        'action': 'list',
        'echo_request': 1,
        'details': 'All/AGs',
        'ids': ids,
        'truncation_limit': 5000
    }

    batch = 1

    print "[%s] Downloading assets..." % current_thread().getName()

    keep_running = True

    while keep_running:
        response = call_api(SERVER_ROOT + api_route, params)

        filename = OUTPUT_DIR + "/assets/\
        assets_Range-%s_Proc-%s_%s_Batch-%d.xml" % (
            ids, os.getpid(), current_thread().getName(), batch)
        write_response(response, filename)
        print "[%s] Wrote API response to %s" % (
            current_thread().getName(), filename)

        print "[%s] Parsing response XML..." % current_thread().getName()
        tree = ET.parse(filename)
        root = tree.getroot()
        response_element = root.find('RESPONSE')

        if response_element is None:
            print "[%s] RESPONSE tag not found in %s. \
            Please check the file." % (
                current_thread().getName(), filename)
            keep_running = False

        warning_element = response_element.find('WARNING')

        if warning_element is None:
            print "[%s] End of pagination for ids %s" % (
                current_thread().getName(), ids)
            keep_running = False
        else:
            next_page_url = warning_element.find('URL').text
            params = get_params_from_url(next_page_url)
            batch += 1
        # end of if-else
    # end of while
# end of download_assets

def chunk_id_set(id_set, num_threads):
    '''
    This method chunks given id set into sub-id-sets of given size
    '''
    for i in xrange(0, len(id_set), num_threads):
        yield id_set[i:i + num_threads]
    # end of for loop
# end of chunk_id_set

def parse_options():
    '''
    This method parses all options given in command line.
    '''
    global SERVER_ROOT, API_USERNAME, API_PASSWORD
    global NUM_ASSET_THREADS, NUM_DETECTION_THREADS, CHUNK_SIZE
    parser = OptionParser()
    parser.add_option("-s", "--server", dest="server",\
    default="https://qualysapi.qualys.com", help="Qualys API Server")
    parser.add_option("-u", "--user",\
    dest="username", help="Qualys API Username")
    parser.add_option("-p", "--pass",\
    dest="password", help="Qualys API Password")
    parser.add_option("-a", "--asset_threads",\
    dest="num_asset_threads", default=0,\
    help="Number of threads to fetch host assets")
    parser.add_option("-d", "--detection_threads",\
    dest="num_detection_threads", default=0,\
    help="Number of threads to fetch host detections")
    parser.add_option("-c", "--CHUNK_SIZE", dest="CHUNK_SIZE", default=1000,\
    help="Size of ID range chunks")
    (options, values) = parser.parse_args()
    SERVER_ROOT = options.server
    API_USERNAME = options.username
    API_PASSWORD = options.password
    NUM_ASSET_THREADS = int(options.num_asset_threads)
    NUM_DETECTION_THREADS = int(options.num_detection_threads)
    CHUNK_SIZE = int(options.CHUNK_SIZE)
# end of parse_options

def main():
    '''
    Main method of this code.
    '''
    parse_options()

    if NUM_ASSET_THREADS <= 0:
        SETTINGS['download_assets'] = False

    if NUM_DETECTION_THREADS <= 0:
        SETTINGS['download_detections'] = False

    if SETTINGS['download_assets'] == False and \
    SETTINGS['download_detections'] == False:
        print "Please set at least one of -a or -d options. \
        You haven't set any of them with valid values."
        print SETTINGS
        exit()
    # end of if

    id_set = get_asset_ids()
    num_ids = len(id_set)
    print "[%s] Got %d asset ids..." % (current_thread().getName(), num_ids)

    # split the entire id set into sub id sets of size CHUNK_SIZE
    num_chunks = num_ids / CHUNK_SIZE
    chunks = chunk_id_set(id_set, num_chunks)

    detection_idset_queue = Queue.Queue()
    assets_idset_queue = Queue.Queue()

    workers = []

    for id_chunk in chunks:
        id_range = "%s-%s" % (id_chunk[0], id_chunk[-1])

        if SETTINGS['download_assets'] == True:
            assets_idset_queue.put(id_range)
        if SETTINGS['download_detections'] == True:
            detection_idset_queue.put(id_range)
    # end of for loop

    if SETTINGS['download_assets'] == True:
        print "Starting %d threads for Assets download..." % NUM_ASSET_THREADS
        for i in range(0, NUM_ASSET_THREADS):
            asset_thread = Thread(
                target=assets_coordinator, args=(assets_idset_queue,))
            asset_thread.setDaemon(True)
            asset_thread.start()
            workers.append(asset_thread)
            print "Started asset thread # %d" % i
        # end of for loop
    # end of if

    if SETTINGS['download_detections'] == True:
        print "Starting %d threads for \
        detection download" % NUM_DETECTION_THREADS
        for i in range(0, NUM_DETECTION_THREADS):
            detection_thread = Thread(
                target=vm_detection_coordinator, args=(detection_idset_queue,))
            detection_thread.setDaemon(True)
            detection_thread.start()
            workers.append(detection_thread)
            print "Started detection thread # %d" % i
        # end of for loop
    # end of if

    for worker in workers:
        worker.join()
# end of main

if __name__ == "__main__":
    START_TIME = datetime.now()
    main()
    END_TIME = datetime.now()
print END_TIME - START_TIME
