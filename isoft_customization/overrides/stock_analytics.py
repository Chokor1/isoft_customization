"""Stock Analytics: carry the opening balance into the first periods of the range.

Backport of erpnext commit 008f2a6b6 ("fix(stock): carry the opening balance into
stock analytics periods", develop, 2026-10-16). Delete this module and its hooks once
the installed ERPNext includes it -- apply() already stands down when the erpnext
module defines OPENING_KEY.

The bug: get_stock_ledger_entries() fetches every entry up to to_date, ignoring
from_date, and get_periodic_data() builds the running balance from all of them. But
get_data() started each row at 0, so the balance from before from_date was computed
and thrown away: every period before an item's first in-range movement showed 0
(item 45518 on O-INDEX: 2026 = 0 with a 2026-only range, 100 with 2025-2026).

get_periodic_data() and get_data() below are copies of the installed ERPNext 13.49.12
functions with only the three upstream changes, each marked "backport 008f2a6b6".
Reports are discovered by folder and v13 has no override hook for them, so apply()
assigns these onto the erpnext module. execute() looks get_data up as a module global
at call time, so it -- and stock_barcode's wrapper around it -- picks the patch up.
apply() runs from before_request and before_job (hooks.py), which cover web report
runs and prepared reports; the call from __init__ covers console and bench execute.
"""
from frappe import scrub
from frappe.utils import getdate

from erpnext.stock.report.stock_analytics.stock_analytics import (
	fill_intermediate_periods,
	get_period,
	get_period_date_ranges,
)
from erpnext.stock.report.stock_balance.stock_balance import (
	get_item_details,
	get_items,
	get_stock_ledger_entries,
)

# backport 008f2a6b6 (1/3)
OPENING_KEY = "_opening"

MODULE = "erpnext.stock.report.stock_analytics.stock_analytics"


def get_periodic_data(entry, filters):
	"""Structured as:
	Item 1
	        - Balance (updated and carried forward):
	                        - Warehouse A : bal_qty/value
	                        - Warehouse B : bal_qty/value
	        - Jun 2021 (sum of warehouse quantities used in report)
	                        - Warehouse A : bal_qty/value
	                        - Warehouse B : bal_qty/value
	        - Jul 2021 (sum of warehouse quantities used in report)
	                        - Warehouse A : bal_qty/value
	                        - Warehouse B : bal_qty/value
	Item 2
	        - Balance (updated and carried forward):
	                        - Warehouse A : bal_qty/value
	                        - Warehouse B : bal_qty/value
	        - Jun 2021 (sum of warehouse quantities used in report)
	                        - Warehouse A : bal_qty/value
	                        - Warehouse B : bal_qty/value
	        - Jul 2021 (sum of warehouse quantities used in report)
	                        - Warehouse A : bal_qty/value
	                        - Warehouse B : bal_qty/value
	"""

	expected_ranges = get_period_date_ranges(filters)
	expected_periods = []
	for _start_date, end_date in expected_ranges:
		expected_periods.append(get_period(end_date, filters))

	# backport 008f2a6b6 (2/3)
	range_start = getdate(expected_ranges[0][0]) if expected_ranges else None

	periodic_data = {}
	for d in entry:
		period = get_period(d.posting_date, filters)
		bal_qty = 0

		fill_intermediate_periods(periodic_data, d.item_code, period, expected_periods)

		# if period against item does not exist yet, instantiate it
		# insert existing balance dict against period, and add/subtract to it
		if periodic_data.get(d.item_code) and not periodic_data.get(d.item_code).get(period):
			previous_balance = periodic_data[d.item_code]["balance"].copy()
			periodic_data[d.item_code][period] = previous_balance

		if d.voucher_type == "Stock Reconciliation" and not d.batch_no:
			if periodic_data.get(d.item_code) and periodic_data.get(d.item_code).get("balance").get(
				d.warehouse
			):
				bal_qty = periodic_data[d.item_code]["balance"][d.warehouse]

			qty_diff = d.qty_after_transaction - bal_qty
		else:
			qty_diff = d.actual_qty

		if filters["value_quantity"] == "Quantity":
			value = qty_diff
		else:
			value = d.stock_value_difference

		# period-warehouse wise balance
		periodic_data.setdefault(d.item_code, {}).setdefault("balance", {}).setdefault(d.warehouse, 0.0)
		periodic_data.setdefault(d.item_code, {}).setdefault(period, {}).setdefault(d.warehouse, 0.0)

		periodic_data[d.item_code]["balance"][d.warehouse] += value
		periodic_data[d.item_code][period][d.warehouse] = periodic_data[d.item_code]["balance"][
			d.warehouse
		]

		# backport 008f2a6b6 (2/3)
		if range_start and getdate(d.posting_date) < range_start:
			periodic_data[d.item_code][OPENING_KEY] = periodic_data[d.item_code]["balance"].copy()

	return periodic_data


def get_data(filters):
	data = []
	items = get_items(filters)
	sle = get_stock_ledger_entries(filters, items)
	item_details = get_item_details(items, sle, filters)
	periodic_data = get_periodic_data(sle, filters)
	ranges = get_period_date_ranges(filters)

	today = getdate()

	for dummy, item_data in item_details.items():
		row = {
			"name": item_data.name,
			"item_name": item_data.item_name,
			"item_group": item_data.item_group,
			"uom": item_data.stock_uom,
			"brand": item_data.brand,
		}
		# backport 008f2a6b6 (3/3)
		previous_period_value = sum(periodic_data.get(item_data.name, {}).get(OPENING_KEY, {}).values())
		for start_date, end_date in ranges:
			period = get_period(end_date, filters)
			period_data = periodic_data.get(item_data.name, {}).get(period)
			if period_data:
				row[scrub(period)] = previous_period_value = sum(period_data.values())
			else:
				row[scrub(period)] = previous_period_value if today >= start_date else None

		data.append(row)

	return data


def apply(*args, **kwargs):
	"""Point ERPNext's Stock Analytics at the functions above. Idempotent and cheap.

	Does nothing once ERPNext ships the fix itself (the module defines OPENING_KEY).
	Takes *args/**kwargs because before_job passes method/kwargs/transaction_type.
	"""
	import importlib

	module = importlib.import_module(MODULE)
	if hasattr(module, "OPENING_KEY"):
		return False
	if module.get_data is not get_data:
		module.get_periodic_data = get_periodic_data
		module.get_data = get_data
	return True
