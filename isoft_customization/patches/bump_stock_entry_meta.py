"""Browsers cache the Stock Entry / Stock Entry Type form scripts by DocType.modified."""
from __future__ import unicode_literals

import frappe
from frappe.utils import now


def execute():
	for doctype in ("Stock Entry", "Stock Entry Type"):
		frappe.db.set_value("DocType", doctype, "modified", now(), update_modified=False)
		frappe.clear_cache(doctype=doctype)
