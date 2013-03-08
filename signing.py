from zeroinstall import SafeException
from zeroinstall.injector import gpg
import tempfile, os, base64, shutil, signal
import subprocess
from rox import tasks, g

umask = os.umask(0)
os.umask(umask)

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

def _io_callback(src, cond, blocker):
	blocker.trigger()
	return False

def get_secret_keys():
	child = subprocess.Popen(('gpg', '--list-secret-keys', '--with-colons', '--with-fingerprint'),
				 stdout = subprocess.PIPE)
	stdout, _ = child.communicate()
	status = child.wait()
	if status:
		raise Exception("GPG failed with exit code %d" % status)
	# First, collect fingerprints for available secret keys
	keys = []
	for line in stdout.split('\n'):
		line = line.split(':')
		if line[0] == 'fpr':
			keys.append([line[9], None])
	# When listing secret keys, the identity shown may not be the primary identity as selected by
	# the user or shown when verifying a signature. However, the primary identity can be obtained
	# by listing the accompanying public key.
	loaded_keys = gpg.load_keys([k[0] for k in keys])
	for key in keys:
		key[1] = "{name} - {id}".format(
				name = loaded_keys[key[0]].name,
				id = key[0][-8:])
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
	error = "ERROR: No valid signatures found!\n"
	for sig in sigs:
		error += "\nGot: %s" % sig
	error += '\n\nTo edit it anyway, remove the signature using a text editor.'
	raise Exception(error)

def write_tmp(path, data):
	"""Create a temporary file in the same directory as 'path' and write data to it."""
	fd, tmp = tempfile.mkstemp(prefix = 'tmp-', dir = os.path.dirname(path))
	stream = os.fdopen(fd, 'w')
	stream.write(data)
	stream.close()
	os.chmod(tmp, 0644 &~umask)
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
		sigtmp = tmp + '.sig'

		agent_info = os.environ.get("GPG_AGENT_INFO", None)
		child = subprocess.Popen(('gpg', '--default-key', key,
					  '--detach-sign', '--status-fd', str(w),
					  '--command-fd', '0',
					  '--no-tty',
					  '--output', sigtmp,
					  '--use-agent',
					  '-q',
					  tmp),
					 preexec_fn = setup_child,
					 stdin = subprocess.PIPE)

		os.close(w)
		w = None
		while True:
			input = tasks.InputBlocker(r)
			yield input
			msg = os.read(r, 100)
			if not msg: break
			buffer.add(msg)
			for command in buffer:
				if command.startswith('[GNUPG:] NEED_PASSPHRASE ') and not agent_info:
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

	encoded = base64.encodestring(file(sigtmp).read())
	os.unlink(sigtmp)
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
		return None
	key_stream = file(key_file, 'w')
	stream = os.popen("gpg -a --export '%s'" % fingerprint)
	shutil.copyfileobj(stream, key_stream)
	stream.close()
	key_stream.close()
	return key_file
