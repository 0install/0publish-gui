#!/usr/bin/env python
import sys
from os.path import dirname, abspath
import unittest
from xml.dom.minidom import parseString

sys.path.insert(0, '..')

import xmltools

doc_a = """<?xml version="1.0" ?>
<root>
  <first/>
  <second/>
</root>"""

doc_b = """<?xml version="1.0" ?>
<root>
  <first/>
  <new/>
  <second/>
</root>"""

doc_c = """<?xml version="1.0" ?>
<root>
  <first/>
  <second/>
  <new/>
</root>"""

doc_d = """<?xml version="1.0" ?>
<root>
  <new/>
  <first/>
  <second/>
</root>"""

class TestXML(unittest.TestCase):
	def setUp(self):
		self.doc = parseString(doc_a)
		self.new = self.doc.createElement('new')

	def testBefore(self):
		first = self.doc.getElementsByTagName('first')[0]
		xmltools.insert_before(self.new, first)
		self.assertXML(doc_d)

		xmltools.remove_element(self.new)
		self.assertXML(doc_a)

		second = self.doc.getElementsByTagName('second')[0]
		xmltools.insert_before(self.new, second)
		self.assertXML(doc_b)

		xmltools.remove_element(self.new)
		self.assertXML(doc_a)

	def testAfter(self):
		first = self.doc.getElementsByTagName('first')[0]
		xmltools.insert_after(self.new, first)
		self.assertXML(doc_b)

		xmltools.remove_element(self.new)
		self.assertXML(doc_a)

		second = self.doc.getElementsByTagName('second')[0]
		xmltools.insert_after(self.new, second)
		self.assertXML(doc_c)

		xmltools.remove_element(self.new)
		self.assertXML(doc_a)

	def assertXML(self, expected_xml):
		# Some Python versions don't include a newline after the decl
		actual_xml = '<?xml version="1.0" ?>\n' + self.doc.documentElement.toxml()
		if expected_xml != actual_xml:
			raise AssertionError("Expected:\n%s\nGot:\n%s\n" % (expected_xml, actual_xml))
	
suite = unittest.makeSuite(TestXML)
if __name__ == '__main__':
	sys.argv.append('-v')
	unittest.main()
