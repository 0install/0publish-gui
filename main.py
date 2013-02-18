from xml.dom import Node, minidom

from StringIO import StringIO

import rox, os, pango, sys, textwrap, traceback, subprocess, shutil
from rox import g, tasks, loading
import gtk.glade

import signing
import archive
from implementation import ImplementationProperties
from requires import Requires
from xmltools import *

from zeroinstall.injector import model, qdom
from zeroinstall.zerostore import Stores

RESPONSE_SAVE = 0
RESPONSE_SAVE_AND_TEST = 1

xml_header = """<?xml version="1.0" ?>
"""
xml_stylesheet_header = """<?xml-stylesheet type='text/xsl' href='interface.xsl'?>
"""

gladefile = os.path.join(rox.app_dir, '0publish-gui.glade')

# Zero Install implementation cache
stores = Stores()

stylesheet_src = os.path.join(os.path.dirname(__file__), 'interface.xsl')

def available_in_path(prog):
	for d in os.environ['PATH'].split(':'):
		path = os.path.join(d, prog)
		if os.path.isfile(path):
			return True
	return False

def get_terminal_emulator():
	terminal_emulators = ['x-terminal-emulator', 'xterm', 'konsole']
	for xterm in terminal_emulators:
		if available_in_path(xterm):
			return xterm
	return 'xterm'		# Hope

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

def combo_set_text(combo, text):
	if combo.get_active_text() or text:
		model =  combo.get_model()
		i = 0
		for row in model:
			if row[0] == text:
				combo.set_active(i)
				return
			i += 1
		combo.append_text(text)
		combo.set_active(i)
	else:
		return

def list_attrs(element):
	attrs = element.attributes
	names = []
	for x in range(attrs.length):
		attr = attrs.item(x)

		if attr.name in ['id', 'version-modifier']: continue
		if element.localName == 'implementation' and attr.name == 'version': continue

		if attr.name in ('stability', 'arch'):
			names.append(attr.value)
		else:
			names.append(attr.name)
	if names:
		return ' (%s)' % ', '.join(names)
	else:
		return ''

emptyFeed = """<?xml version='1.0'?>
<interface xmlns="%s">
  <name>Name</name>
</interface>
""" % (XMLNS_INTERFACE)

element_target = ('INTERNAL:FeedEditor/Element', gtk.TARGET_SAME_WIDGET, 0)

