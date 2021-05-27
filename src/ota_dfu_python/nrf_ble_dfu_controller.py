import os
import pexpect
import re
import logging
import time

from abc   import ABCMeta, abstractmethod
from array import array
from src.ota_dfu_python.util  import *

verbose = False

class NrfBleDfuController(object, metaclass=ABCMeta):
    ctrlpt_handle        = 0
    ctrlpt_cccd_handle   = 0
    data_handle          = 0

    pkt_receipt_interval = 10
    pkt_payload_size     = 20

    # --------------------------------------------------------------------------
    #  Start the firmware update process
    # --------------------------------------------------------------------------
    @abstractmethod
    def start(self):
        pass

    # --------------------------------------------------------------------------
    #  Check if the peripheral is running in bootloader (DFU) or application mode
    #  Returns True if the peripheral is in DFU mode
    # --------------------------------------------------------------------------
    @abstractmethod
    def check_DFU_mode(self):
        pass

    @abstractmethod
    # --------------------------------------------------------------------------
    #  Switch from application to bootloader (DFU)
    # --------------------------------------------------------------------------
    def switch_to_dfu_mode(self):
        pass

    # --------------------------------------------------------------------------
    #  Parse notification status results
    # --------------------------------------------------------------------------
    @abstractmethod
    def _dfu_parse_notify(self, notify):
        pass

    # --------------------------------------------------------------------------
    #  Wait for a notification and parse the response
    # --------------------------------------------------------------------------
    @abstractmethod
    def _wait_and_parse_notify(self):
        pass

    def __init__(self, target_mac, firmware_path, datfile_path):
        self.target_mac = target_mac

        self.firmware_path = firmware_path
        self.datfile_path = datfile_path

        logging.debug(f"Firmware path: {firmware_path}")

        self.ble_conn = pexpect.spawn("gatttool -b '%s' -t random --interactive" % target_mac)
        self.ble_conn.delaybeforesend = 0

    # --------------------------------------------------------------------------
    #  Start the firmware update process
    # --------------------------------------------------------------------------
    def start(self):
        (_, self.ctrlpt_handle, self.ctrlpt_cccd_handle) = self._get_handles(self.UUID_CONTROL_POINT)
        (_, self.data_handle, _) = self._get_handles(self.UUID_PACKET)

        logging.debug('Control Point Handle: 0x%04x, CCCD: 0x%04x' % (self.ctrlpt_handle, self.ctrlpt_cccd_handle))
        logging.debug('Packet handle: 0x%04x' % (self.data_handle))

        # Subscribe to notifications from Control Point characteristic
        self._enable_notifications(self.ctrlpt_cccd_handle)

        # Set the Packet Receipt Notification interval
        prn = uint16_to_bytes_le(self.pkt_receipt_interval)
        self._dfu_send_command(Procedures.SET_PRN, prn)

        self._dfu_send_init()

        self._dfu_send_image()

    # --------------------------------------------------------------------------
    # Initialize: 
    #    Hex: read and convert hexfile into bin_array 
    #    Bin: read binfile into bin_array
    # --------------------------------------------------------------------------
    def input_setup(self):
        logging.debug("Sending file " + os.path.split(self.firmware_path)[1] + " to " + self.target_mac)

        if self.firmware_path == None:
            raise Exception("input invalid")

        name, extent = os.path.splitext(self.firmware_path)

        if extent == ".bin":
            self.bin_array = array('B', open(self.firmware_path, 'rb').read())

            self.image_size = len(self.bin_array)
            # print("Binary imge size: %d" % self.image_size)

            return

        if extent == ".hex":
            intelhex = IntelHex(self.firmware_path)
            self.bin_array = intelhex.tobinarray()
            self.image_size = len(self.bin_array)
            logging.debug("Bin array size: ", self.image_size)
            return

        raise Exception("Input invalid")

    # --------------------------------------------------------------------------
    # Perform a scan and connect via gatttool.
    # Will return True if a connection was established, False otherwise
    # --------------------------------------------------------------------------
    def scan_and_connect(self, timeout=2):
        """Try to connect to device"""
        logging.info("Connecting to %s" % (self.target_mac))

        try:
            self.ble_conn.expect('\[LE\]>', timeout=timeout)
        except pexpect.TIMEOUT as e:
            logging.warning(f"Timeout during scan: {e}")
            return False

        self.ble_conn.sendline('connect')

        try:
            res = self.ble_conn.expect('.*Connection successful.*', timeout=timeout)
        except pexpect.TIMEOUT as e:
            logging.warning(f"Timeout during connect: {e}")
            return False

        return True

    # --------------------------------------------------------------------------
    #  Disconnect from the peripheral and close the gatttool connection
    # --------------------------------------------------------------------------
    def disconnect(self):
        self.ble_conn.sendline('exit')
        self.ble_conn.close()

    def target_mac_increase(self, inc):
        self.target_mac = uint_to_mac_string(mac_string_to_uint(self.target_mac) + inc)

        # Re-start gatttool with the new address
        self.disconnect()
        self.ble_conn = pexpect.spawn("gatttool -b '%s' -t random --interactive" % self.target_mac)
        self.ble_conn.delaybeforesend = 0

    # --------------------------------------------------------------------------
    #  Fetch handles for a given UUID.
    #  Will return a three-tuple: (char handle, value handle, CCCD handle)
    #  Will raise an exception if the UUID is not found
    # --------------------------------------------------------------------------
    def _get_handles(self, uuid):
        self.ble_conn.before = ""
        self.ble_conn.sendline('characteristics')

        try:
            self.ble_conn.expect([uuid], timeout=10)
            handles = re.findall(b'.*handle: (0x....),.*char value handle: (0x....)', self.ble_conn.before)
            # print(f"Found handles: {handles} on uuid: {uuid}")
            (handle, value_handle) = handles[-1]
            # print(f"Selected handle: {handle}, value handle: {value_handle}")
        except pexpect.TIMEOUT as e:
            raise Exception("UUID not found: {}".format(uuid))

        return (int(handle, 16), int(value_handle, 16), int(value_handle, 16)+1)

    # --------------------------------------------------------------------------
    #  Wait for notification to arrive.
    #  Example format: "Notification handle = 0x0019 value: 10 01 01"
    # --------------------------------------------------------------------------
    def _dfu_wait_for_notify(self):
        while True:
            if not self.ble_conn.isalive():
                logging.warning("Connection not alive")
                return None

            try:
                index = self.ble_conn.expect('Notification handle = .*? \r\n', timeout=30)

                print(f"Received notification index: {index}")

            except pexpect.TIMEOUT as e:
                #
                # The gatttool does not report link-lost directly.
                # The only way found to detect it is monitoring the prompt '[CON]'
                # and if it goes to '[   ]' this indicates the connection has
                # been broken.
                # In order to get a updated prompt string, issue an empty
                # sendline('').  If it contains the '[   ]' string, then
                # raise an exception. Otherwise, if not a link-lost condition,
                # continue to wait.
                #
                self.ble_conn.sendline('')
                string = self.ble_conn.before
                try:
                    if '[   ]' in string:
                        logging.warning('Connection lost!')
                        raise Exception('Connection Lost')
                except Exception as e:
                    logging.error(f"An exception occured when trying to read string: {e}")
                return None

            if index == 0:
                after = self.ble_conn.after
                hxstr = after.split()[3:]
                handle = int(float.fromhex(hxstr[0].decode('UTF-8')))
                return hxstr[2:]

            else:
                logging.warning(f"Unexpeced index: {index}")
                return None

    # --------------------------------------------------------------------------
    #  Send a procedure + any parameters required
    # --------------------------------------------------------------------------
    def _dfu_send_command(self, procedure, params=[]):

        cmd  = 'char-write-req 0x%04x %02x' % (self.ctrlpt_handle, procedure)
        cmd += array_to_hex_string(params)

        print(f"Sending command {cmd}")

        self.ble_conn.sendline(cmd)

        # Verify that command was successfully written
        try:
            res = self.ble_conn.expect('Characteristic value was written successfully.*', timeout=10)
        except pexpect.TIMEOUT as e:
            logging.error(f"State timeout when writing characteristic: {e}")

    # --------------------------------------------------------------------------
    #  Send an array of bytes
    # --------------------------------------------------------------------------
    def _dfu_send_data(self, data):
        cmd  = 'char-write-cmd 0x%04x' % (self.data_handle)
        cmd += ' '
        cmd += array_to_hex_string(data)

        logging.debug(f"Sending cmd {cmd}")

        self.ble_conn.sendline(cmd)

    # --------------------------------------------------------------------------
    #  Enable notifications from the Control Point Handle
    # --------------------------------------------------------------------------
    def _enable_notifications(self, cccd_handle):
        cmd  = 'char-write-req 0x%04x %s' % (cccd_handle, '0100')

        logging.debug(f"Enable notifications: {cmd}")

        self.ble_conn.sendline(cmd)

        # Verify that command was successfully written
        try:
            res = self.ble_conn.expect('Characteristic value was written successfully.*', timeout=10)
        except pexpect.TIMEOUT as e:
            logging.error(f"State timeout in enable notifications: {e}")
