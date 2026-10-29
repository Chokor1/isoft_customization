"""Force browsers to refetch the Pricing Rule form script.

The desk caches each DocType's meta, including the merged form JS, in
localStorage keyed by tabDocType.modified. The conflict dialog in
public/js/pricing_rule.js changed (item-group tree overlaps, no Remove for a
wider group) but that timestamp did not, so without this bump browsers keep the
old dialog. Idempotent: bumping again only costs one more meta fetch per browser.
"""
from __future__ import unicode_literals

import frappe
from frappe.utils import now


def execute():
	frappe.db.set_value("DocType", "Pricing Rule", "modified", now(), update_modified=False)
	frappe.clear_cache(doctype="Pricing Rule")
