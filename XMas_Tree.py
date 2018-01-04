#!/usr/bin/env python
# coding: utf-8
"""
NavVis XMas_Tree Python API and command line tool

This application supports hidapi and hidapi-cffi, please choose
according to your preference:
  https://pypi.python.org/pypi/hidapi
    or
  https://pypi.python.org/pypi/hidapi-cffi

"""

from __future__ import unicode_literals
from __future__ import print_function
import sys
import struct
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
        print('\tpip install --user hidapi')
        raise

__version__ = '0.0.1'

# XMas_Tree device USB VID
XMas_Tree_USB_VID = 0x04d8
# XMas_Tree PIDs when in normal operation mode: Ykush beta, Ykush, Ykush3, XMas_Tree
XMas_Tree_USB_PID_LIST = (0x0041, 0xF2FE)
# XMas_Tree PIDs when in bootloader mode: XMas_Tree, XMas_Tree3
XMas_Tree_USB_PID_BL_LIST = (0xf11c, 0xf0cd)

# XMas_Tree device USB comm declarations
XMas_Tree_USB_TIMEOUT = 1000  # timeout in ms
XMas_Tree_USB_PACKET_SIZE = 64
XMas_Tree_USB_PACKET_PAYLOAD_SIZE = 20

# XMas_Tree device protocol status declarations
XMas_Tree_PROTO_OK_STATUS = 1

# XMas_Tree port state meaning declarations
XMas_Tree_PORT_STATE_UP = 1
XMas_Tree_PORT_STATE_DOWN = 0
XMas_Tree_PORT_STATE_ERROR = 255
XMas_Tree_PORT_STATE_DICT = {0: 'DOWN', 1: 'UP', 255: 'ERROR'}


def hid_enumerate(vid=0, pid=0):
    '''HID enumerate wrapper function'''
    for info in hid.enumerate(vid, pid) if _usingHid else hidapi.enumerate(vid, pid):
        if _usingHid:
            ret = info
        else:
            # unfortunately there is no __dict__ attr in the cffi DeviceInfo object
            ret = dict([(p, getattr(info, p)) for p in info.__slots__])
        yield ret


class XMas_TreeNotFound(Exception):
    '''XMas_Tree not found exception'''

    def __str__(self):
        return 'XMas_Tree device not found'


class XMas_Tree(object):
    '''XMas_Tree hidapi based interface class'''

    def __init__(self, serial=None, path=None):
        '''Constructor, the algorithm will connect to the first XMas_Tree found if a path or serial number is not provided'''
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
                if device['vendor_id'] == XMas_Tree_USB_VID and device['product_id'] in XMas_Tree_USB_PID_LIST:
                    if serial is None or serial == device['serial_number']:
                        return self.__init__(path=device['path'])
        if self._devhandle is None:
            raise XMas_TreeNotFound()

    def __del__(self):
        '''Destructor, release the device'''
        if self._devhandle:
            self._devhandle.close()

    def get_product_string(self):
        '''Returns the device product string'''
        return self._devhandle.get_product_string()

    def get_serial_number_string(self):
        '''Returns the device serial number string'''
        return self._devhandle.get_serial_number_string()

    def get_firmware_version(self):
        '''Returns a tuple with XMas_Tree firmware version in format (major, minor)'''
        if self._firmware_major_version is None:
            status, major, minor = self._raw_sendreceive([0xf0])[:3]
            if status == XMas_Tree_PROTO_OK_STATUS:
                self._firmware_major_version, self._firmware_minor_version = (major, minor)
            else:
                # early devices will not recognize it, figure it out from serial
                self._firmware_major_version = 1
                self._firmware_minor_version = 2 if 'YK2' in self.get_serial_number_string() else 255 if 'YKD2' in self.get_serial_number_string() else 0
        return self._firmware_major_version, self._firmware_minor_version

    def _raw_sendreceive(self, packetarray):
        '''Internal method, submit a command and read the response from XMas_Tree'''
        # build the packet according to the report packet size
        # note: no buffer optimization was made for the sake of simplicity
        if _usingHid:
            packetarray = [0x00] + packetarray + [0x00] * (XMas_Tree_USB_PACKET_SIZE - len(packetarray))
            self._devhandle.write(packetarray)
            recvpacket = self._devhandle.read(max_length=XMas_Tree_USB_PACKET_SIZE + 1, timeout_ms=XMas_Tree_USB_TIMEOUT)
        else:
            packetarray = packetarray + [0x00] * (XMas_Tree_USB_PACKET_SIZE - len(packetarray))
            packet = struct.pack('<%dB' % XMas_Tree_USB_PACKET_SIZE, *packetarray)
            self._devhandle.write(packet)
            recvpacket = self._devhandle.read(length=XMas_Tree_USB_PACKET_SIZE + 1, timeout_ms=XMas_Tree_USB_TIMEOUT)
        # if not None return the bytes we actually need
        if recvpacket is None or len(recvpacket) < XMas_Tree_USB_PACKET_PAYLOAD_SIZE:
            return [0xff] * XMas_Tree_USB_PACKET_PAYLOAD_SIZE
        return recvpacket[:XMas_Tree_USB_PACKET_PAYLOAD_SIZE] if _usingHid else struct.unpack('<%iB' % XMas_Tree_USB_PACKET_PAYLOAD_SIZE, recvpacket[:XMas_Tree_USB_PACKET_PAYLOAD_SIZE])

    def led1_on(self):
        return self._raw_sendreceive([0x40])[0] == XMas_Tree_PROTO_OK_STATUS

    def led1_off(self):
        return self._raw_sendreceive([0x41])[0] == XMas_Tree_PROTO_OK_STATUS

    def led2_on(self):
        return self._raw_sendreceive([0x50])[0] == XMas_Tree_PROTO_OK_STATUS

    def led2_off(self):
        return self._raw_sendreceive([0x51])[0] == XMas_Tree_PROTO_OK_STATUS

    def get_height(self):
        recvbytes = self._raw_sendreceive([0x60])
        print ((recvbytes[1] << 8) + recvbytes[0])
        return


