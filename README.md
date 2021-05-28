# Python nRF5 OTA DFU Controller

This is a fork of daniel-thompson's Python OTA DFU utility. We have fixed some bugs and made some changes to make this library installable.

Included changes are:
* DFU always failed if previous DFU was not successful. This is now fixed.
* Basic setup.py to allow installation.
* Only secure DFU has been checked and updated so far. Legacy DFU will be added when we will need it.

## What does it do?

This is a Python program that uses `gatttool` (provided with the Linux BlueZ driver) to achieve Over The Air (OTA) Device Firmware Updates (DFU) to a Nordic Semiconductor nRF5 (either nRF51 or nRF52) device via Bluetooth Low Energy (BLE).


### Main features:

* Perform OTA DFU to an nRF5 peripheral without an external USB BLE dongle.
* Ability to detect if the peripheral is running in application mode or bootloader, and automatically switch if needed (buttonless).
* Support for Secure (SDK >= 12) bootloader only!

Before using this utility the nRF5 peripheral device needs to be programmed with a DFU bootloader (see Nordic Semiconductor documentation/examples for instructions on that).


## Prerequisites

* BlueZ 5.4 or above
* Python 3.7
* Python `pexpect` module (available via pip)
* Python `intelhex` module (available via pip)

## Installation

1. Clone this repo with `git clone https://github.com/IRNAS/ota-dfu-python.git`
2. Run `python3 -m pip install .` to install module.

## Firmware Build Requirement

* Your nRF5 peripheral firmware build method will produce  a firmware file ending with either `*.hex` or `*.bin`.
* Your nRF5 firmware build method will produce an Init file ending with `.dat`.
* The typical naming convention is `application.bin` and `application.dat`, but this utility will accept other names.


## Usage

A `*.zip` file is expected as the input to the Dfu class. Bundle the `*.dat` and `*.hex`/`*.bin` file into a `*.zip` file before running DFU with this library.


## Usage Example

    address = "AB:CD:EF:00:11:22"
    zipfile = "path_to_zipfile.zip"

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

To run the complete example with device discovery and cli parameters run `python3 example.py -a <device_address> -z <dfu_filename>` or `python3 example.py -a <device_address> -d <datfile_filename> -f <hexfile_filename>`. If no address is specified a prompt will appear with all discovered BLE devices, select one from the list.


## Example Output

        ================================
        ==                            ==
        ==         DFU Server         ==
        ==                            ==
        ================================ 

    Sending file application.bin to CD:E3:4A:47:1C:E4
    bin array size:  60788
    Checking DFU State...
    Board needs to switch in DFU mode
    Switching to DFU mode
    Enable Notifications in DFU mode
    Sending hex file size
    Waiting for Image Size notification
    Waiting for INIT DFU notification
    Begin DFU
    Progress: |xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx| 100.0% Complete (60788 of 60788 bytes)

    Upload complete in 0 minutes and 14 seconds


## Info & References

* [Nordic Legacy DFU Service](http://infocenter.nordicsemi.com/topic/com.nordic.infocenter.sdk5.v11.0.0/bledfu_transport_bleservice.html?cp=4_0_3_4_3_1_4_1)
* [Nordic Legacy DFU sequence diagrams](http://infocenter.nordicsemi.com/topic/com.nordic.infocenter.sdk5.v11.0.0/bledfu_transport_bleprofile.html?cp=4_0_3_4_3_1_4_0_1_6#ota_profile_pkt_rcpt_notif)
* [Nordic Secure DFU bootloader](http://infocenter.nordicsemi.com/topic/com.nordic.infocenter.sdk5.v12.2.0/lib_dfu_transport_ble.html?cp=4_0_1_3_5_2_2)
* [nrfutil](https://github.com/NordicSemiconductor/pc-nrfutil)
