"""Stock Reconciliation > Fetch Items from Warehouse, filtered by Brand and Item Group.

ERPNext's dialog only takes a warehouse and one item code. public/js/stock_reconciliation.js
replaces that dialog with one that also asks for a Brand and an Item Group (the group
includes its sub-groups) and calls get_items below.

Without a brand or group this is ERPNext's get_items unchanged. With one, the items are
narrowed BEFORE their stock balances are read, so a filtered fetch on a big warehouse
is faster than an unfiltered one, not slower.
"""
from __future__ import unicode_literals

import frappe
from frappe.utils import cint
from frappe.utils.nestedset import get_descendants_of

from erpnext.stock.doctype.stock_reconciliation import stock_reconciliation as core


@frappe.whitelist()
def get_items(
	warehouse,
	posting_date,
	posting_time,
	company,
	item_code=None,
	ignore_empty_stock=False,
	brand=None,
	item_group=None,
):
	if not (brand or item_group):
		return core.get_items(warehouse, posting_date, posting_time, company, item_code, ignore_empty_stock)

	allowed = matching_items(brand, item_group)

	if item_code:
		if item_code not in allowed:
			return []
		return core.get_items(warehouse, posting_date, posting_time, company, item_code, ignore_empty_stock)

	items = [d for d in core.get_items_for_stock_reco(warehouse, company) if d.item_code in allowed]
	if not items:
		return []

	# Same loop as erpnext's get_items, over the filtered items only.
	ignore_empty_stock = cint(ignore_empty_stock)
	itemwise_batch_data = core.get_itemwise_batch(warehouse, posting_date, company)
	res = []

	for d in items:
		if d.item_code in itemwise_batch_data:
			valuation_rate = core.get_stock_balance(
				d.item_code, d.warehouse, posting_date, posting_time, with_valuation_rate=True
			)[1]

			for row in itemwise_batch_data.get(d.item_code):
				if ignore_empty_stock and not row.qty:
					continue
				res.append(core.get_item_data(row, row.qty, valuation_rate))
		else:
			stock_bal = core.get_stock_balance(
				d.item_code,
				d.warehouse,
				posting_date,
				posting_time,
				with_valuation_rate=True,
				with_serial_no=cint(d.has_serial_no),
			)
			qty, valuation_rate = stock_bal[0], stock_bal[1]
			serial_no = stock_bal[2] if cint(d.has_serial_no) else ""

			if ignore_empty_stock and not qty:
				continue
			res.append(core.get_item_data(d, qty, valuation_rate, serial_no))

	return res


def matching_items(brand=None, item_group=None):
	"""Names of the items with this brand and in this item group or any group under it."""
	filters = {}
	if brand:
		filters["brand"] = brand
	if item_group:
		filters["item_group"] = ["in", [item_group] + get_descendants_of("Item Group", item_group)]
	return set(frappe.get_all("Item", filters=filters, pluck="name"))
