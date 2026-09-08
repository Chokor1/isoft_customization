"""Force browsers to refetch the Purchase Invoice form script.

The desk caches each DocType's meta, including the merged form JS, in
localStorage keyed by tabDocType.modified. Adding a doctype_js entry for
Purchase Invoice changes the served script but not that timestamp, so without
this bump every browser keeps running the old bundle. Idempotent: bumping again
only costs one more meta fetch per browser.
"""
from __future__ import unicode_literals

import frappe
from frappe.utils import now


def execute():
	frappe.db.set_value("DocType", "Purchase Invoice", "modified", now(), update_modified=False)
	frappe.clear_cache(doctype="Purchase Invoice")
