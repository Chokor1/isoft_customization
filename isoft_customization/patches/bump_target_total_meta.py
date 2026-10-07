"""Force browsers to refetch the Quotation / Delivery Note / Sales Invoice form scripts.

The desk caches each DocType's merged form JS in localStorage keyed by
tabDocType.modified. Adding the Target Total Assistant doctype_js entries
changes the served script but not that timestamp, so without this bump every
browser keeps running the old bundle. Idempotent.
"""
from __future__ import unicode_literals

import frappe
from frappe.utils import now


def execute():
	for doctype in ("Quotation", "Delivery Note", "Sales Invoice"):
		frappe.db.set_value("DocType", doctype, "modified", now(), update_modified=False)
		frappe.clear_cache(doctype=doctype)
