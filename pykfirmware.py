#!/usr/bin/env python
# coding: utf-8
r"""
__   __         _    _ _
\ \ / /__ _ __ | | _(_) |_
 \ V / _ \ '_ \| |/ / | __|
  | |  __/ |_) |   <| | |_
  |_|\___| .__/|_|\_\_|\__|
         |_| http://yepkit.com/

Yepkit firmware update tool v0.0.1 **YKUSH PREVIEW VERSION**

This application supports hidapi and hidapi-cffi, please choose
according to your preference:
  https://pypi.python.org/pypi/hidapi
    or
  https://pypi.python.org/pypi/hidapi-cffi

For now the use of You will also need the future module to 

Copyright 2016, 2013 Yepkit Lda and other contributors
Released under the MIT license, please read the file LICENSE.txt

Date: 2016-11-02

Usage:
    usage: pykfirmware.py [-h] [-s SERIAL] infile

    Yepkit firmware update tool **YKUSH PREVIEW VERSION**

    positional arguments:
      infile                the input Intel HEX filename

    optional arguments:
      -h, --help            show this help message and exit
      -s SERIAL, --serial SERIAL
                            the USB device serial number string

Notes:
  * This is a work in progress that started as a collage code with several chained
    and superfluous transformations, please be warned about the code performance.
  * The code supports both Python 2 and 3
  * Works on Linux, Windows and Mac

"""

from __future__ import unicode_literals
from __future__ import print_function
try:
    from future.utils import bytes_to_native_str
except (ImportError):
    # python -m pip install --user future
    print('Please ensure that you have the future module installed.')
    print('If you are confortable with Python, it should be as simple as:')
    print('\tpython -m pip install --user future')
    raise
import sys
import time
import array
import struct
import binascii
import argparse
_usingHid = False
try:
    import hid
    _usingHid = True
except (ImportError, OSError):
    try:
        import hidapi
    except (ImportError, OSError):
        print('Please ensure that you have hidapi or hidapi-cffi installed,')
        print('any of them are supported.')
        print('If you are confortable with Python, it should be as simple as:')
        print('\tpython -m pip install --user cython')
        print('\tpython -m pip install --user hidapi')
        raise

__version__ = '0.0.1'

# YKUSH device USB VID
YKUSH_USB_VID = 0x04d8
# YKUSH PIDs when in normal operation mode: YKUSH beta, YKUSH, YKUSH3
YKUSH_USB_PID_LIST = (0x0042, 0xf2ff, 0xf11b, 0xf2fd)
# YKUSH PIDs when in bootloader mode: YKUSH, YKUSH3
YKUSH_USB_PID_BL_LIST = (0xf11c, 0xf0cd)

# YKUSH device USB comm declarations
YKUSH_USB_TIMEOUT = 1000  # timeout in ms
YKUSH_USB_PACKET_SIZE = 64
YKUSH_USB_PACKET_PAYLOAD_SIZE = YKUSH_USB_PACKET_SIZE

# YKUSH device protocol status declarations
YKUSH_PROTO_OK_STATUS = 1

# Bootloader packet commands
YKBL_CMD_QUERY_DEVICE = 0x02
YKBL_CMD_UNLOCK_CONFIG = 0x03
YKBL_CMD_ERASE_DEVICE = 0x04
YKBL_CMD_PROGRAM_DEVICE = 0x05
YKBL_CMD_PROGRAM_COMPLETE = 0x06
YKBL_CMD_GET_DATA = 0x07
YKBL_CMD_RESET_DEVICE = 0x08
YKBL_CMD_SIGN_FLASH = 0x09  # The host PC application should send this command after the verify operation has completed successfully.  If checksums are used instead of a true verify (due to ALLOW_GET_DATA_COMMAND being commented), then the host PC application should send SIGN_FLASH command after is has verified the checksums are as exected. The firmware will then program the SIGNATURE_WORD into flash at the SIGNATURE_ADDRESS.
YKBL_CMD_QUERY_EXTENDED_INFO = 0x0C  # Used by host PC app to get additional info about the device, beyond the basic NVM layout provided by the query device command


