import logging
import argparse
import asyncio
import time
import sys

from PyInquirer import prompt, style_from_dict, Token
from bleak import discover
from ota_dfu_python.dfu import SecureDfu
from ota_dfu_python.unpacker import Unpacker

def select_ble_device(devices):
    """Select device used for DFU"""
    
    question_devices = [
        {
            "type": "list",
            "message": "Select discovered BLE device",
            "name": "device",
            "choices": [{"name": f"Address: {d.address}, Name: {d.name}", "value": d.address} for d in devices]
        }
    ]
    
    selected_device = prompt(question_devices)["device"]
    print(selected_device)
    return selected_device

def get_ble_devices(loop):
    """Finds all devices containg 'identifier' in name"""
    try:
        logging.info("Starting BLE device discovery")
        device_list = []
        async def run():
            devices = await discover(timeout=2)
            for d in devices:
                device_list.append(d)
        loop.run_until_complete(run())
        device_list.sort(key=lambda x: x.rssi)
    except Exception as e:
        logging.error(f"An exception occured during BLE device disveory: {e}")
        device_list = None
    return device_list


logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%d/%m/%Y %H:%M:%S', level=logging.INFO)

parser = argparse.ArgumentParser(description="python3 example.py -z <zip_file> -a <dfu_target_address>")
parser.add_argument('-a', '--address', action='store', dest="address", default=None, help='DFU target address.')
parser.add_argument('-z', '--zipfile', action='store', dest="zipfile", default=None, help='Zip file to be used.')
parser.add_argument('-f', '--hexfile', action='store', dest="hexfile", default=None, help='Hex file to be used.')
parser.add_argument('-d', '--datfile', action='store', dest="datfile", default=None, help='Dat file to be used.')
args = parser.parse_args()

address = None
zipfile = None
hexfile = None
datfile = None

if args.address is not None:
    address = args.address

if args.zipfile is not None:
    zipfile = args.zipfile
    unpacker = Unpacker()
    try:
        hexfile, datfile = unpacker.unpack_zipfile(zipfile)	
    except Exception as e:
        logging.info(f"An exception occured when trying to unpack zipfile: {e}")

else:
    if args.hexfile is not None:
        hexfile = args.hexfile
    else:
        logging.warning("Hexfile is not specified! Can not perform Secure DFU!")
        sys.exit(0)

    if args.datfile is not None:
        datfile = args.datfile
    else:
        logging.warning("Datfile is not specified! Can not perform Secure DFU!")
        sys.exit(0)

if address is None:
    logging.warning("No device address specified.")
    time.sleep(1)
    loop = asyncio.get_event_loop()
    devices = get_ble_devices(loop)
    selected_device = select_ble_device(devices)
    address = selected_device

if hexfile is not None and datfile is not None:
    # dfu sometimes fails, retry until it succeeds
    # TODO: find out WHY dfu fails
    success = False
    fail_counter = 0
    while not success:

        if fail_counter > 5:  # stop after 5 retries
            logging.error(f"Failed to perform DFU on device {address}. Exiting.")
            break

        try:
            # initialize dfu class
            dfu = SecureDfu(address, hexfile, datfile)
            dfu.perform_dfu()
            success = True
            if not success:
                fail_counter += 1
        except Exception as e:
            logging.error(f"Unable to perform dfu. Reason: {e}")
            
        time.sleep(1)

