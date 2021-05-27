import math
import pexpect
import time
import logging

from array import array
from ota_dfu_python.util import *

from ota_dfu_python.nrf_ble_dfu_controller import NrfBleDfuController

verbose = False

class Procedures:
    CREATE          = 0x01
    SET_PRN         = 0x02
    CALC_CHECKSUM   = 0x03
    EXECUTE         = 0x04
    SELECT          = 0x06
    RESPONSE        = 0x60

    PARAM_COMMAND   = 0x01
    PARAM_DATA      = 0x02

    string_map = {
        CREATE          : "CREATE",
        SET_PRN         : "SET_PRN",
        CALC_CHECKSUM   : "CALC_CHECKSUM",
        EXECUTE         : "EXECUTE",
        SELECT          : "SELECT",
        RESPONSE        : "RESPONSE",
    }

    @staticmethod
    def to_string(proc):
        return Procedures.string_map[proc]

    @staticmethod
    def from_string(proc_str):
        return int(proc_str, 16)

class Results:
    INVALID_CODE                = 0x00
    SUCCESS                     = 0x01
    OPCODE_NOT_SUPPORTED        = 0x02
    INVALID_PARAMETER           = 0x03
    INSUFF_RESOURCES            = 0x04
    INVALID_OBJECT              = 0x05
    UNSUPPORTED_TYPE            = 0x07
    OPERATION_NOT_PERMITTED     = 0x08
    OPERATION_FAILED            = 0x0A

    string_map = {
        INVALID_CODE            : "INVALID_CODE",
        SUCCESS                 : "SUCCESS",
        OPCODE_NOT_SUPPORTED    : "OPCODE_NOT_SUPPORTED",
        INVALID_PARAMETER       : "INVALID_PARAMETER",
        INSUFF_RESOURCES        : "INSUFFICIENT_RESOURCES",
        INVALID_OBJECT          : "INVALID_OBJECT",
        UNSUPPORTED_TYPE        : "UNSUPPORTED_TYPE",
        OPERATION_NOT_PERMITTED : "OPERATION_NOT_PERMITTED",
        OPERATION_FAILED        : "OPERATION_FAILED",
    }

    @staticmethod
    def to_string(res):
        return Results.string_map[res]

    @staticmethod
    def from_string(res_str):
        return int(res_str, 16)


