#!/usr/bin/env python2.4
import sys
from os.path import dirname, abspath
import unittest

sys.path.insert(0, '..')

import signing

class TestBuffer(unittest.TestCase):
	def testbuffer(self):
		buffer = signing.LineBuffer()
		assert list(buffer) == []

		buffer.add('Hello\n')
		assert list(buffer) == ['Hello']

		buffer.add('Hello')
		assert list(buffer) == []
		buffer.add(' World\nGoodbye\n')
		assert list(buffer) == ['Hello World', 'Goodbye']

		buffer.add(' World\nGoodbye')
		assert list(buffer) == [' World']
		buffer.add('\n')
		assert list(buffer) == ['Goodbye']
		assert list(buffer) == []
		assert list(buffer) == []
	
suite = unittest.makeSuite(TestBuffer)
if __name__ == '__main__':
	sys.argv.append('-v')
	unittest.main()
