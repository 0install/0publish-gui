from xml.dom import Node, minidom

import rox, os, pango, sys
from rox import g
import gtk.glade

import signing

RESPONSE_SAVE = 1
RESPONSE_SAVE_AND_TEST = 0

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

XMLNS_INTERFACE = "http://zero-install.sourceforge.net/2004/injector/interface"

emptyFeed = """<?xml version='1.0'?>
<interface xmlns="%s"/>
""" % (XMLNS_INTERFACE)

def data(node):
	"""Return all the text directly inside this DOM Node."""
	return ''.join([text.nodeValue for text in node.childNodes
			if text.nodeType == Node.TEXT_NODE])

def format_para(para):
	lines = [l.strip() for l in para.split('\n')]
	return ' '.join(filter(None, lines))

def children(parent, localName, uri = XMLNS_INTERFACE):
	for x in parent.childNodes:
		if x.nodeType == Node.ELEMENT_NODE:
			if x.nodeName == localName and x.namespaceURI == uri:
				yield x

def singleton_text(parent, localName, uri = XMLNS_INTERFACE):
	elements = list(children(parent, localName, uri))
	if elements:
		return data(elements[0])

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
				self.save()
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

		description = singleton_text(root, 'description')
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
	
	def save(self):
		pass
