from xml.dom import Node, minidom

import rox, os, pango, sys, textwrap, traceback, subprocess
from rox import g, tasks
import gtk.glade

import signing
from xmltools import *

RESPONSE_SAVE = 0
RESPONSE_SAVE_AND_TEST = 1

gladefile = os.path.join(rox.app_dir, '0publish-gui.glade')

def choose_feed():
	tree = gtk.glade.XML(gladefile, 'no_file_specified')
	box = tree.get_widget('no_file_specified')
	tree.get_widget('new_button').grab_focus()
	resp = box.run()
	box.destroy()
	if resp == 0:
		chooser = g.FileChooserDialog('Choose a location for the new feed',
					      None, g.FILE_CHOOSER_ACTION_SAVE)
		chooser.set_current_name('MyProg.xml')
		chooser.add_button(g.STOCK_CANCEL, g.RESPONSE_CANCEL)
		chooser.add_button(g.STOCK_NEW, g.RESPONSE_OK)
	elif resp == 1:
		chooser = g.FileChooserDialog('Choose the feed to edit',
					      None, g.FILE_CHOOSER_ACTION_OPEN)
		chooser.add_button(g.STOCK_CANCEL, g.RESPONSE_CANCEL)
		chooser.add_button(g.STOCK_OPEN, g.RESPONSE_OK)
	else:
		sys.exit(1)
	chooser.set_default_response(g.RESPONSE_OK)
	if chooser.run() != g.RESPONSE_OK:
		sys.exit(1)
	path = chooser.get_filename()
	chooser.destroy()
	return FeedEditor(path)

emptyFeed = """<?xml version='1.0'?>
<interface xmlns="%s">
  <name>Name</name>
</interface>
""" % (XMLNS_INTERFACE)

class FeedEditor:
	def __init__(self, pathname):
		self.pathname = pathname

		self.wTree = gtk.glade.XML(gladefile, 'main')
		self.window = self.wTree.get_widget('main')
		self.window.connect('destroy', rox.toplevel_unref)

		help = gtk.glade.XML(gladefile, 'main_help')
		help_box = help.get_widget('main_help')
		help_box.set_default_size(g.gdk.screen_width() / 4,
				      g.gdk.screen_height() / 4)
		help_box.connect('delete-event', lambda box, ev: True)
		help_box.connect('response', lambda box, resp: box.hide())

		def resp(box, resp):
			if resp == g.RESPONSE_HELP:
				help_box.present()
			elif resp == RESPONSE_SAVE_AND_TEST:
				self.save(self.test)
			elif resp == RESPONSE_SAVE:
				self.save()
			else:
				box.destroy()
		self.window.connect('response', resp)
		rox.toplevel_ref()
	
		keys = signing.get_secret_keys()
		key_menu = self.wTree.get_widget('feed_key')
		key_model = g.ListStore(str, str)
		key_menu.set_model(key_model)
		cell = g.CellRendererText()
		cell.set_property('ellipsize', pango.ELLIPSIZE_MIDDLE)
		key_menu.pack_start(cell)
		key_menu.add_attribute(cell, 'text', 1)

		key_model.append((None, '(unsigned)'))
		for k in keys:
			key_model.append(k)

		if os.path.exists(self.pathname):
			data, _, self.key = signing.check_signature(self.pathname)
			self.doc = minidom.parseString(data)
			self.update_fields()
		else:
			self.doc = minidom.parseString(emptyFeed)
			self.key = None
			key_menu.set_active(0)

		impl_model = g.TreeStore(str)
		impl_tree = self.wTree.get_widget('impl_tree')
		impl_tree.set_model(impl_model)

		#self.attr_model = g.ListStore(str, str)
		#attributes = self.wTree.get_widget('attributes')
		#attributes.set_model(self.attr_model)
		#text = g.CellRendererText()
		#for title in ['Attribute', 'Value']:
		#	column = g.TreeViewColumn(title, text)
		#	attributes.append_column(column)
	
	def update_fields(self):
		root = self.doc.documentElement

		def set(name):
			value = singleton_text(root, name)
			if value:
				self.wTree.get_widget('feed_' + name).set_text(value)
		set('name')
		set('summary')
		set('homepage')

		for icon in children(root, 'icon'):
			if icon.getAttribute('type') == 'image/png':
				href = icon.getAttribute('href')
				self.wTree.get_widget('feed_icon').set_text(href)
				break

		description = singleton_text(root, 'description') or ''
		paragraphs = [format_para(p) for p in description.split('\n\n')]
		buffer = self.wTree.get_widget('feed_description').get_buffer()
		buffer.delete(buffer.get_start_iter(), buffer.get_end_iter())
		buffer.insert_at_cursor('\n'.join(paragraphs))

		key_menu = self.wTree.get_widget('feed_key')
		model = key_menu.get_model()
		if self.key:
			i = 0
			for line in model:
				if line[0] == self.key:
					break
				i += 1
			else:
				model.append((self.key, 'Missing key (%s)' % self.key))
			key_menu.set_active(i)
		else:
			key_menu.set_active(0)

	def test(self):
		child = os.fork()
		if child == 0:
			try:
				try:
					# We are the child
					# Spawn a grandchild and exit
					subprocess.Popen(['0launch', '--gui', self.pathname])
					os._exit(0)
				except:
					traceback.print_exc()
			finally:
				os._exit(1)
		pid, status = os.waitpid(child, 0)
		assert pid == child
		if status:
			raise Exception('Failed to run 0launch - status code %d' % status)
	
	def update_doc(self):
		root = self.doc.documentElement
		def update(name, required = False, attrs = {}, value_attr = None):
			widget = self.wTree.get_widget('feed_' + name)
			if isinstance(widget, g.TextView):
				buffer = widget.get_buffer()
				text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter())
				paras = ['\n'.join(textwrap.wrap(para, 80)) for para in text.split('\n') if para.strip()]
				value = '\n' + '\n\n'.join(paras)
			else:
				value = widget.get_text()
			elems = list(children(root, name, attrs = attrs))
			if value:
				if elems:
					elem = elems[0]
				else:
					elem = create_element(root, name,
							        before = ['group', 'implementation', 'requires'])
					for x in attrs:
						elem.setAttribute(x, attrs[x])
				if value_attr:
					elem.setAttribute(value_attr, value)
					set_data(elem, None)
				else:
					set_data(elem, value)
			else:
				if required:
					raise Exception('Missing required field "%s"' % name)
				for e in elems:
					remove_element(e)
			
		update('name', True)
		update('summary', True)
		update('description', True)
		update('homepage')
		update('icon', attrs = {'type': 'image/png'}, value_attr = 'href')

		uri = self.wTree.get_widget('feed_url').get_text()
		if uri:
			root.setAttribute('uri', uri)
		elif root.hasAttribute('uri'):
			root.removeAttribute('uri')

		key_menu = self.wTree.get_widget('feed_key')
		key_model = key_menu.get_model()
		self.key = key_model[key_menu.get_active()][0]
	
	def save(self, callback = None):
		self.update_doc()
		if self.key:
			sign = signing.sign_xml
		else:
			sign = signing.sign_unsigned
		data = self.doc.toxml() + '\n'

		gen = sign(self.pathname, data, self.key, callback)
		# May require interaction to get the pass-phrase, so run in the background...
		if gen:
			tasks.Task(gen)
