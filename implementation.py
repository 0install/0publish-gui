from xml.dom import Node, minidom

import rox, os, pango, sys, textwrap, traceback, subprocess, time, urlparse
from rox import g, tasks, loading
import gtk.glade

import main
from xmltools import *

from zeroinstall.injector import model
from zeroinstall.zerostore import unpack, NotStored

class ImplementationProperties:
	def __init__(self, feed_editor, element = None, is_group = False):
		self.feed_editor = feed_editor
		self.element = element

		widgets = gtk.glade.XML(main.gladefile, 'version')

		#attributes = g.ListStore(str, str)
		#attr_view = widgets.get_widget('attributes')
		#attr_view.set_model(attributes)

		#attr_view.append_column(g.TreeViewColumn('Name'))
		#attr_view.append_column(g.TreeViewColumn('Value'))

		inherit_arch = widgets.get_widget('inherit_arch')
		def shade_os_cpu():
			s = not inherit_arch.get_active()
			widgets.get_widget('cpu').set_sensitive(s)
			widgets.get_widget('os').set_sensitive(s)
			if s and widgets.get_widget('cpu').get_active_text() == 'src':
				widgets.get_widget('source_frame').show()
			else:
				widgets.get_widget('source_frame').hide()
				command = widgets.get_widget('compile_command')
				if command.get_text() == '':
					command.set_text('"$SRCDIR/configure" --prefix="$DISTDIR" && make install')
		inherit_arch.connect('toggled', lambda cb: shade_os_cpu())
		widgets.get_widget('cpu').connect('changed', lambda cb: shade_os_cpu())

		main_menu = widgets.get_widget('main_binary')

		if element:
			if element.localName == 'group':
				is_group = True
				id = None
			else:
				id = element.getAttribute('id')

			version = element.getAttribute('version') + \
				  (element.getAttribute('version-modifier') or '')
			widgets.get_widget('version_number').set_text(version)
			widgets.get_widget('released').set_text(element.getAttribute('released'))

			widgets.get_widget('compile_command').set_text(element.getAttributeNS(XMLNS_COMPILE, 'command'))
			widgets.get_widget('compile_binary_main').set_text(element.getAttributeNS(XMLNS_COMPILE, 'binary-main'))

			main_binary = element.getAttribute('main')

			stability_menu = widgets.get_widget('stability')
			stability = element.getAttribute('stability')
			if stability:
				i = 0
				for row in stability_menu.get_model():
					if row[0].lower() == stability:
						stability_menu.set_active(i)
						break
					i += 1
			else:
				stability_menu.set_active(0)

			main.combo_set_text(widgets.get_widget('license'), element.getAttribute('license'))
			arch = element.getAttribute('arch')
			if arch:
				arch_os, arch_cpu = arch.split('-')
				main.combo_set_text(widgets.get_widget('os'), arch_os)
				main.combo_set_text(widgets.get_widget('cpu'), arch_cpu)
				inherit_arch.set_active(False)
			else:
				widgets.get_widget('os').set_active(0)
				widgets.get_widget('cpu').set_active(0)

			def ok():
				self.update_impl(element, widgets)
		else:
			released = widgets.get_widget('released')

			id = '.'
			if is_group:
				widgets.get_widget('version_number').set_text('')
				released.set_text('')
			else:
				widgets.get_widget('version_number').set_text('1.0')
				released.set_text(time.strftime('%Y-%m-%d'))

			widgets.get_widget('cpu').set_active(0)
			widgets.get_widget('os').set_active(0)
			widgets.get_widget('stability').set_active(0)
			main_binary = None

			def ok():
				if is_group:
					element_name = 'group'
				else:
					element_name = 'implementation'
				element = create_element(self.feed_editor.doc.documentElement, element_name)
				if not is_group:
					element.setAttribute('id', '.')
				try:
					self.update_impl(element, widgets)
				except:
					remove_element(element)
					raise

		shade_os_cpu()

		self.is_group = is_group

		id_label = widgets.get_widget('id_label')

		if is_group:
			id_label.set_text('(group)')
		elif id:
			id_label.set_text(id)
			if id.startswith('.') or id.startswith('/'):
				id_label.set_sensitive(True)
		else:
			id_label.set_text('-')

		def resp(dialog, r):
			if r == g.RESPONSE_OK:
				ok()
				self.feed_editor.update_version_model()
			dialog.destroy()

		if is_group and element:
			# Find a cached implementation for getting main
			for x in child_elements(element):
				if x.localName == 'implementation' and x.namespaceURI == XMLNS_INTERFACE:
					id = x.getAttribute('id')
					try:
						if id and (id.startswith('.') or id.startswith('/') or main.stores.lookup(id)):
							break
					except NotStored, ex:
						pass
		if id:
			# Find possible main settings, if possible
			if id.startswith('/') or id.startswith('.'):
				cached_impl = os.path.abspath(os.path.join(os.path.dirname(feed_editor.pathname), id))
			else:
				try:
					cached_impl = main.stores.lookup(id)
				except NotStored, ex:
					cached_impl = None
			if cached_impl:
				i = 0
				for (dirpath, dirnames, filenames) in os.walk(cached_impl):
					for file in filenames:
						info = os.stat(os.path.join(dirpath, file))
						if info.st_mode & 0111:
							relbasedir = dirpath[len(cached_impl) + 1:]
							new = os.path.join(relbasedir, file)
							main_menu.append_text(new)
							i += 1
		main.combo_set_text(main_menu, main_binary)

		dialog = widgets.get_widget('version')
		dialog.connect('response', resp)

	def update_impl(self, element, widgets):
		version = widgets.get_widget('version_number').get_text()
		released = widgets.get_widget('released').get_text()
		inherit_arch = widgets.get_widget('inherit_arch')

		def get_combo(name):
			widget = widgets.get_widget(name)
			return widget.get_active_text()

		cpu = get_combo('cpu')
		os = get_combo('os')
		license = get_combo('license')

		widget = widgets.get_widget('stability')
		if widget.get_active() == 0:
			stability = None
		else:
			stability = get_combo('stability').lower()

		if inherit_arch.get_active():
			arch = None
		else:
			arch = os + '-' + cpu

		main = widgets.get_widget('main_binary').get_active_text()

		old_id = element.getAttribute('id')
		if old_id.startswith('/') or old_id.startswith('.'):
			# Local paths are editable
			new_id = widgets.get_widget('id_label').get_text()
			if new_id.startswith('.') or new_id.startswith('/'):
				element.setAttribute('id', new_id)
			else:
				raise Exception('Local IDs must start with "." or "/"')

		version_modifier = None
		if version:
			model.parse_version(version)
			if '-' in version:
				version, version_modifier = version.split('-', 1)
				version_modifier = '-' + version_modifier

		for name, value in [('version', version),
			            ('version-modifier', version_modifier),
			            ('arch', arch),
			            ('main', main),
			            ('released', released),
			            ('license', license),
			            ('stability', stability)]:
			if value:
				element.setAttribute(name, value)
			elif element.hasAttribute(name):
				element.removeAttribute(name)

		# Source packages
		if widgets.get_widget('source_frame').flags() & gtk.VISIBLE:
			compile_command = widgets.get_widget('compile_command').get_text()
			compile_binary_main = widgets.get_widget('compile_binary_main').get_text()
			self.feed_editor.doc.documentElement.setAttribute('xmlns:compile', XMLNS_COMPILE)
		else:
			compile_command = compile_binary_main = None

		for name, value in [('command', compile_command),
				    ('binary-main', compile_binary_main)]:
			if value:
				element.setAttributeNS(XMLNS_COMPILE, 'compile:' + name, value)
			elif element.hasAttributeNS(XMLNS_COMPILE, name):
				element.removeAttributeNS(XMLNS_COMPILE, name)
