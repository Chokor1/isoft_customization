"""Ship the Multi-buy form scripts: browsers cache doctype JS by DocType.modified."""
import frappe


def execute():
	for dt in ("Quotation", "Sales Order", "Delivery Note", "Sales Invoice", "Pricing Rule"):
		frappe.db.sql("update tabDocType set modified = now() where name = %s", dt)
	frappe.clear_cache()