class FeedEditor(loading.XDSLoader):
	def __init__(self, pathname):
		loading.XDSLoader.__init__(self, None)

		self.pathname = pathname

		self.wTree = gtk.glade.XML(gladefile, 'main')
		self.window = self.wTree.get_widget('main')
		self.window.connect('destroy', rox.toplevel_unref)
		self.xds_proxy_for(self.window)

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
	
		key_menu = self.wTree.get_widget('feed_key')
		key_model = g.ListStore(str, str)
		key_menu.set_model(key_model)
		cell = g.CellRendererText()

		if gtk.pygtk_version >= (2, 8, 0):
			# Crashes with pygtk 2.6.1
			cell.set_property('ellipsize', pango.ELLIPSIZE_MIDDLE)

		key_menu.pack_start(cell)
		key_menu.add_attribute(cell, 'text', 1)

		self.update_key_model()

		self.impl_model = g.TreeStore(str, object)
		impl_tree = self.wTree.get_widget('impl_tree')
		impl_tree.set_model(self.impl_model)
		text = g.CellRendererText()
		column = g.TreeViewColumn('', text)
		column.add_attribute(text, 'text', 0)
		impl_tree.append_column(column)

		impl_tree.enable_model_drag_source(gtk.gdk.BUTTON1_MASK, [element_target], gtk.gdk.ACTION_MOVE)
		impl_tree.enable_model_drag_dest([element_target], gtk.gdk.ACTION_MOVE)

		sel = impl_tree.get_selection()
		sel.set_mode(g.SELECTION_BROWSE)

		if os.path.exists(self.pathname):
			data, _, self.key = signing.check_signature(self.pathname)
			self.doc = minidom.parseString(data)
			self.update_fields()

			# Default to showing the versions tab
			self.wTree.get_widget('notebook').next_page()
		else:
			default_name = os.path.basename(self.pathname)
			if default_name.endswith('.xml'):
				default_name = default_name[:-4]
			self.doc = minidom.parseString(emptyFeed)
			self.key = None
			key_menu.set_active(0)

			self.update_fields()
			self.wTree.get_widget('feed_name').set_text(default_name)

		root = self.impl_model.get_iter_root()
		if root:
			sel.select_iter(root)

		self.wTree.get_widget('generate_key').connect('clicked', lambda b: self.generate_key())

		self.wTree.get_widget('add_implementation').connect('clicked', lambda b: self.add_version())
		self.wTree.get_widget('add_archive').connect('clicked', lambda b: self.add_archive())
		self.wTree.get_widget('add_requires').connect('clicked', lambda b: self.add_requires())
		self.wTree.get_widget('add_group').connect('clicked', lambda b: self.add_group())
		self.wTree.get_widget('edit_properties').connect('clicked', lambda b: self.edit_properties())
		self.wTree.get_widget('remove').connect('clicked', lambda b: self.remove_version())
		impl_tree.connect('row-activated', lambda tv, path, col: self.edit_properties(path))
		impl_tree.connect('drag-data-received', self.tree_drag_data_received)
	
	def update_key_model(self):
		key_menu = self.wTree.get_widget('feed_key')
		key_model = key_menu.get_model()
		keys = signing.get_secret_keys()
		key_model.clear()
		key_model.append((None, '(unsigned)'))
		for k in keys:
			key_model.append(k)

	def generate_key(self):
		for x in ['xterm', 'konsole']:
			if available_in_path(x):
				child = subprocess.Popen([x, '-e', 'gpg', '--gen-key'], stderr = subprocess.PIPE)
				break
		else:
			child = subprocess.Popen(['gnome-terminal', '-e', 'gpg --gen-key'], stderr = subprocess.PIPE)

		def get_keygen_out():
			errors = ''
			while True:
				yield signing.InputBlocker(child.stderr)
				data = os.read(child.stderr.fileno(), 100)
				if not data:
					break
				errors += data
			self.update_key_model()
			if errors:
				rox.alert('Errors from terminal: %s' % errors)

		tasks.Task(get_keygen_out())

	def tree_drag_data_received(self, treeview, context, x, y, selection, info, time):
		if not selection: return
		drop_info = treeview.get_dest_row_at_pos(x, y)
		if drop_info:
			model = treeview.get_model()
			path, position = drop_info

			src = self.get_selected()
			dest = model[path][1]

			def is_ancestor_or_self(a, b):
				while b:
					if b is a: return True
					b = b.parentNode
				return False

			if is_ancestor_or_self(src, dest):
				# Can't move an element into itself!
				return

			if position in (gtk.TREE_VIEW_DROP_BEFORE, gtk.TREE_VIEW_DROP_AFTER):
				new_parent = dest.parentNode
			else:
				new_parent = dest

			if src.namespaceURI != XMLNS_INTERFACE: return
			if new_parent.namespaceURI != XMLNS_INTERFACE: return

			if new_parent.localName == 'group':
				if src.localName not in ('implementation', 'group', 'requires'):
					return
			elif new_parent.localName == 'interface':
				if src.localName not in ('implementation', 'group'):
					return
			elif new_parent.localName == 'implementation':
				if src.localName not in ['requires']:
					return
			else:
				return

			remove_element(src)

			if position == gtk.TREE_VIEW_DROP_BEFORE:
				insert_before(src, dest)
			elif position == gtk.TREE_VIEW_DROP_AFTER:
				next = dest.nextSibling
				while next and not next.nodeType == Node.ELEMENT_NODE:
					next = next.nextSibling
				if next:
					insert_before(src, next)
				else:
					insert_element(src, new_parent)
			else:
				for next in child_elements(new_parent):
					insert_before(src, next)
					break
				else:
					insert_element(src, new_parent)
			self.update_version_model()

	def add_version(self):
		ImplementationProperties(self)

	def add_group(self):
		ImplementationProperties(self, is_group = True)

	def add_requires(self):
		elem = self.get_selected()
		if elem.namespaceURI == XMLNS_INTERFACE:
			if elem.localName not in ('group', 'implementation'):
				elem = elem.parentNode
			if elem.localName in ('group', 'implementation'):
				Requires(self, parent = elem)
				return
		rox.alert('Select a group or implementation!')

	def edit_properties(self, path = None, element = None):
		assert not (path and element)

		if element:
			pass
		elif path is None:
			element = self.get_selected()
		else:
			element = self.impl_model[path][1]

		if element.namespaceURI != XMLNS_INTERFACE:
			rox.alert("Sorry, I don't known how to edit %s elements!" % element.namespaceURI)

		if element.localName in ('group', 'implementation'):
			ImplementationProperties(self, element)
		elif element.localName == 'requires':
			Requires(self, parent = element.parentNode, element = element)
		else:
			rox.alert("Sorry, I don't known how to edit %s elements!" % element.localName)
	
	def update_fields(self):
		root = self.doc.documentElement

		def set(name):
			value = singleton_text(root, name)
			if value:
				self.wTree.get_widget('feed_' + name).set_text(value)
		set('name')
		set('summary')
		set('homepage')

		needs_terminal = len(list(children(root, 'needs-terminal'))) > 0
		self.wTree.get_widget('feed_needs_terminal').set_active(needs_terminal)

		category_widget = self.wTree.get_widget('feed_category')
		category = singleton_text(root, 'category')
		if category:
			combo_set_text(category_widget, category)
		else:
			category_widget.set_active(0)

		uri = root.getAttribute('uri')
		if uri:
			self.wTree.get_widget('feed_url').set_text(uri)

		for feed_for in children(root, 'feed-for'):
			self.wTree.get_widget('feed_feed_for').set_text(feed_for.getAttribute('interface'))

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

		self.update_version_model()
	
	def add_archives(self, impl_element, iter):
		for child in child_elements(impl_element):
			if child.namespaceURI != XMLNS_INTERFACE: continue
			if child.localName == 'archive':
				self.impl_model.append(iter, ['Archive ' + child.getAttribute('href'), child])
			elif child.localName == 'requires':
				req_iface = child.getAttribute('interface')
				self.impl_model.append(iter, ['Impl requires %s' % req_iface, child])
			else:
				self.impl_model.append(iter, ['<%s>' % child.localName, child])
	
	def update_version_model(self):
		impl_tree = self.wTree.get_widget('impl_tree')

		# Remember which ones are open
		expanded_elements = set()
		impl_tree.map_expanded_rows(lambda tv, path: expanded_elements.add(self.impl_model[path][1]))

		initial_build = not self.impl_model.get_iter_root()

		self.impl_model.clear()

		def add_impls(elem, iter, attrs):
			"""Add all groups, implementations and requirements in elem"""

			for x in child_elements(elem):
				if x.namespaceURI != XMLNS_INTERFACE: continue

				if x.localName == 'requires':
					req_iface = x.getAttribute('interface')
					new = self.impl_model.append(iter, ['Group requires %s' % req_iface, x])

				if x.localName not in ('implementation', 'group'): continue

				new_attrs = attrs.copy()
				attributes = x.attributes
				for i in range(attributes.length):
					a = attributes.item(i)
					new_attrs[str(a.name)] = a.value

				if x.localName == 'implementation':
					version = new_attrs.get('version', '(missing version number)') + \
						  (new_attrs.get('version-modifier') or '')
					new = self.impl_model.append(iter, ['Version %s%s' % (version, list_attrs(x)), x])
					self.add_archives(x, new)
				elif x.localName == 'group':
					new = self.impl_model.append(iter, ['Group%s' % list_attrs(x), x])
					if initial_build:
						expanded_elements.add(x)
					add_impls(x, new, new_attrs)
					
		add_impls(self.doc.documentElement, None, attrs = {})

		def may_expand(model, path, iter):
			if model[iter][1] in expanded_elements:
				impl_tree.expand_row(path, False)
		self.impl_model.foreach(may_expand)

	def test(self, args = []):
		child = os.fork()
		if child == 0:
			try:
				try:
					# We are the child
					# Spawn a grandchild and exit
					command = ['0launch', '--gui'] + args + [self.pathname]
					if self.wTree.get_widget('feed_needs_terminal').get_active():
						command = [get_terminal_emulator(), '-e'] + command
					subprocess.Popen(command)
					os._exit(0)
				except:
					traceback.print_exc()
			finally:
				os._exit(1)
		pid, status = os.waitpid(child, 0)
		assert pid == child
		if status:
			raise Exception('Failed to run 0launch - status code %d' % status)
	
	def test_compile(self, args = []):
		child = os.fork()
		if child == 0:
			try:
				try:
					# We are the child
					# Spawn a grandchild and exit
					subprocess.Popen(['0launch',
						'http://0install.net/2006/interfaces/0compile.xml', 'gui'] +
						args + [self.pathname])
					os._exit(0)
				except:
					traceback.print_exc()
			finally:
				os._exit(1)
		pid, status = os.waitpid(child, 0)
		assert pid == child
		if status:
			raise Exception('Failed to run 0compile - status code %d' % status)
	
	def update_doc(self):
		root = self.doc.documentElement
		def update(name, required = False, attrs = {}, value_attr = None):
			widget = self.wTree.get_widget('feed_' + name.replace('-', '_'))
			if isinstance(widget, g.TextView):
				buffer = widget.get_buffer()
				text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter())
				paras = ['\n'.join(textwrap.wrap(para, 80)) for para in text.split('\n') if para.strip()]
				value = '\n' + '\n\n'.join(paras)
			elif isinstance(widget, g.ComboBox):
				if widget.get_active() == 0:
					value = None
				else:
					value = widget.get_active_text()
			elif isinstance(widget, g.ToggleButton):
				value = widget.get_active()
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
					# Set attribute
					elem.setAttribute(value_attr, value)
					set_data(elem, None)
				elif isinstance(widget, g.ToggleButton):
					pass
				else:
					# Set content
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
		update('category')
		update('feed-for', value_attr = 'interface')
		update('needs-terminal')
		update('icon', attrs = {'type': 'image/png'}, value_attr = 'href')

		uri = self.wTree.get_widget('feed_url').get_text()
		if uri:
			root.setAttribute('uri', uri)
		elif root.hasAttribute('uri'):
			root.removeAttribute('uri')

		key_menu = self.wTree.get_widget('feed_key')
		key_model = key_menu.get_model()
		self.key = key_model[key_menu.get_active()][0]
	
	def export_stylesheet_and_key(self):
		dir = os.path.dirname(os.path.abspath(self.pathname))
		stylesheet = os.path.join(dir, 'interface.xsl')
		if not os.path.exists(stylesheet):
			shutil.copyfile(stylesheet_src, stylesheet)
			rox.info("I have saved a stylesheet as '%s'. You should upload "
				"this to your web-server in the same directory as the feed file. "
				"This allows browsers to display the feed nicely." % stylesheet)

		if os.path.abspath(self.pathname).endswith('/feed.xml'):
			# Probably the feed's URL is the directory, so we'll get the key from the parent.
			dir = os.path.dirname(dir)

		exported =  signing.export_key(dir, self.key)
		if exported:
			rox.info("I have exported your public key as '%s'. You should upload "
				"this to your web-server in the same directory as the feed file. "
				"This allows people to check the signature on your feed." % exported)
	
	def save(self, callback = None):
		data = xml_header
		self.update_doc()
		if self.key:
			sign = signing.sign_xml
			self.export_stylesheet_and_key()
			data += xml_stylesheet_header
		else:
			sign = signing.sign_unsigned
		data += self.doc.documentElement.toxml() + '\n'

		gen = sign(self.pathname, data, self.key, callback)
		# May require interaction to get the pass-phrase, so run in the background...
		if gen:
			tasks.Task(gen)

	def add_archive(self):
		archive.AddArchiveBox(self)
	
	def xds_load_from_file(self, path):
		archive.AddArchiveBox(self, local_archive = path)
	
	def remove_version(self, path = None):
		elem = self.get_selected()
		remove_element(elem)
		self.update_version_model()
	
	def get_selected(self):
		tree = self.wTree.get_widget('impl_tree')
		sel = tree.get_selection()
		model, iter = sel.get_selected()
		if not iter:
			raise Exception('Select something first!')
		return model[iter][1]

	def find_implementation(self, id):
		def find_impl(parent):
			for x in child_elements(parent):
				if x.namespaceURI != XMLNS_INTERFACE: continue
				if x.localName == 'group':
					sub = find_impl(x)
					if sub: return sub
				elif x.localName == 'implementation':
					if x.getAttribute('id') == id:
						return x
		return find_impl(self.doc.documentElement)

	def list_versions(self):
		"""Return a list of (version, element) pairs, one for each <implementation>."""
		versions = []

		def add_versions(parent, version):
			for x in child_elements(parent):
				if x.namespaceURI != XMLNS_INTERFACE: continue
				if x.hasAttribute('version'): version = x.getAttribute('version')
				if x.localName == 'group':
					add_versions(x, version)
				elif x.localName == 'implementation':
					versions.append((model.parse_version(version), x))

		add_versions(self.doc.documentElement, version = None)

		return versions

	def get_as_feed(self):
		self.update_doc()
		xml = self.doc.documentElement.toxml(encoding = 'utf-8')
		return model.ZeroInstallFeed(qdom.parse(StringIO(xml)), local_path = os.path.abspath(self.pathname))
