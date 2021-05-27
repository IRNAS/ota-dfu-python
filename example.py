import logging
from ota_dfu_python.dfu import Dfu

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%d/%m/%Y %H:%M:%S', level=logging.INFO)

address = "AB:CD:EF:01:12:23"
zipfile = "/path/to/zipfile.zip"

# dfu sometimes fails, retry until it succeeds
# TODO: find out WHY dfu fails
success = False
while not success:
    # initialize dfu class
    dfu = Dfu(address, zipfile)
    try:
        dfu.perform_dfu()
        success = True
    except Exception as e:
        logging.error(f"Unable to perform dfu. Reason: {e}")