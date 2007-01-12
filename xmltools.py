from xml.dom import Node, minidom

XMLNS_INTERFACE = "http://zero-install.sourceforge.net/2004/injector/interface"

def data(node):
	"""Return all the text directly inside this DOM Node."""
	return ''.join([text.nodeValue for text in node.childNodes
			if text.nodeType == Node.TEXT_NODE])

def set_data(elem, value):
	"""Replace all children of 'elem' with a single text node containing 'value'"""
	for node in elem.childNodes:
		elem.removeChild(node)
	if value:
		text = elem.ownerDocument.createTextNode(value)
		elem.appendChild(text)

def indent_of(x):
	"""If x's previous sibling is whitespace, return its length. Otherwise, return 0."""
	indent = x.previousSibling
	if indent and indent.nodeType == Node.TEXT_NODE:
		spaces = indent.nodeValue.split('\n')[-1]
		if spaces.strip() == '':
			return len(spaces)
	return 0

def insert_before(new, next):
	indent_depth = indent_of(next)
	new_parent = next.parentNode

	prev = next.previousSibling
	if prev and prev.nodeType == Node.TEXT_NODE:
		next = prev

	new_parent.insertBefore(new, next)
	if indent_depth:
		text = new_parent.ownerDocument.createTextNode('\n' + (' ' * indent_depth))
		new_parent.insertBefore(text, new)

def insert_element(new, parent, before = []):
	indent = indent_of(parent) + 2	# Default indent
	last_element = None
	for x in parent.childNodes:
		if x.nodeType == Node.ELEMENT_NODE:
			indent = indent or indent_of(x)
			if x.localName in before:
				parent.insertBefore(new, last_element.nextSibling)
				break
			last_element = x
	else:
		if last_element:
			parent.insertBefore(new, last_element.nextSibling)
		else:
			had_children = bool(list(child_elements(parent)))
			parent.appendChild(new)
			if not had_children:
				final_indent = '\n' + (' ' * indent_of(parent))
				parent.appendChild(parent.ownerDocument.createTextNode(final_indent))
	if indent:
		indent_text = parent.ownerDocument.createTextNode('\n' + (' ' * indent))
		parent.insertBefore(indent_text, new)

def create_element(parent, name, uri = XMLNS_INTERFACE, before = []):
	"""Create a new child element with the given name.
	Add it as far down the list of children as possible, but before
	any element in the 'before' set. Indent it sensibly."""
	new = parent.ownerDocument.createElementNS(uri, name)
	insert_element(new, parent, before)
	return new

def remove_element(elem):
	"""Remove 'elem' and any whitespace before it."""
	parent = elem.parentNode
	prev = elem.previousSibling
	if prev and prev.nodeType == Node.TEXT_NODE:
		if prev.nodeValue.strip() == '':
			parent.removeChild(prev)
	parent.removeChild(elem)

def format_para(para):
	"""Turn new-lines into spaces, removing any blank lines."""
	lines = [l.strip() for l in para.split('\n')]
	return ' '.join(filter(None, lines))

def attrs_match(elem, attrs):
	for x in attrs:
		if not elem.hasAttribute(x): return False
		if elem.getAttribute(x) != attrs[x]: return False
	return True

def child_elements(parent):
	"""Yield all direct child elements."""
	for x in parent.childNodes:
		if x.nodeType == Node.ELEMENT_NODE:
			yield x

def children(parent, localName, uri = XMLNS_INTERFACE, attrs = {}):
	"""Yield all direct child elements with this name and attributes."""
	for x in parent.childNodes:
		if x.nodeType == Node.ELEMENT_NODE:
			if x.nodeName == localName and x.namespaceURI == uri and attrs_match(x, attrs):
				yield x

def singleton_text(parent, localName, uri = XMLNS_INTERFACE):
	"""Return the text of the first child element with this name, or None
	if there aren't any."""
	elements = list(children(parent, localName, uri))
	if elements:
		return data(elements[0])

def set_or_remove(element, attr_name, value):
	if value:
		element.setAttribute(attr_name, value)
	elif element.hasAttribute(attr_name):
		element.removeAttribute(attr_name)
