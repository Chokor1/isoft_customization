"""Barcode UOM on scan in ERPNext's selling documents.

The Item Barcode table carries a UOM per barcode (posa_uom, a POS Awesome custom
field). POS Awesome uses it; ERPNext's Scan Barcode field did not: its lookup
returned only barcode and item_code, so the row always took the item's default
UOM and that UOM's price.

This wraps the whitelisted lookup to add `uom` when the scanned barcode has one.
Every other answer (serial no, batch no, unknown code, barcode without UOM) is
returned unchanged. The form side (public/js/barcode_uom_scan.js) puts the UOM on
the row, which makes ERPNext fetch that UOM's conversion factor and price.
"""
from __future__ import unicode_literals

import frappe
from erpnext.selling.page.point_of_sale.point_of_sale import (
	search_for_serial_or_batch_or_barcode_number as _erpnext_lookup,
)


@frappe.whitelist()
def search_for_serial_or_batch_or_barcode_number(search_value):
	result = _erpnext_lookup(search_value) or {}
	if result.get("barcode") and result.get("item_code") and frappe.get_meta("Item Barcode").has_field("posa_uom"):
		uom = frappe.db.get_value("Item Barcode",
			{"barcode": result["barcode"], "parent": result["item_code"]}, "posa_uom")
		if uom:
			result["uom"] = uom
	return result
