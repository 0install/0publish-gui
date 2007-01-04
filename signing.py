from zeroinstall import SafeException
from zeroinstall.injector import gpg
import tempfile, os, base64, sys, shutil
import subprocess

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
		sign_fn = sign_plain
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

def sign_unsigned(path, data, key):
	os.rename(write_tmp(path, data), path)

def sign_plain(path, data, key):
	tmp = write_tmp(path, data)
	try:
		run_gpg(key, '--clearsign', tmp)
	finally:
		os.unlink(tmp)
	os.rename(tmp + '.asc', path)

def sign_xml(path, data, key):
	tmp = write_tmp(path, data)
	try:
		run_gpg(key, '--detach-sign', tmp)
	finally:
		os.unlink(tmp)
	tmp += '.sig'
	encoded = base64.encodestring(file(tmp).read())
	os.unlink(tmp)
	sig = "<!-- Base64 Signature\n" + encoded + "\n-->\n"
	os.rename(write_tmp(path, data + sig), path)

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
