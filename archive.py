from xml.dom import Node, minidom
import re

import rox, os, sys, urlparse, tempfile, shutil, time, urllib
from rox import g, tasks
import gtk.glade

from zeroinstall.zerostore import unpack, manifest, NotStored

import signing
from xmltools import *
import main

dotted_ints = '[0-9]+(.[0-9]+)*'
version_regexp = '[^a-zA-Z0-9](%s)(-(pre|rc|post|)%s)*' % (dotted_ints, dotted_ints)

def get_combo_value(combo):
	i = combo.get_active()
	m = combo.get_model()
	return m[i][0]

watch = gtk.gdk.Cursor(gtk.gdk.WATCH)

def autopackage_get_details(package):
	size = None
	type = 'application/x-bzip-compressed-tar'
	for line in file(package):
		if line.startswith('export dataSize=') or line.startswith('export data_size='):
			size = os.path.getsize(package) - int(line.split('"', 2)[1])
		elif line.startswith('compression=') and 'lzma' in line:
			type = 'application/x-lzma-compressed-tar'
		if line.startswith('## END OF STUB'): break
	if size is None:
		raise Exception("Can't find payload in autopackage (missing 'dataSize')")
	return size, type

class AddArchiveBox:
	def __init__(self, feed_editor, local_archive = None):
		self.feed_editor = feed_editor
		self.tmpdir = None
		self.mime_type = self.start_offset = None

		widgets = gtk.glade.XML(main.gladefile, 'add_archive')

		tree = widgets.get_widget('extract_list')
		model = g.TreeStore(str)
		tree.set_model(model)
		selection = tree.get_selection()
		selection.set_mode(g.SELECTION_BROWSE)

		cell = g.CellRendererText()
		col = g.TreeViewColumn('Extract', cell)
		col.add_attribute(cell, 'text', 0)
		tree.append_column(col)

		dialog = widgets.get_widget('add_archive')

		mime_type = widgets.get_widget('mime_type')
		mime_type.set_active(0)

		def local_archive_changed(chooser):
			model.clear()
			path = chooser.get_filename()
			widgets.get_widget('subdirectory_frame').set_sensitive(False)
			self.destroy_tmp()
			if not path: return

			if mime_type.get_active() == 0:
				type = None
			else:
				type = mime_type.get_active_text()

			archive_url = widgets.get_widget('archive_url')
			url = archive_url.get_text()
			if not url:
				url = 'http://SITE/' + os.path.basename(path)
				archive_url.set_text(url)

			start_offset = 0
			if not type:
				if url.endswith('.package'):
					type = 'Autopackage'
				else:
					type = unpack.type_from_url(url)

			if type == 'Autopackage':
				# Autopackage isn't a real type. Examine the .package file
				# and find out what it really is.
				start_offset, type = autopackage_get_details(path)

			self.tmpdir = tempfile.mkdtemp('-0publish-gui')
			try:
				dialog.window.set_cursor(watch)
				gtk.gdk.flush()
				try:
					unpack.unpack_archive(url, file(path), self.tmpdir,
							      type = type, start_offset = start_offset)
				finally:
					dialog.window.set_cursor(None)
			except:
				chooser.unselect_filename(path)
				self.destroy_tmp()
				raise
			iter = model.append(None, ['Everything'])
			items = os.listdir(self.tmpdir)
			for f in items:
				model.append(iter, [f])
			tree.expand_all()
			# Choose a sensible default
			iter = model.get_iter_root()
			if len(items) == 1 and \
		           os.path.isdir(os.path.join(self.tmpdir, items[0])) and \
			   items[0] not in ('usr', 'opt', 'bin', 'etc', 'sbin', 'doc', 'var'):
				iter = model.iter_children(iter)
			selection.select_iter(iter)

			self.mime_type = type
			self.start_offset = start_offset
			widgets.get_widget('subdirectory_frame').set_sensitive(True)

		local_archive_button = widgets.get_widget('local_archive')
		local_archive_button.connect('selection-changed', local_archive_changed)
		widgets.get_widget('subdirectory_frame').set_sensitive(False)

		def download(button):
			url = widgets.get_widget('archive_url').get_text()
			if not url:
				raise Exception("Enter a URL to download from!")

			chooser = g.FileChooserDialog('Save archive as...', dialog, g.FILE_CHOOSER_ACTION_SAVE)
			chooser.set_current_name(os.path.basename(url))
			chooser.add_button(g.STOCK_CANCEL, g.RESPONSE_CANCEL)
			chooser.add_button(g.STOCK_SAVE, g.RESPONSE_OK)
			chooser.set_default_response(g.RESPONSE_OK)
			resp = chooser.run()
			filename = chooser.get_filename()
			chooser.destroy()
			if resp != g.RESPONSE_OK:
				return

			DownloadBox(url, filename, local_archive_button)

		widgets.get_widget('download').connect('clicked', download)

		def resp(dialog, r):
			if r == g.RESPONSE_OK:
				url = widgets.get_widget('archive_url').get_text()
				if urlparse.urlparse(url)[1] == '':
					raise Exception('Missing host name in URL "%s"' % url)
				if urlparse.urlparse(url)[2] == '':
					raise Exception('Missing resource part in URL "%s"' % url)
				local_archive = widgets.get_widget('local_archive').get_filename()
				if not local_archive:
					raise Exception('Please select a local file')
				if selection.iter_is_selected(model.get_iter_root()):
					root = self.tmpdir
					extract = None
				else:
					_, iter = selection.get_selected()
					extract = model[iter][0]
					root = os.path.join(self.tmpdir, extract)

				size = os.path.getsize(local_archive)
				if self.start_offset:
					size -= self.start_offset
				self.create_archive_element(url, self.mime_type, root, extract, size,
						    self.start_offset)
			self.destroy_tmp()
			dialog.destroy()

		dialog.connect('response', resp)

		if local_archive:
			local_archive_button.set_filename(local_archive)
			initial_url = 'http://SITE/' + os.path.basename(local_archive)
			widgets.get_widget('archive_url').set_text(initial_url)
	
	def destroy_tmp(self):
		if self.tmpdir:
			shutil.rmtree(self.tmpdir)
			self.tmpdir = None

	def create_archive_element(self, url, mime_type, root, extract, size, start_offset):
		alg = manifest.get_algorithm('sha1new')
		digest = alg.new_digest()
		for line in alg.generate_manifest(root):
			digest.update(line + '\n')
		id = alg.getID(digest)

		# Add it to the cache if missing
		# Helps with setting 'main' attribute later
		try:
			main.stores.lookup(id)
		except NotStored:
			main.stores.add_dir_to_cache(id, root)

		# Do we already have an implementation with this digest?
		impl_element = self.feed_editor.find_implementation(id)

		if impl_element is None:
			# No. Create a new implementation. Guess the details...

			leaf = url.split('/')[-1]
			version = None
			for m in re.finditer(version_regexp, leaf):
				match = m.group()[1:]
				if version is None or len(best) < len(match):
					version = match

			impl_element = create_element(self.feed_editor.doc.documentElement, 'implementation')
			impl_element.setAttribute('id', id)
			impl_element.setAttribute('released', time.strftime('%Y-%m-%d'))
			if version: impl_element.setAttribute('version', version)
			created_impl = True
		else:
			created_impl = False

		archive_element = create_element(impl_element, 'archive')
		archive_element.setAttribute('size', str(size))
		archive_element.setAttribute('href', url)
		if extract: archive_element.setAttribute('extract', extract)
		if mime_type: archive_element.setAttribute('type', mime_type)
		if start_offset: archive_element.setAttribute('start-offset', str(start_offset))

		self.feed_editor.update_version_model()

		if created_impl:
			self.feed_editor.edit_properties(element = impl_element)

class DownloadBox:
	def __init__(self, url, path, archive_button):
		widgets = gtk.glade.XML(main.gladefile, 'download')
		gtk.gdk.flush()

		output = file(path, 'w')

		dialog = widgets.get_widget('download')
		progress = widgets.get_widget('progress')
		
		cancelled = tasks.Blocker()
		def resp(box, resp):
			cancelled.trigger()
		dialog.connect('response', resp)

		def download():
			stream = None

			def cleanup():
				dialog.destroy()
				if output:
					output.close()
				if stream:
					stream.close()

			try:
				# (urllib2 is buggy; no fileno)
				stream = urllib.urlopen(url)
				size = float(stream.info().get('Content-Length', None))
				got = 0

				while True:
					yield signing.InputBlocker(stream), cancelled
					if cancelled.happened:
						raise Exception("Download cancelled at user's request")
					data = os.read(stream.fileno(), 1024)
					if not data: break
					output.write(data)
					got += len(data)

					if size:
						progress.set_fraction(got / size)
					else:
						progress.pulse()
			except:
				# No finally in python 2.4
				cleanup()
				raise
			else:
				cleanup()
				archive_button.set_filename(path)

		tasks.Task(download())
