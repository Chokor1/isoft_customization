"""Back-dated cost-only Stock Reconciliation of serialized stock (serial_cost_reconciliation.py).

Recreates production's MAT-RECO-2026-00084 (20VE00RSPG at 913,350 on 31/12/2025, whose serial
MP25H5CS was transferred and sold in 2026) on a production copy, submits it, runs the stock
repost, checks values and serial nos, then cancels it and checks everything is back.
WRITES to the site (a submitted then cancelled reconciliation): run on erp-testing only.

Run from sites/: ../env/bin/python ../apps/isoft_customization/isoft_customization/tests/serial_cost_reco_check.py erp-testing.itec.ao
"""
import sys

import frappe
from frappe.utils import flt

SITE = sys.argv[1]
assert SITE.startswith("erp-testing"), "writes stock and GL: production copy only"
frappe.init(site=SITE, sites_path=".")
frappe.connect()
frappe.set_user("Administrator")

ITEM, NEW_RATE = "20VE00RSPG", 913350.0
DATE, TIME = "2025-12-31", "23:59:00"
WAREHOUSES = ["05 - Garantia - ITEC", "17 - Loja Benguela - ITEC"]
SERIAL_FIELDS = ["warehouse", "status", "purchase_document_no", "delivery_document_no"]
fails = 0


def check(name, cond, detail=""):
	global fails
	print(("PASS" if cond else "FAIL"), name, "" if cond else str(detail)[:600], flush=True)
	fails += not cond


def run_reposts():
	from erpnext.stock.doctype.repost_item_valuation.repost_item_valuation import repost

	for name in frappe.get_all("Repost Item Valuation", filters={"status": "Queued", "docstatus": 1}, pluck="name", order_by="creation"):
		repost(frappe.get_doc("Repost Item Valuation", name))
	frappe.db.commit()


def bins():
	return {
		b.warehouse: (flt(b.actual_qty), flt(b.stock_value, 2))
		for b in frappe.get_all("Bin", filters={"item_code": ITEM}, fields=["warehouse", "actual_qty", "stock_value"])
	}


def serial_state(serials):
	return {s: frappe.db.get_value("Serial No", s, SERIAL_FIELDS + ["purchase_rate"], as_dict=1) for s in serials}


def gl_balance(voucher_type, voucher_no):
	return frappe.db.sql("""select account, sum(debit) - sum(credit) from `tabGL Entry`
		where voucher_type=%s and voucher_no=%s and is_cancelled=0 group by account""", (voucher_type, voucher_no))


from erpnext.stock.doctype.stock_reconciliation.stock_reconciliation import get_stock_balance_for
from erpnext.stock.doctype.serial_no.serial_no import get_serial_nos

run_reposts()  # anything left over, so the baseline is settled
company = frappe.db.get_value("Warehouse", WAREHOUSES[0], "company")
rows, all_serials = [], []
for wh in WAREHOUSES:
	bal = get_stock_balance_for(ITEM, wh, DATE, TIME)
	rows.append({"item_code": ITEM, "warehouse": wh, "qty": bal["qty"], "valuation_rate": NEW_RATE,
		"serial_no": bal["serial_nos"], "current_qty": bal["qty"], "current_valuation_rate": bal["rate"],
		"current_serial_no": bal["serial_nos"]})
	all_serials += get_serial_nos(bal["serial_nos"])
print("rows:", [(r["warehouse"], r["qty"], r["current_valuation_rate"]) for r in rows])
check("has_the_blocking_serial", "MP25H5CS" in all_serials, all_serials)

before_bins, before_serials = bins(), serial_state(all_serials)
dn_cost_before = frappe.db.get_value("Stock Ledger Entry", {"voucher_no": "GR 2026/809", "item_code": ITEM, "is_cancelled": 0}, "stock_value_difference")

reco = frappe.get_doc({"doctype": "Stock Reconciliation", "company": company, "purpose": "Stock Reconciliation",
	"set_posting_time": 1, "posting_date": DATE, "posting_time": TIME, "items": rows})
reco.insert()
check("override_class_in_use", type(reco).__name__ == "IsoftStockReconciliation", type(reco))
reco.submit()
frappe.db.commit()
print("submitted", reco.name)

sles = frappe.get_all("Stock Ledger Entry", filters={"voucher_no": reco.name, "is_cancelled": 0},
	fields=["warehouse", "serial_no", "actual_qty", "stock_value_difference", "qty_after_transaction", "valuation_rate"])
