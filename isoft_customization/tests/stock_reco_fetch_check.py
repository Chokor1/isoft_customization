"""Fetch Items from Warehouse with Brand / Item Group filters (stock_reco_fetch.py). Read-only.

The filtered fetch must return exactly ERPNext's unfiltered rows for the matching items:
same rows, quantities, valuation rates, batches and serial nos.

Run from sites/: ../env/bin/python ../apps/isoft_customization/isoft_customization/tests/stock_reco_fetch_check.py dev.isoft.ao ["<warehouse>"]
"""
import sys
import time

import frappe
from frappe.utils import nowdate, nowtime
from frappe.utils.nestedset import get_descendants_of

SITE = sys.argv[1]
frappe.init(site=SITE, sites_path=".")
frappe.connect()
frappe.set_user("Administrator")

from erpnext.stock.doctype.stock_reconciliation.stock_reconciliation import get_items as core_get_items  # noqa: E402
from isoft_customization.stock_reco_fetch import get_items  # noqa: E402

WAREHOUSE = sys.argv[2] if len(sys.argv) > 2 else "17 - Loja Benguela - ITEC"
COMPANY = frappe.db.get_value("Warehouse", WAREHOUSE, "company")
DATE, TIME = nowdate(), nowtime()
fails = 0


def check(name, cond, detail=""):
	global fails
	print(("PASS" if cond else "FAIL"), name, "" if cond else str(detail)[:600], flush=True)
	fails += not cond


def key(rows):
	return sorted(
		(r["item_code"], r["warehouse"], r.get("batch_no") or "", r["qty"], r["valuation_rate"], r.get("serial_no") or "")
		for r in rows
	)


def fetch(**kw):
	start = time.time()
	rows = get_items(WAREHOUSE, DATE, TIME, COMPANY, **kw)
	return rows, time.time() - start


start = time.time()
everything = core_get_items(WAREHOUSE, DATE, TIME, COMPANY)
core_secs = time.time() - start
item = {r.name: r for r in frappe.get_all("Item", fields=["name", "brand", "item_group"], filters={"name": ["in", list({r["item_code"] for r in everything})]})}
print("warehouse", WAREHOUSE, "|", len(everything), "rows from ERPNext in %.1fs" % core_secs)
check("warehouse has rows to filter", len(everything) > 20, len(everything))

# Most frequent brand, and the item group with the most sub-groups that holds items here.
brands = {}
for r in everything:
	b = item[r["item_code"]].brand
	if b:
		brands[b] = brands.get(b, 0) + 1
brand = max(brands, key=brands.get)
group, subgroups, best = None, [], 0
for g in {i.item_group for i in item.values()} | {frappe.db.get_value("Item Group", i.item_group, "parent_item_group") for i in item.values()}:
	if not g or not frappe.db.get_value("Item Group", g, "parent_item_group"):
		continue  # the root holds everything: proves nothing
	sub = get_descendants_of("Item Group", g)
	in_sub = sum(item[r["item_code"]].item_group in sub for r in everything)
	if in_sub > best:
		group, subgroups, best = g, sub, in_sub
print("brand", brand, "| item group", group, "with", len(subgroups), "sub-groups")

rows, _ = fetch()
check("no filter = ERPNext unchanged", key(rows) == key(everything))

rows, secs = fetch(brand=brand)
expected = [r for r in everything if item[r["item_code"]].brand == brand]
check("brand: same rows as ERPNext for that brand (%d rows, %.1fs)" % (len(rows), secs), key(rows) == key(expected) and rows, (len(rows), len(expected)))
check("brand: no other brand slipped in", all(item[r["item_code"]].brand == brand for r in rows))

in_group = set([group] + subgroups)
rows, secs = fetch(item_group=group)
expected = [r for r in everything if item[r["item_code"]].item_group in in_group]
check("item group incl. sub-groups (%d rows, %.1fs)" % (len(rows), secs), key(rows) == key(expected) and rows, (len(rows), len(expected)))
check("sub-group items are included", any(item[r["item_code"]].item_group != group for r in rows))

rows, _ = fetch(brand=brand, item_group=group)
expected = [r for r in everything if item[r["item_code"]].brand == brand and item[r["item_code"]].item_group in in_group]
check("brand AND item group (%d rows)" % len(rows), key(rows) == key(expected), (len(rows), len(expected)))

rows, _ = fetch(brand=brand, ignore_empty_stock=1)
expected = [r for r in core_get_items(WAREHOUSE, DATE, TIME, COMPANY, ignore_empty_stock=1) if item[r["item_code"]].brand == brand]
check("brand + ignore empty stock (%d rows)" % len(rows), key(rows) == key(expected), (len(rows), len(expected)))

some = next(r["item_code"] for r in everything if item[r["item_code"]].brand == brand)
other = next(b for b in brands if b != brand)
rows, _ = fetch(item_code=some, brand=brand)
check("item code of that brand: fetched", key(rows) == key(core_get_items(WAREHOUSE, DATE, TIME, COMPANY, some)) and rows)
rows, _ = fetch(item_code=some, brand=other)
check("item code of another brand: nothing", rows == [], rows)

rows, _ = fetch(brand="__no such brand__")
check("brand with no items: empty list", rows == [], rows)

frappe.db.rollback()
print("\n%d failure(s)" % fails)
sys.exit(1 if fails else 0)
