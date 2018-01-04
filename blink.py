
from __future__ import unicode_literals
from __future__ import print_function
import sys
import struct
import XMas_Tree
import time


def main():
    XT = XMas_Tree.XMas_Tree()
    print ('%s ' % XT.get_product_string())

    XT.led2_off()
    XT.led1_on()
    time.sleep(1)
    XT.led2_on()
    XT.led1_off()
    time.sleep(1)
    print ('while loop')
    while 1:
        for i in range(10):
            XT.led1_on()
            XT.led2_off()
            time.sleep(0.3 + 0.01 * i)
            XT.led1_off()
            XT.led2_on()
            time.sleep(0.3 - (0.01 * i))
            print ('%i' % i)


if __name__ == '__main__':
    main()
