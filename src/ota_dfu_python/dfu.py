#!/usr/bin/env python3
"""
------------------------------------------------------------------------------
 DFU Server for Nordic nRF51 based systems.
 Conforms to nRF51_SDK 11.0 BLE_DFU requirements.
------------------------------------------------------------------------------
"""
import os, re
import sys
import optparse
import time
import math
import traceback
import asyncio
import logging

from ota_dfu_python.unpacker import Unpacker

from ota_dfu_python.ble_secure_dfu_controller import BleDfuControllerSecure

class SecureDfu():
    def __init__(self, address, zipfile=None, hexfile=None, datfile=None):
        self.address = address
        self.zipfile = zipfile
        self.hexfile = hexfile
        self.datfile = datfile

        self.unpacker = Unpacker()

        self.can_perform_dfu = True

        if self.zipfile is not None:
            try:
                self.hexfile, self.datfile = self.unpacker.unpack_zipfile(self.zipfile)	
            except Exception as e:
                logging.error(f"An exception occured when trying to unpack zipfile: {e}")

        if self.hexfile is None:
            logging.warning("Hexfile is not specified! Can not perform Secure DFU!")
            self.can_perform_dfu = False

        if self.datfile is None:
            logging.warning("Datfile is not specified! Can not perform Secure DFU!")
            self.can_perform_dfu = False

        if self.can_perform_dfu:
            self.ble_dfu = BleDfuControllerSecure(self.address.upper(), self.hexfile, self.datfile)
            # Initialize inputs
            self.ble_dfu.input_setup()

    def perform_dfu(self):
        """Perform OTA DFU on BLE device with selected address"""

        if self.can_perform_dfu:
            # Connect to peer device. Assume application mode.
            if self.ble_dfu.scan_and_connect():  # works
                dfu_mode = self.ble_dfu.check_DFU_mode()
                # assume false: 
                # dfu_mode = False
                logging.info(f"Device dfu mode: {dfu_mode}")
                if not dfu_mode:
                    logging.info("Need to switch to DFU mode")
                    success = self.ble_dfu.switch_to_dfu_mode()
                    if not success:
                        logging.info("Couldn't reconnect")
            else:
                # The device might already be in DFU mode (MAC + 1)
                self.ble_dfu.target_mac_increase(1)

                # Try connection with new address
                logging.info("Couldn't connect, will try DFU MAC")
                if not self.ble_dfu.scan_and_connect():
                    raise Exception("Can't connect to device")

            self.ble_dfu.start()

            # Disconnect from peer device if not done already and clean up.
            self.ble_dfu.disconnect()

            return True
        
        return False