def main():
    '''Just in case all you need is a command line tool'''
    from argparse import ArgumentParser

    # argument parser description
    parser = ArgumentParser(description='NavVis XMas_Tree command line tool.')
    parser.add_argument('-s', '--serial', default=None, help='specify the serial number string of the XMas_Tree to be listed or managed')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('-l', '--list', help='list XMas_Tree devices', action='store_true')
    group.add_argument('-n', '--on', type=int, nargs='*', help='turn the cam on')
    group.add_argument('-f', '--off', type=int, nargs='*', help='turn the cam off')

    args = parser.parse_args()

    # say hello
    print('%s XMas_Tree family devices \n-------------------------------\n%s' %
          (args.list and 'listing' or 'managing',
           args.serial is None and ' ' or ' with serial number %s' % (args.serial)))
    try:
        XMas_Tree_found = False
        for device in hid_enumerate(0, 0):
            if device['vendor_id'] == XMas_Tree_USB_VID and device['product_id'] in XMas_Tree_USB_PID_LIST + XMas_Tree_USB_PID_BL_LIST:
                if args.serial is None or args.serial == device['serial_number']:
                    XMas_Tree_found = True
                    print('  %s REV: %s  Serial number: %s' %
                          (device['product_string'], device['release_number'], device['serial_number']))
                    print('    system device path %s, VID 0x%.4x, PID 0x%.4x' % (device['path'].decode(), device['vendor_id'], device['product_id']))
                    if device['product_id'] in XMas_Tree_USB_PID_BL_LIST:
                        print('    control functions are not available, the device is working in bootloader mode')
                    else:
                        XT = None
                        try:
                            XT = XMas_Tree()  # path=device['path'])
                            print('    Firmware v%i.%i' % (XT.get_firmware_version()))
                        except IOError:
                            if args.list:
                                print('    warning: could not communicate, the device may be in use or')
                                print('    your user do not have access rights to do so, in the latter')
                                print('    case you may work around the by using sudo, for example:')
                                print('      sudo python pXMas_Tree.py -l')
                                print('    if you are using the binary version:')
                                print('      sudo pXMas_Tree -l')
                            else:
                                raise
                        if XT:
                            cmds = []
                            if args.list:
                                # list requested, attempting to get all port states
                                t = XT.get_allports_state()
                                # print('    downstream running power states, port 1 to %i: %s' %
                                #      (XMas_Tree.get_downstream_port_count(), ', '.join([XMas_Tree_PORT_STATE_DICT[s] for s in t])))
                                # XMas_Tree firmware below v2 does not support persistence functions
                                if XT.get_firmware_version()[0] > 1:
                                    t = XT.get_allports_persistent_state()
                                    # if t[0] != XMas_Tree_PORT_STATE_ERROR:
                                    # print('    downstream startup/persistent power states, port 1 to %i: %s' %
                                    #      (XMas_Tree.get_downstream_port_count(), ', '.join([XMas_Tree_PORT_STATE_DICT[s] for s in t])))
                            if args.on is not None:
                                XT.led1_on()
                            if args.off is not None:
                                XT.led1_off()

        if not XMas_Tree_found:
            print('no XMas_Tree devices found')
    except (ValueError, IOError, OSError) as e:
        print('communication error, exception details:')
        print('  error "%s"' % e.message)
        sys.exit(1)


if __name__ == '__main__':
    main()
