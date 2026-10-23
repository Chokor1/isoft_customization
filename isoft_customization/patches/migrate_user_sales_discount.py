"""Move the site-level "User Sales Discount" rows into Sales Discount Limit and
retire the Server Script that enforced them on Sales Invoice.

Idempotent: users that already have a Sales Discount Limit are left alone; the
old custom DocType and its rows stay in place. Settings are switched on with
"No limit (100%)" for users without a record, which is what the old script did
(no row = no check), and Sales Invoice is the only checked document type, so
behaviour on existing sites does not change until someone edits the settings.
"""
from __future__ import unicode_literals

import frappe
from frappe.utils import cint, flt


def execute():
	frappe.reload_doc("isoft_customization", "doctype", "sales_discount_limit_line")
	frappe.reload_doc("isoft_customization", "doctype", "sales_discount_limit")
	frappe.reload_doc("isoft_customization", "doctype", "sales_discount_role_limit")
	frappe.reload_doc("isoft_customization", "doctype", "sales_discount_limit_settings")

	if not frappe.db.table_exists("User Sales Discount"):
		return

	moved = 0
	for row in frappe.db.sql("select user, max_discount_stock, max_discount_service, enabled from `tabUser Sales Discount`", as_dict=1):
		if not row.user or not frappe.db.exists("User", row.user) or frappe.db.exists("Sales Discount Limit", row.user):
			continue
		frappe.get_doc({
			"doctype": "Sales Discount Limit", "user": row.user, "enabled": cint(row.enabled),
			"limits": [{"document_type": "Sales Invoice", "max_discount_stock": flt(row.max_discount_stock), "max_discount_service": flt(row.max_discount_service)}],
		}).insert(ignore_permissions=True)
		moved += 1

	settings = frappe.get_doc("Sales Discount Limit Settings")
	if not cint(settings.enabled) and moved:
		settings.enabled = 1
		settings.users_without_limit = "No limit (100%)"
		settings.limit_user = "Document owner"
		settings.check_quotation = 0
		settings.check_sales_order = 0
		settings.check_delivery_note = 0
		settings.check_sales_invoice = 1
		settings.save(ignore_permissions=True)

	for name in frappe.get_all("Server Script", filters={"script": ["like", "%User Sales Discount%"], "disabled": 0}, pluck="name"):
		frappe.db.set_value("Server Script", name, "disabled", 1)
	frappe.clear_cache()
