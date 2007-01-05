from zeroinstall import SafeException
from zeroinstall.injector import gpg
import tempfile, os, base64, sys, shutil, signal
import subprocess
from rox import tasks, g
import gobject

class LineBuffer:
	def __init__(self):
		self.data = ''
	
	def add(self, new):
		assert new
		self.data += new
	
	def __iter__(self):
		while '\n' in self.data:
			command, self.data = self.data.split('\n', 1)
			yield command

# (version in ROX-Lib < 2.0.4 is buggy; missing IO_HUP)
class InputBlocker(tasks.Blocker):
	"""Triggers when os.read(stream) would not block."""
	_tag = None
	_stream = None
	def __init__(self, stream):
		tasks.Blocker.__init__(self)
		self._stream = stream
	
	def add_task(self, task):
		tasks.Blocker.add_task(self, task)
		if self._tag is None:
			self._tag = gobject.io_add_watch(self._stream, gobject.IO_IN | gobject.IO_HUP,
				lambda src, cond: self.trigger())
	
	def remove_task(self, task):
		tasks.Blocker.remove_task(self, task)
		if not self._rox_lib_tasks:
			gobject.source_remove(self._tag)
			self._tag = None

def get_secret_keys():
	child = subprocess.Popen(('gpg', '--list-secret-keys', '--with-colons', '--with-fingerprint'),
				 stdout = subprocess.PIPE)
	stdout, _ = child.communicate()
	status = child.wait()
	if status:
		raise Exception("GPG failed with exit code %d" % status)
	keys = []
	for line in stdout.split('\n'):
		line = line.split(':')
		if line[0] == 'sec':
			keys.append([None, line[9]])
		elif line[0] == 'fpr':
			keys[-1][0] = line[9]
	return keys

def check_signature(path):
	data = file(path).read()
	xml_comment = data.rfind('\n<!-- Base64 Signature')
	if xml_comment >= 0:
		data_stream, sigs = gpg.check_stream(file(path))
		sign_fn = sign_xml
		data = data[:xml_comment + 1]
		data_stream.close()
	elif data.startswith('-----BEGIN'):
		data_stream, sigs = gpg.check_stream(file(path))
		sign_fn = sign_xml		# Don't support saving as plain
		data = data_stream.read()
	else:
		return data, sign_unsigned, None
	for sig in sigs:
		if isinstance(sig, gpg.ValidSig):
			return data, sign_fn, sig.fingerprint
	print "ERROR: No valid signatures found!"
	for sig in sigs:
		print "Got:", sig
	ok = raw_input('Ignore and load anyway? (y/N) ').lower()
	if ok and 'yes'.startswith(ok):
		import __main__
		__main__.force_save = True
		return data, sign_unsigned, None
	sys.exit(1)

def write_tmp(path, data):
	"""Create a temporary file in the same directory as 'path' and write data to it."""
	fd, tmp = tempfile.mkstemp(prefix = 'tmp-', dir = os.path.dirname(path))
	stream = os.fdopen(fd, 'w')
	stream.write(data)
	stream.close()
	return tmp

def run_gpg(default_key, *arguments):
	arguments = list(arguments)
	if default_key is not None:
		arguments = ['--default-key', default_key] + arguments
	arguments.insert(0, 'gpg')
	if os.spawnvp(os.P_WAIT, 'gpg', arguments):
		raise SafeException("Command '%s' failed" % arguments)

def sign_unsigned(path, data, key, callback):
	os.rename(write_tmp(path, data), path)
	if callback: callback()

def sign_xml(path, data, key, callback):
	import main
	wTree = g.glade.XML(main.gladefile, 'get_passphrase')
	box = wTree.get_widget('get_passphrase')
	box.set_default_response(g.RESPONSE_OK)
	entry = wTree.get_widget('passphrase')

	buffer = LineBuffer()

	killed = False
	error = False
	tmp = None
	r, w = os.pipe()
	try:
		def setup_child():
			os.close(r)

		tmp = write_tmp(path, data)

		child = subprocess.Popen(('gpg', '--default-key', key,
					  '--detach-sign', '--status-fd', str(w),
					  '--command-fd', '0',
					  '-q',
					  tmp),
					 preexec_fn = setup_child,
					 stdin = subprocess.PIPE)

		os.close(w)
		w = None
		while True:
			input = InputBlocker(r)
			yield input
			msg = os.read(r, 100)
			if not msg: break
			buffer.add(msg)
			for command in buffer:
				if command.startswith('[GNUPG:] NEED_PASSPHRASE '):
					entry.set_text('')
					box.present()
					resp = box.run()
					box.hide()
					if resp == g.RESPONSE_OK:
						child.stdin.write(entry.get_text() + '\n')
						child.stdin.flush()
					else:
						os.kill(child.pid, signal.SIGTERM)
						killed = True

		status = child.wait()
		if status:
			raise Exception("GPG failed with exit code %d" % status)
	except:
		# No generator finally blocks in Python 2.4...
		error = True

	if r is not None: os.close(r)
	if w is not None: os.close(w)
	if tmp is not None: os.unlink(tmp)

	if killed: return
	if error: raise

	tmp += '.sig'
	encoded = base64.encodestring(file(tmp).read())
	os.unlink(tmp)
	sig = "<!-- Base64 Signature\n" + encoded + "\n-->\n"
	os.rename(write_tmp(path, data + sig), path)

	if callback: callback()

def export_key(dir, fingerprint):
	assert fingerprint is not None
	# Convert fingerprint to key ID
	stream = os.popen('gpg --with-colons --list-keys %s' % fingerprint)
	try:
		keyID = None
		for line in stream:
			parts = line.split(':')
			if parts[0] == 'pub':
				if keyID:
					raise Exception('Two key IDs returned from GPG!')
				keyID = parts[4]
	finally:
		stream.close()
	key_file = os.path.join(dir, keyID + '.gpg')
	if os.path.isfile(key_file):
		return
	key_stream = file(key_file, 'w')
	stream = os.popen("gpg -a --export '%s'" % fingerprint)
	shutil.copyfileobj(stream, key_stream)
	stream.close()
	key_stream.close()
	print "Exported public key as '%s'" % key_file
