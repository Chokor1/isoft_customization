# Copyright (c) 2026, Isoft and Contributors
# MIT License. See license.txt

"""Role-gated document rename endpoint.

Replaces a bare `@frappe.whitelist()` that had been added directly onto
`frappe.model.rename_doc.rename_doc` in the framework. That decorator exposed the
raw helper to every authenticated session, including its `ignore_permissions` and
`force` arguments -- a caller could pass `ignore_permissions=1` and rename any
document in the system regardless of their own permissions.

This wrapper keeps the capability but fixes the two problems: the dangerous
arguments are never taken from the caller, and the caller must hold write
permission on the specific document.
"""

from __future__ import unicode_literals

import frappe
from frappe import _

#: Roles allowed to rename documents through this endpoint.
ALLOWED_ROLES = ("System Manager", "Administrator")


@frappe.whitelist()
def rename_document(doctype, old, new, merge=False):
	"""Rename `old` to `new` for `doctype`, honouring the caller's permissions."""
	if not (doctype and old and new):
		frappe.throw(_("Doctype, current name and new name are all required."))

	if not set(ALLOWED_ROLES) & set(frappe.get_roles()):
		frappe.throw(
			_("You are not permitted to rename documents."), frappe.PermissionError
		)

	# Permission is checked against this specific document, not the doctype alone.
	frappe.get_doc(doctype, old).check_permission("write")

	if not frappe.get_meta(doctype).allow_rename:
		frappe.throw(_("{0} cannot be renamed.").format(_(doctype)))

	from frappe.model.rename_doc import rename_doc

	# ignore_permissions and force are deliberately not exposed to the caller.
	return rename_doc(
		doctype=doctype,
		old=old,
		new=new,
		merge=frappe.utils.cint(merge),
		ignore_permissions=False,
	)