class BleDfuControllerSecure(NrfBleDfuController):
    # Class constants
    UUID_BUTTONLESS      = '8ec90003-f315-4f60-9fb8-838830daea50'  # changed ed to ec for buttonless nordic characteristic
    UUID_CONTROL_POINT   = '8ec90001-f315-4f60-9fb8-838830daea50'
    UUID_PACKET          = '8ec90002-f315-4f60-9fb8-838830daea50'

    # Constructor inherited from abstract base class

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
    #  Check if the peripheral is running in bootloader (DFU) or application mode
    #  Returns True if the peripheral is in DFU mode
    # --------------------------------------------------------------------------
    def check_DFU_mode(self):
        logging.info("Checking DFU State...")

        self.ble_conn.sendline('characteristics')

        dfu_mode = False

        try:
            logging.info("Trying to find buttonless dfu characteristic")
            self.ble_conn.expect(self.UUID_BUTTONLESS, timeout=2)
        except pexpect.TIMEOUT as e:
            dfu_mode = True

        return dfu_mode

    def switch_to_dfu_mode(self):
        logging.info("Switching to DFU mode")
        (_, bl_value_handle, bl_cccd_handle) = self._get_handles(self.UUID_BUTTONLESS)

        cmd  = 'char-write-req 0x%04x %s' % (bl_cccd_handle, '02')
        logging.debug(f"Writing: {cmd}")
        self.ble_conn.sendline(cmd)
        # Verify that command was successfully written
        try:
            res = self.ble_conn.expect('Characteristic value was written successfully.*', timeout=2)
        except pexpect.TIMEOUT as e:
            logging.error(f"State timeout when switching to dfu mode: {e}")

        # Reset the board in DFU mode. After reset the board will be disconnected
        cmd = 'char-write-req 0x%04x 01' % (bl_value_handle)
        logging.debug(f"Writing: {cmd}")
        self.ble_conn.sendline(cmd)

        # Wait some time for board to reboot
        time.sleep(2)

        # Increase the mac address by one and reconnect
        self.target_mac_increase(1)
        return self.scan_and_connect()

    # --------------------------------------------------------------------------
    #  Parse notification status results
    # --------------------------------------------------------------------------
    def _dfu_parse_notify(self, notify):
        if len(notify) < 3:
            logging.error("Notify data length error")
            return None

        logging.debug(notify)

        dfu_notify_opcode = Procedures.from_string(notify[0])
        if dfu_notify_opcode == Procedures.RESPONSE:

            dfu_procedure = Procedures.from_string(notify[1])
            dfu_result  = Results.from_string(notify[2])

            procedure_str = Procedures.to_string(dfu_procedure)
            result_str  = Results.to_string(dfu_result)

            logging.debug("opcode: 0x%02x, proc: %s, res: %s" % (dfu_notify_opcode, procedure_str, result_str))

            # Packet Receipt notifications are sent in the exact same format
            # as responses to the CALC_CHECKSUM procedure.
            if(dfu_procedure == Procedures.CALC_CHECKSUM and dfu_result == Results.SUCCESS):
                offset = bytes_to_uint32_le(notify[3:7])
                crc32 = bytes_to_uint32_le(notify[7:11])

                return (dfu_procedure, dfu_result, offset, crc32)

            elif(dfu_procedure == Procedures.SELECT and dfu_result == Results.SUCCESS):
                max_size = bytes_to_uint32_le(notify[3:7])
                offset = bytes_to_uint32_le(notify[7:11])
                crc32 = bytes_to_uint32_le(notify[11:15])

                return (dfu_procedure, dfu_result, max_size, offset, crc32)

            else:
                return (dfu_procedure, dfu_result)

    # --------------------------------------------------------------------------
    #  Wait for a notification and parse the response
    # --------------------------------------------------------------------------
    def _wait_and_parse_notify(self):
        
        logging.debug("Waiting for notification")
        notify = self._dfu_wait_for_notify()

        if notify is None:
            raise Exception("No notification received")

        logging.debug("Parsing notification")

        result = self._dfu_parse_notify(notify)
        if result[1] != Results.SUCCESS:
            raise Exception("Error in {} procedure, reason: {}".format(
                Procedures.to_string(result[0]),
                Results.to_string(result[1])))

        return result

    # --------------------------------------------------------------------------
    #  Send the Init info (*.dat file contents) to peripheral device.
    # --------------------------------------------------------------------------
    def _dfu_send_init(self):

        logging.debug("DFU SEND INIT")
        # Open the DAT file and create array of its contents
        init_bin_array = array('B', open(self.datfile_path, 'rb').read())
        init_size = len(init_bin_array)
        init_crc = 0

        # Select command
        self._dfu_send_command(Procedures.SELECT, [Procedures.PARAM_COMMAND])
        try:
            (proc, res, max_size, offset, crc32) = self._wait_and_parse_notify()
        except Exception as e:
            logging.error(f"An error when waiting for notification 0: {e}")
            return None

        if offset != init_size or crc32 != init_crc:
            if offset == 0 or offset > init_size:
                # Create command
                self._dfu_send_command(Procedures.CREATE, [Procedures.PARAM_COMMAND] + uint32_to_bytes_le(init_size))
                try:
                    res = self._wait_and_parse_notify()
                except Exception as e:
                    logging.error(f"An error when waiting for notification 1: {e}")
                    return None

                segment_count = 0
                segment_total = int(math.ceil(init_size/float(self.pkt_payload_size)))

                for i in range(0, init_size, self.pkt_payload_size):
                    segment = init_bin_array[i:i + self.pkt_payload_size]
                    self._dfu_send_data(segment)
                    segment_count += 1

                    if (segment_count % self.pkt_receipt_interval) == 0:
                        try:
                            (proc, res, offset, crc32) = self._wait_and_parse_notify()
                        except Exception as e:
                            logging.error(f"An error when waiting for notification 2: {e}")
                            return None

                        if res != Results.SUCCESS:
                            raise Exception("bad notification status: {}".format(Results.to_string(res)))
                        
            else:
                self._dfu_send_command(Procedures.EXECUTE)
                try:
                    res = self._wait_and_parse_notify()
                except Exception as e:
                    logging.error(f"An error when waiting for notification 3: {e}")
                    return None

                # Select command
                self._dfu_send_command(Procedures.SELECT, [Procedures.PARAM_COMMAND])
                try:
                    (proc, res, max_size, offset, crc32) = self._wait_and_parse_notify()
                except Exception as e:
                    logging.error(f"An error when waiting for notification 0: {e}")
                    return None


            # Calculate CRC
            self._dfu_send_command(Procedures.CALC_CHECKSUM)
            try:
                self._wait_and_parse_notify()
            except Exception as e:
                logging.error(f"An error when waiting for notification 3: {e}")
                return None

        # Execute command
        self._dfu_send_command(Procedures.EXECUTE)
        try:
            self._wait_and_parse_notify()
        except Exception as e:
            return None

        logging.debug("Init packet successfully transfered")

    # --------------------------------------------------------------------------
    #  Send the Firmware image to peripheral device.
    # --------------------------------------------------------------------------
    def _dfu_send_image(self):
        logging.debug("Sending DFU image")

        # Select Data Object
        self._dfu_send_command(Procedures.SELECT, [Procedures.PARAM_DATA])
        try:
            (proc, res, max_size, offset, crc32) = self._wait_and_parse_notify()
        except Exception as e:
            return None

        # Split the firmware into multiple objects
        num_objects = int(math.ceil(self.image_size / float(max_size)))
        logging.debug("Max object size: %d, num objects: %d, offset: %d, total size: %d" % (max_size, num_objects, offset, self.image_size))

        time_start = time.time()
        last_send_time = time.time()

        obj_offset = int(offset / max_size) * max_size
        dfu_failed = False
        while obj_offset < self.image_size:
            ret = self._dfu_send_object(obj_offset, max_size)
            if ret is not None:
                obj_offset += ret
            else:
                dfu_failed = True

        # Image uploaded successfully, update the progress bar
        print_progress(self.image_size, self.image_size, barLength = 50)

        duration = time.time() - time_start
        logging.info("Upload complete in {} minutes and {} seconds".format(int(duration / 60), int(duration % 60)))

    # --------------------------------------------------------------------------
    #  Send a single data object of given size and offset.
    # --------------------------------------------------------------------------
    def _dfu_send_object(self, offset, obj_max_size):
        if offset != self.image_size:
            if offset == 0 or offset >= obj_max_size:  # or crc32 != crc32_unsigned(self.bin_array[0:offset]):
                # Create Data Object
                size = min(obj_max_size, self.image_size - offset)
                self._dfu_send_command(Procedures.CREATE, [Procedures.PARAM_DATA] + uint32_to_bytes_le(size))
                try:
                    self._wait_and_parse_notify()
                except Exception as e:
                    return None

            segment_count = 0
            segment_total = int(math.ceil(min(obj_max_size, self.image_size-offset)/float(self.pkt_payload_size)))

            segment_begin = offset
            segment_end = min(offset+obj_max_size, self.image_size)

            for i in range(segment_begin, segment_end, self.pkt_payload_size):
                num_bytes = min(self.pkt_payload_size, segment_end - i)
                segment = self.bin_array[i:i + num_bytes]
                self._dfu_send_data(segment)
                segment_count += 1

                if (segment_count % self.pkt_receipt_interval) == 0:
                    try:
                        (proc, res, offset, crc32) = self._wait_and_parse_notify()
                    except Exception as e:
                        # Likely no notification received, need to re-transmit object
                        return 0

                    if res != Results.SUCCESS:
                        raise Exception("bad notification status: {}".format(Results.to_string(res)))

                    if crc32 != crc32_unsigned(self.bin_array[0:offset]):
                        # Something went wrong, need to re-transmit this object
                        return 0

                    print_progress(offset, self.image_size, barLength = 50)

            # Calculate CRC
            self._dfu_send_command(Procedures.CALC_CHECKSUM)
            (proc, res, offset, crc32) = self._wait_and_parse_notify()
            if(crc32 != crc32_unsigned(self.bin_array[0:offset])):
                # Need to re-transmit object
                return 0

        # Execute command
        self._dfu_send_command(Procedures.EXECUTE)
        self._wait_and_parse_notify()

        # If everything executed correctly, return amount of bytes transfered
        return obj_max_size
