"""Remove the leftovers of the old "Advance Tools" module.

The module (Barcode Generation Tool, Scrape Tool, Scrape Target, Scrape Tool Item,
the Market Price Comparison Report, the "Barcode Sticker" print format and its
workspace) once lived in the ERPNext fork; its files were deleted in the fork's
commit 4b2ff74 ("clear erpnext external customization") but the database records
stayed. Opening any of them now fails with KeyError: 'advance_tools' because no
installed app provides that module.

Only the metadata is removed. Frappe v13 keeps the tables when a DocType is
deleted, and every deleted record is kept as a Deleted Document, so the old
Scrape Tool data is still there if anyone needs it.
"""

import frappe
from frappe import scrub

MODULE = "Advance Tools"

# children before parents, so nothing points at a DocType that is already gone
DOCTYPES = ("Scrape Tool Item", "Scrape Tool", "Scrape Target", "Barcode Generation Tool")


def execute():
	if not frappe.db.exists("Module Def", MODULE) and not frappe.db.exists("DocType", {"module": MODULE}):
		return
	if scrub(MODULE) in (frappe.local.module_app or {}):
		# some installed app ships this module again: it is not a leftover
		return

	for name in DOCTYPES:
		if frappe.db.get_value("DocType", name, "module") == MODULE:
			frappe.delete_doc("DocType", name, force=True, ignore_permissions=True, ignore_missing=True)

	# anything else of the module, whatever was added on the site later
	for doctype in ("DocType", "Report", "Print Format", "Workspace", "Page", "Dashboard Chart", "Number Card"):
		if not frappe.db.table_exists(doctype) or not frappe.db.has_column(doctype, "module"):
			continue
		for name in frappe.get_all(doctype, filters={"module": MODULE}, pluck="name"):
			frappe.delete_doc(
				doctype, name, force=True, ignore_permissions=True, ignore_on_trash=True, ignore_missing=True
			)

	frappe.delete_doc(
		"Module Def", MODULE, force=True, ignore_permissions=True, ignore_on_trash=True, ignore_missing=True
	)
	frappe.clear_cache()