garantia = [s for s in sles if s.warehouse == WAREHOUSES[0]]
check("garantia_value_only_entry", len(garantia) == 1 and not garantia[0].serial_no and flt(garantia[0].actual_qty) == 0, garantia)
g_qty = rows[0]["qty"]
check("garantia_difference", abs(flt(garantia[0].stock_value_difference) - g_qty * (NEW_RATE - rows[0]["current_valuation_rate"])) < 1, garantia)
benguela = [s for s in sles if s.warehouse == WAREHOUSES[1]]
check("benguela_standard_serial_path", benguela and all(s.serial_no for s in benguela), benguela)
diff = sum(r["qty"] * (NEW_RATE - r["current_valuation_rate"]) for r in rows)
gl = gl_balance("Stock Reconciliation", reco.name)
check("gl_balanced", abs(sum(flt(b) for _a, b in gl)) < 0.01, gl)
adjust = frappe.db.get_value("Stock Reconciliation", reco.name, "expense_account")
check("gl_stock_change", abs(sum(flt(b) for a, b in gl if a == adjust) + diff) < 1, (diff, gl))

after = serial_state(all_serials)
# the Garantia row was posted value-only: its serial nos keep their history (Benguela took the standard path)
moved = [s for s in all_serials if s in get_serial_nos(rows[0]["serial_no"]) and
	{f: after[s][f] for f in SERIAL_FIELDS} != {f: before_serials[s][f] for f in SERIAL_FIELDS}]
check("serial_history_untouched", not moved, [(s, before_serials[s], after[s]) for s in moved][:3])
check("serial_cost_updated", all(flt(after[s].purchase_rate) == NEW_RATE for s in all_serials), {s: after[s].purchase_rate for s in all_serials})

run_reposts()
now_bins = bins()
for wh in WAREHOUSES:
	qty, value = now_bins.get(wh, (0, 0))
	check("value_now_at_new_rate " + wh, abs(value - qty * NEW_RATE) < 1, (qty, value))
# MP25H5CS left Garantia in Jan at the new cost; MAT-RECO-2026-00035 (18/02) counted it again at the old
# cost, so that count now carries the difference back and the later sale keeps the old cost.
def out_value(voucher, wh):
	return flt(frappe.db.get_value("Stock Ledger Entry", {"voucher_no": voucher, "warehouse": wh, "item_code": ITEM,
		"is_cancelled": 0, "actual_qty": ("<", 0), "serial_no": ("like", "%MP25H5CS%")}, "stock_value_difference"))
check("transfer_after_date_recosted", abs(out_value("GT MAC2026/460", WAREHOUSES[0]) + NEW_RATE) < 1, out_value("GT MAC2026/460", WAREHOUSES[0]))
check("later_count_recosted", abs(out_value("MAT-RECO-2026-00035", "07 - Maculusso Armazem - ITEC") + NEW_RATE) < 1)
dn_cost = frappe.db.get_value("Stock Ledger Entry", {"voucher_no": "GR 2026/809", "item_code": ITEM, "is_cancelled": 0}, "stock_value_difference")
check("sale_after_later_count_unchanged", abs(flt(dn_cost) - flt(dn_cost_before)) < 1, (dn_cost_before, dn_cost))
failed = frappe.get_all("Repost Item Valuation", filters={"status": "Failed", "modified": (">", reco.creation)}, fields=["name", "error_log"])
check("repost_no_failures", not failed, failed)

reco.reload()
reco.cancel()
frappe.db.commit()
run_reposts()
check("cancel_ok", reco.docstatus == 2)
back = serial_state(all_serials)
check("cancel_serials_back", back == before_serials, [(s, before_serials[s], back[s]) for s in all_serials if back[s] != before_serials[s]][:3])
check("cancel_bins_back", bins() == before_bins, (before_bins, bins()))
dn_cost_back = frappe.db.get_value("Stock Ledger Entry", {"voucher_no": "GR 2026/809", "item_code": ITEM, "is_cancelled": 0}, "stock_value_difference")
check("cancel_sale_cost_back", abs(flt(dn_cost_back) - flt(dn_cost_before)) < 1, (dn_cost_before, dn_cost_back))
check("cancel_gl_reversed", abs(sum(flt(b) for _a, b in gl_balance("Stock Reconciliation", reco.name))) < 0.01)

frappe.destroy()
print("FAILURES:", fails)
sys.exit(1 if fails else 0)
