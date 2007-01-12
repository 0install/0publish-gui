import rox, os
import gtk.glade

import main
from xmltools import *

from zeroinstall.zerostore import NotStored
from zeroinstall.injector import model
from zeroinstall.injector.policy import Policy

def get_combo_value(combo):
	i = combo.get_active()
	m = combo.get_model()
	return m[i][0]

class Requires:
	def __init__(self, feed_editor, parent, element = None):
		self.feed_editor = feed_editor
		self.element = element

		self.widgets = gtk.glade.XML(main.gladefile, 'requires')

		uri = self.widgets.get_widget('requires_uri')
		stream = os.popen('0launch --list')
		self.known_ifaces = [line.strip() for line in stream if not line.startswith('/')]
		self.known_ifaces.sort()
		stream.close()

		for x in self.known_ifaces:
			uri.append_text(x)

		uri.connect('changed', self.update_uri)
	
	def update_uri(self, combo):
		env_insert = self.widgets.get_widget('env_insert')
		env_insert.get_model().clear()

		uri = combo.get_active_text()
		if uri not in self.known_ifaces: return

		policy = Policy(uri)
		policy.network_use = model.network_offline
		policy.freshness = 0
		impls = policy.get_ranked_implementations(policy.get_interface(uri))

		for impl in impls:
			if impl.id.startswith('/'):
				cached_impl = impl.id
			else:
				try:
					cached_impl = main.stores.lookup(impl.id)
				except NotStored, ex:
					cached_impl = None
			if cached_impl:
				for (dirpath, dirnames, filenames) in os.walk(cached_impl):
					for d in dirnames[:]:
						if d in ('.svn', 'CVS'):
							dirnames.remove(d)
					new = dirpath[len(cached_impl) + 1:]
					env_insert.append_text(new)
				break