# Not the most pythonic way to print to the terminal but we do prefer it to avoid weird future imports, flush or
# compatibility issues
def printout(str='', end='\n', flush=True):
    sys.stdout.write(str + end)
    if flush:
        sys.stdout.flush()


# Same as the previous but pointing to stderr
def printerr(str='', end='\n', flush=True):
    sys.stderr.write(str + end)
    if flush:  # a paranoid touch as stderr is supposed to be non buffered by default
        sys.stderr.flush()


# simple hidapi and hidapi_cffi function wrapper helper
def hid_enumerate(vid=0, pid=0):
    '''HID enumerate wrapper function'''
    for info in hid.enumerate(vid, pid) if _usingHid else hidapi.enumerate(vid, pid):
        if _usingHid:
            ret = info
        else:
            # unfortunately there is no __dict__ attr in the cffi DeviceInfo object
            ret = dict([(p, getattr(info, p)) for p in info.__slots__])
        yield ret


# device not found exception
class YKUSHNotFound(Exception):
    '''YKUSH not found exception'''

    def __str__(self):
        return 'YKUSH device not found'


# YKUSH_ex class definition
class YKUSH_ex(object):
    '''YKUSH_ex hidapi based interface class'''

    def __init__(self, serial=None, path=None):
        '''Constructor, the algorithm will connect to the first YKUSH found if a path or serial number is not provided'''
        self._devhandle = None
        self._firmware_major_version = None
        self._firmware_minor_version = None
        self._downstream_port_count = None
        if path:
            # open the provided path
            if _usingHid:
                # blocking by default
                self._devhandle = hid.device()
                self._devhandle.open_path(path)
            else:
                # also blocking by default but ensure it is
                self._devhandle = hidapi.Device(path=path, blocking=True)
        else:
            # otherwise try to locate a device
            for device in hid_enumerate(0, 0):
                if device['vendor_id'] == YKUSH_USB_VID and device['product_id'] in YKUSH_USB_PID_LIST:
                    if serial is None or serial == device['serial_number']:
                        return self.__init__(path=device['path'])
        if self._devhandle is None:
            raise YKUSHNotFound()

    def __del__(self):
        '''Destructor, release the device'''
        if self._devhandle:
            self._devhandle.close()

    def get_firmware_version_APP_MODE_ONLY(self):
        '''Returns a tuple with YKUSH firmware version in format (major, minor)'''
        if self._firmware_major_version is None:
            status, major, minor = self._raw_sendreceive([0xf0])[:3]
            if status == YKUSH_PROTO_OK_STATUS:
                self._firmware_major_version, self._firmware_minor_version = (major, minor)
            else:
                # early devices will not recognize it, figure it out from serial
                self._firmware_major_version = 1
                self._firmware_minor_version = 0xff
        return self._firmware_major_version, self._firmware_minor_version

    def _raw_sendreceive(self, packetarray):
        '''Internal method, submit a command and read the response from YKUSH'''
        # build the packet according to the report packet size
        # note: no buffer optimization was made for the sake of simplicity
        if _usingHid:
            packetarray = [0x00] + packetarray + [0x00] * (YKUSH_USB_PACKET_SIZE - len(packetarray))
            self._devhandle.write(packetarray)
            recvpacket = self._devhandle.read(max_length=YKUSH_USB_PACKET_SIZE + 1, timeout_ms=YKUSH_USB_TIMEOUT)
        else:
            packetarray = packetarray + [0x00] * (YKUSH_USB_PACKET_SIZE - len(packetarray))
            packet = struct.pack('<%dB' % YKUSH_USB_PACKET_SIZE, *packetarray)
            self._devhandle.write(packet)
            recvpacket = self._devhandle.read(length=YKUSH_USB_PACKET_SIZE + 1, timeout_ms=YKUSH_USB_TIMEOUT)
        # if not None return the bytes we actually need
        if recvpacket is None or len(recvpacket) < YKUSH_USB_PACKET_PAYLOAD_SIZE:
            return [0xff] * YKUSH_USB_PACKET_PAYLOAD_SIZE
        return recvpacket[:YKUSH_USB_PACKET_PAYLOAD_SIZE] if _usingHid else struct.unpack('<%iB' % YKUSH_USB_PACKET_PAYLOAD_SIZE, recvpacket[:YKUSH_USB_PACKET_PAYLOAD_SIZE])


