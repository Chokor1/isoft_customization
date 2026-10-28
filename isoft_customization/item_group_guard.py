"""Refuse an Item Group parent that would close a loop.

Frappe's NestedSet only rejects a group being its own parent. On dev.isoft.ao
"Acessórios" and "MALAS/MOCHILAS" were each other's parent (since January 2026),
and ERPNext's validate_item_tax_template walks parents in a `while` loop, so
every sales document with an item from those groups hung until gunicorn killed
the worker. This validate hook walks up from the chosen parent and throws when
it meets the group itself (or runs past a sane depth, which means an existing
loop elsewhere in the chain).
"""
from __future__ import unicode_literals

import frappe
from frappe import _

MAX_DEPTH = 200


def validate_parent(doc, method=None, *args, **kwargs):
	parent = doc.get("parent_item_group")
	if not parent:
		return
	if parent == doc.name:
		frappe.throw(_("Item Group {0} cannot be its own parent.").format(doc.name))
	chain = [parent]
	current = parent
	for _i in range(MAX_DEPTH):
		current = frappe.db.get_value("Item Group", current, "parent_item_group")
		if not current:
			return
		if current == doc.name:
			frappe.throw(_("Item Group {0} cannot be placed under {1}: {1} is already below it ({2}).").format(
				doc.name, parent, " > ".join(reversed(chain + [doc.name]))))
		chain.append(current)
	frappe.throw(_("The parents of Item Group {0} form a loop ({1}); fix that group first.").format(parent, " > ".join(chain[:6]) + " ..."))
