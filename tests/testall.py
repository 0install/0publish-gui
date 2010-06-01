#!/usr/bin/env python
import unittest, os, sys
try:
	import coverage
	coverage.erase()
	coverage.start()
except ImportError:
	coverage = None

my_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
os.chdir(my_dir)

sys.argv.append('-v')

suite_names = [f[:-3] for f in os.listdir(my_dir)
		if f.startswith('test') and f.endswith('.py')]
suite_names.remove('testall')
suite_names.sort()

alltests = unittest.TestSuite()

for name in suite_names:
	m = __import__(name, globals(), locals(), [])
	alltests.addTest(m.suite)

a = unittest.TextTestRunner(verbosity=2).run(alltests)

if coverage:
	coverage.stop()
else:
	print "Coverage module not found. Skipping coverage report."

print "\nResult", a
if not a.wasSuccessful():
	sys.exit(1)

if coverage:
	all_sources = []
	def incl(d):
		for x in os.listdir(d):
			if x.endswith('.py'):
				all_sources.append(os.path.join(d, x))
	incl('..')
	coverage.report(all_sources)