def main():
    # Parser definition
    parser = argparse.ArgumentParser(description='Yepkit firmware update tool **YKUSH PREVIEW VERSION**')
    parser.add_argument('infile', type=argparse.FileType('r'), help='the input Intel HEX filename')
    parser.add_argument('-s', '--serial', default=None, help='the USB device serial number string')
    args = parser.parse_args()
    printout('%s\n%s' % (parser.description, 'Progress status (9 steps):'))
    # find the device and enter bootloader mode if located
    printout('1. Enumerating devices...', end='')
    yk_app = None
    for device in hid_enumerate(0, 0):
        if device['vendor_id'] == YKUSH_USB_VID and device['product_id'] in YKUSH_USB_PID_LIST:
            if args.serial is None or args.serial == device['serial_numnber']:
                yk_app = YKUSH_ex(path=device['path'])
                if yk_app.get_firmware_version_APP_MODE_ONLY()[0] >= 2:
                    # enter bootloader mode
                    yk_app._raw_sendreceive([0xfd])
                    # leave the loop
                    break
    if yk_app:
        printout('device located, bootloader operating more requested.')
        # settle down a sec before enumerate again
        time.sleep(3)
    else:
        printout('done.')
    # now locate the device running in bootloader mode
    printout('2. Opening device in bootloader mode...', end='')
    yk_bl = None
    yk_sn = ''
    for device in hid_enumerate(0, 0):
        if device['vendor_id'] == YKUSH_USB_VID and device['product_id'] in YKUSH_USB_PID_BL_LIST:
            if args.serial is None or args.serial == device['serial_numnber']:
                yk_bl = YKUSH_ex(path=device['path'])
                yk_sn = device['serial_number']
    if yk_bl is None:
        printout('no devices located.')
        printerr('> No YKUSH devices found in bootloader mode')
        printerr('> Note: the tool only works on early development firmware versions (>=v2)')
        sys.exit(1)
    else:  # device located
        printout('selected device serial number = %s' % yk_sn)
        # query device bootloader settings
        devbytesperaddress, devmemaddress, devmemlength = 0, 0, 0
        recvpacket = yk_bl._raw_sendreceive([YKBL_CMD_QUERY_DEVICE])
        (bogus, devpacketdatafieldsize, devbytesperaddress, devmemtype, devmemaddress, devmemlength) = \
            struct.unpack_from('<4B2L', struct.pack('<%iB' % 16, *recvpacket[:16]))
        printout('3. Device programmable region: 0x%x to 0x%x' % (devmemaddress, devmemaddress + devmemlength))
        # Parse the Intel HEX file
        printout('4. Importing .hex file...', end='')
        hexrecinfo = struct.Struct('>BHB')  # Big-endian modifier and the formatting structs
        hexrecsegm = struct.Struct('>H')
        flashbuffer = [x for x in [0x3f, 0xff] * (devmemlength // 2)]
        ln = 0  # Line number reference
        segmaddr = 0  # Segment address reference
        for rec in args.infile.readlines():  # For each .hex file line
            ln += 1  # Keep the line number info in case we need to report an error
            if rec[0] != ':':  # Minimalistic consistency checks
                printout()
                printerr('> Unrecognized Intel HEX format, affected line: %i' % ln)
                sys.exit(1)
            (rsize, raddr, rtype) = hexrecinfo.unpack(binascii.unhexlify(rec[1:9]))  # Get the record size, address and type
            raddr += segmaddr
            rsum = 0  # Sum the record bytes according to the proposed format
            for i in range(1, 9 + rsize * 2, 2):
                rsum += int(rec[i:(i + 2)], 16)
            csum = (~rsum + 1) & 0xff  # Compute the checksum based on the two's complement and ensure the result is a byte
            if int(rec[(9 + rsize * 2):(11 + rsize * 2)], 16) != csum:  # A few more validations before proceed
                # Oops, checksum mismatch
                printout()
                printerr('> Checksum mismatch, affected line: %i' % ln)
                return 1
            elif rsize % devbytesperaddress:
                # Unaligned records
                printout()
                printerr('> Expecting a multiple of %i byte(s) record, affected line: %i' % ln)
                return 1
            if rtype in (0x02, 0x04):
                # Segment or linear addresses
                segmaddr = hexrecsegm.unpack(binascii.unhexlify(rec[9:13]))[0]
                if rtype == 0x02:
                    segmaddr <<= 4
                else:
                    segmaddr <<= 16
            elif rtype == 0:
                # Data type record
                devaddr = raddr
                # Get the payload
                # print(rec[9:(9 + rsize * 2)])
                rpayload = array.array(bytes_to_native_str(b'B'), binascii.unhexlify(rec[9:(9 + rsize * 2)]))
                # print(rpayload)
                mstart, mend = int(devaddr - devmemaddress), int(devaddr + len(rpayload) - devmemaddress)
                # print(rpayload)
                # print(mstart, mend)
                # Fill the buffer if between boundaries
                if 0 <= mstart < devmemaddress + devmemlength:
                    if mend > devmemaddress + devmemlength:
                        mend = devmemaddress + devmemlength
                    flashbuffer[mstart:mend] = rpayload[:mend - mstart]
        printout('done.')

        # Erase device
        printout('5. Erasing device before programming...', end='')
        yk_bl._raw_sendreceive([YKBL_CMD_ERASE_DEVICE])
        printout('done.')

        # Program device
        printout('6. Programming device, please wait..', end='')
        cosmeticprogress = 0
        writeerror = 0
        offset = devmemaddress
        for chunk in (flashbuffer[pos:pos + 56] for pos in
                      range(0, len(flashbuffer), 56)):
            if cosmeticprogress % 3 == 0:
                printout('.', end='')
            sendpacket = struct.pack('<BLBBB%iB' % len(chunk), YKBL_CMD_PROGRAM_DEVICE, offset,
                                     len(chunk) * devbytesperaddress, 0, 0, *chunk)
            for retry in range(3, -1, -1):
                try:
                    recvpacket = yk_bl._raw_sendreceive(list(struct.unpack('<%iB' % len(sendpacket), sendpacket)))
                    break
                except (IOError, OSError) as e:
                    time.sleep(.1)
                    writeerror += 1
                    if writeerror > 20:
                        print('too many errors:', writeerror)
                        # sys.exit(1)
                    if not retry:
                        printout()
                        printerr('> Got an error trying to program the device at address: 0x%x' % offset)
                        if e.message is not None and e.message != '':
                            printerr('> Error message: %s' % e.message)
                        # sys.exit(1)
            offset += 56
            cosmeticprogress += 1

        # Finish signalling program complete
        yk_bl._raw_sendreceive([YKBL_CMD_PROGRAM_COMPLETE])
        printout('done.')

        # Verify the written flash
        printout('7. Verifying the written data...', end='')
        offset = devmemaddress
        for chunk in (flashbuffer[pos:pos + 56] for pos in range(0, len(flashbuffer), 56)):
            sendpacket = struct.pack('<BLB', YKBL_CMD_GET_DATA, offset, len(chunk))
            recvpacket = yk_bl._raw_sendreceive(list(struct.unpack('<%iB' % len(sendpacket), sendpacket)))
            recvunpacked = struct.unpack_from('<BHBBBBB%iB' % 56, struct.pack('<%iB' % len(recvpacket), *recvpacket))
            for i, j in zip(chunk, recvunpacked[7:]):
                if i != j and i != 0xff and i != 0x3f:
                    printout()
                    printerr('> Data inconsistency detected at the offset: 0x%x.' % offset)
                    sys.exit(1)
            offset += 56
        printout('done.')

        # Sign flash
        printout('8. Signing image...', end='')
        yk_bl._raw_sendreceive([YKBL_CMD_SIGN_FLASH])
        printout('done.')

        # Finally reboot the device to start the user application
        printout('9. Resetting device...', end='')
        try:
            yk_bl._raw_sendreceive([YKBL_CMD_RESET_DEVICE])
        except (IOError, OSError):
            pass
        printout('done.')

if __name__ == '__main__':
    main()
