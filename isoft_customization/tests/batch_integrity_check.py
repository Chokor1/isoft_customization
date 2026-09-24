"""Acceptance check for isoft_customization.batch_integrity, run against a live site.

Everything it creates is rolled back at the end; nothing is committed. Submits only
Stock Entries (no AGT hooks); Sales Invoice and Delivery Note are only ever submitted
in cases that must fail in before_submit, before on_submit could reach AGT.

    cd sites && ../env/bin/python ../apps/isoft_customization/isoft_customization/tests/batch_integrity_check.py \
        [--site dev.isoft.ao] [--company "TEST 2"] [--with-existing-guards]

dev.isoft.ao carries two older, blunter batch guards: isoft_invenza's validations and a
"Validate Batch Before Save" Server Script on Batch. Neither has an escape hatch, so by
default both are stubbed out and only these guards are exercised (ptperp.isoft.ao has
neither, or the incident could not have happened). --with-existing-guards leaves them
in place to show the combined behaviour.
"""
import argparse
import sys
import traceback

import frappe
from frappe.utils import nowdate, random_string

ap = argparse.ArgumentParser()
ap.add_argument("--site", default="dev.isoft.ao")
ap.add_argument("--company", default="TEST 2")
ap.add_argument("--with-existing-guards", action="store_true")
args = ap.parse_args()

frappe.init(site=args.site, sites_path="/home/frappe/frappe-bench/sites")
frappe.connect()
frappe.set_user("Administrator")
frappe.flags.atc_nif_pos_context = True


class CommitAttempted(Exception):
	pass


def _no_commit(*args, **kwargs):
	# ERPNext's SalesInvoice.on_submit commits (add_mapped_identity). If a guard
	# ever lets a bad invoice reach it, fail loudly instead of persisting test data.
	raise CommitAttempted("something tried to commit during the check")


frappe.db.commit = _no_commit

from isoft_customization.batch_integrity import (  # noqa: E402
	BatchItemMismatchError,
	BatchItemReassignmentError,
	find_batch_item_mismatches,
)

if not args.with_existing_guards:
	if "isoft_invenza" in frappe.get_installed_apps():
		import isoft_invenza.overrides.validations as inv

		for fn in (
			"validate_invoice_batch_item",
			"validate_stock_entry_batch_item",
			"validate_batch_item_not_changing_if_in_use",
		):
			setattr(inv, fn, lambda doc, method=None: None)

	import frappe.model.document as document_module

	_run_server_script = document_module.run_server_script_for_doc_event

	def _skip_batch_server_scripts(doc, event):
		if doc.doctype != "Batch":
			return _run_server_script(doc, event)

	document_module.run_server_script_for_doc_event = _skip_batch_server_scripts

TAG = "BI-TEST-" + random_string(5).upper()
C = args.company
WH = frappe.db.sql(
	"select name from tabWarehouse where company=%s and is_group=0 and disabled=0 order by name limit 1", C
)[0][0]
IVA_TEMPLATE = frappe.db.get_value("Item Tax Template", {"tax_type": "IVA", "company": C}) or frappe.db.get_value(
	"Item Tax Template", {"tax_type": "IVA"}
)
CC = frappe.get_cached_value("Company", C, "cost_center")
POS_MOP = frappe.db.get_value("Mode of Payment Account", {"company": C, "default_account": ("!=", "")}, "parent")
results = []


def check(case, label, ok, detail=""):
	results.append((case, label, bool(ok), detail))
	print("{:<5} {:<4} {}{}".format(case, "PASS" if ok else "FAIL", label, (" -- " + detail) if detail else ""))


def raises(fn, exc):
	try:
		fn()
	except exc as e:
		frappe.local.message_log = []
		return e
	return None


def ledger_counts(doctype, name):
	sle = frappe.db.count("Stock Ledger Entry", {"voucher_type": doctype, "voucher_no": name})
	gle = frappe.db.count("GL Entry", {"voucher_type": doctype, "voucher_no": name})
	return sle, gle


def assert_blocked_draft(case, label, doc):
	err = raises(doc.submit, BatchItemMismatchError)
	check(case, label + ": blocked with BatchItemMismatchError", err, str(err)[:160] if err else "")
	ds = frappe.db.get_value(doc.doctype, doc.name, "docstatus")
	sle, gle = ledger_counts(doc.doctype, doc.name)
	check(case, label + ": docstatus in DB still 0", ds == 0, "docstatus={}".format(ds))
	check(case, label + ": no Stock Ledger / GL rows", sle == 0 and gle == 0, "sle={} gl={}".format(sle, gle))


def make_item(code, stock=1, batch=1):
	item = frappe.get_doc({
		"doctype": "Item", "item_code": code, "item_name": code, "item_group": "All Item Groups",
		"stock_uom": "Nos", "is_stock_item": stock, "has_batch_no": batch, "include_item_in_manufacturing": 0,
		# dev.isoft.ao's "Item Validation" Server Script refuses items without an IVA template
		"taxes": [{"item_tax_template": IVA_TEMPLATE}] if IVA_TEMPLATE else [],
	})
	# site-level mandatory customisations (brand, tax_category, ...) are not under test
	item.flags.ignore_mandatory = True
	return item.insert()


def make_batch(batch_id, item):
	return frappe.get_doc({"doctype": "Batch", "batch_id": batch_id, "item": item}).insert()


def stock_entry(purpose, item, batch, qty, submit=True):
	row = {
		"item_code": item, "qty": qty, "uom": "Nos", "conversion_factor": 1, "batch_no": batch, "basic_rate": 100,
		# the desk form fills these from item details; a direct insert does not
		"expense_account": frappe.get_cached_value("Company", C, "stock_adjustment_account"),
		"cost_center": frappe.get_cached_value("Company", C, "cost_center"),
	}
	row["t_warehouse" if purpose == "Material Receipt" else "s_warehouse"] = WH
	se = frappe.get_doc({
		"doctype": "Stock Entry", "stock_entry_type": purpose, "purpose": purpose, "company": C,
		"posting_date": nowdate(), "items": [row],
	}).insert()
	if submit:
		se.submit()
	return se


try:
	A, B, P = TAG + "-A", TAG + "-B", TAG + "-BUNDLE"
	make_item(A)
	make_item(B)
	make_item(P, stock=0, batch=0)
	frappe.get_doc({"doctype": "Product Bundle", "new_item_code": P, "items": [{"item_code": A, "qty": 1}]}).insert()

	# 3 · insert
	BA = make_batch(TAG + "-BA", A).name
	BZ = make_batch(TAG + "-BZ", A).name
	check("3", "insert new batch allowed", frappe.db.exists("Batch", BA))

	# 2 · save without changing item
	b = frappe.get_doc("Batch", BA)
	b.description = "touched"
	b.save()
	check("2", "save batch without item change allowed", True)

	# 7 · correct doc submits (receipt into BA under A)
	se_in = stock_entry("Material Receipt", A, BA, 10)
	sle, gle = ledger_counts("Stock Entry", se_in.name)
	check("7", "correct Stock Entry submits", se_in.docstatus == 1 and sle == 1, "sle={} gl={}".format(sle, gle))

	# 4 · re-point a batch with no history
	b = frappe.get_doc("Batch", BZ)
	b.item = B
	b.save()
	check("4", "re-point batch with zero ledger allowed", frappe.db.get_value("Batch", BZ, "item") == B)

	# 1 · re-point a batch with history
	b = frappe.get_doc("Batch", BA)
	b.item = B
	err = raises(b.save, BatchItemReassignmentError)
	msg = str(err or "")
	check("1", "re-point batch with ledger blocked", err)
	check("1", "message names item, count and qty", A in msg and ": 1 ledger" in msg and "10" in msg, msg[:220])
	check("1", "batch master unchanged", frappe.db.get_value("Batch", BA, "item") == A)

	# 9 · Data Import update path (Importer.update_record -> save, in_import set)
	from frappe.core.doctype.data_import.importer import Importer, get_id_field

	imp = Importer.__new__(Importer)
	imp.doctype = "Batch"
	imp.data_import = frappe._dict(doctype="Data Import", name=TAG)
	frappe.flags.in_import = True
	try:
		err = raises(lambda: imp.update_record(frappe._dict({get_id_field("Batch").fieldname: BA, "item": B})), BatchItemReassignmentError)
	finally:
		frappe.flags.in_import = False
	check("9", "Data Import re-point blocked", err and frappe.db.get_value("Batch", BA, "item") == A)

	# 5 · escape hatch
	frappe.flags.allow_batch_item_reassignment = True
	try:
		b = frappe.get_doc("Batch", BA)
		b.item = B
		err = raises(b.save, frappe.ValidationError)
		check("5", "re-point allowed with flag", not err and frappe.db.get_value("Batch", BA, "item") == B, str(err or "")[:160])
	finally:
		frappe.flags.allow_batch_item_reassignment = False

	# detection sees the drift the flag just created
	rows = [r for r in find_batch_item_mismatches() if r.batch_no == BA]
	check("det", "detection reports the drifted batch",
		len(rows) == 1 and rows[0].master_item == B and rows[0].ledger_item == A and rows[0].qty == 10 and rows[0].entries == 1,
		str(rows))

	# 6 · drift already in the data: submit docs selling A from BA (now owned by B)
	se_out = stock_entry("Material Issue", A, BA, 2, submit=False)
	assert_blocked_draft("6", "Stock Entry", se_out)

	def sales_invoice(is_pos=0):
		si = frappe.get_doc({
			"doctype": "Sales Invoice", "company": C, "customer": frappe.db.get_value("Customer", {"disabled": 0}),
			"posting_date": nowdate(), "update_stock": 1, "set_warehouse": WH, "is_pos": is_pos,
			"taxes_and_charges": frappe.db.get_value("Sales Taxes and Charges Template", {"company": C}),
			"cost_center": CC,
			"items": [{"item_code": A, "qty": 2, "rate": 100, "warehouse": WH, "batch_no": BA, "cost_center": CC,
				"item_tax_template": frappe.db.get_value("Item Tax Template", {"company": C}),
				"income_account": frappe.get_cached_value("Company", C, "default_income_account") or frappe.db.get_value(
					"Account", {"company": C, "root_type": "Income", "is_group": 0}),
				"expense_account": frappe.get_cached_value("Company", C, "default_expense_account")}],
		})
		# a Server Script on dev refuses a taxed item with no tax lines
		from erpnext.controllers.accounts_controller import get_taxes_and_charges

		si.set("taxes", get_taxes_and_charges("Sales Taxes and Charges Template", si.taxes_and_charges))
		if is_pos:
			si.set_missing_values()
			si.calculate_taxes_and_totals()
			si.append("payments", {"mode_of_payment": POS_MOP, "amount": si.rounded_total or si.grand_total})
		return si

	# desk invoice: saft_xml's before_save turns this insert into a submit, so
	# before_submit never runs and the before_save arm has to catch it
	try:
		si = sales_invoice()
		err = raises(si.insert, BatchItemMismatchError)
		if err:
			sle, gle = ledger_counts("Sales Invoice", si.name)
			check("6", "Sales Invoice (auto-submit on save): blocked with BatchItemMismatchError", True, str(err)[:120])
			check("6", "Sales Invoice (auto-submit on save): row never written",
				not frappe.db.exists("Sales Invoice", si.name) and sle == 0 and gle == 0,
				"exists={} sle={} gl={}".format(bool(frappe.db.exists("Sales Invoice", si.name)), sle, gle))
		else:
			# saft_xml not installed: the insert is a plain draft
			assert_blocked_draft("6", "Sales Invoice (draft then submit)", si)
	except Exception as e:
		traceback.print_exc()
		check("6", "Sales Invoice (auto-submit) fixture could not be built", False, repr(e)[:200])

	# POS invoice (the incident's shape): saved as draft, submitted explicitly
	if POS_MOP:
		try:
			si = sales_invoice(is_pos=1)
			si.insert()
			check("6", "POS Sales Invoice saved as draft", frappe.db.get_value("Sales Invoice", si.name, "docstatus") == 0)
			assert_blocked_draft("6", "POS Sales Invoice", si)
		except Exception as e:
			traceback.print_exc()
			check("6", "POS Sales Invoice fixture could not be built", False, repr(e)[:200])
	else:
		check("6", "POS Sales Invoice skipped: no Mode of Payment account for " + C, False)

	# 8 · Product Bundle, bad batch on the packed row only
	try:
		dn = frappe.get_doc({
			"doctype": "Delivery Note", "company": C, "customer": frappe.db.get_value("Customer", {"disabled": 0}),
			"posting_date": nowdate(), "set_warehouse": WH,
			"cost_center": CC,
			"items": [{"item_code": P, "qty": 2, "rate": 100, "warehouse": WH, "cost_center": CC,
				"expense_account": frappe.get_cached_value("Company", C, "default_expense_account")}],
		}).insert()
		packed = dn.get("packed_items") or []
		for r in packed:
			r.batch_no = BA
		dn.save()
		check("8", "packed row carries the bad batch, parent row none",
			len(dn.packed_items) == 1 and dn.packed_items[0].batch_no == BA and not dn.items[0].batch_no)
		assert_blocked_draft("8", "Delivery Note packed_items", dn)
	except Exception as e:
		check("8", "Delivery Note fixture could not be built", False, repr(e)[:200])

	# repair direction: re-pointing back to the ledger item needs no flag
	b = frappe.get_doc("Batch", BA)
	b.item = A
	err = raises(b.save, frappe.ValidationError)
	check("rep", "re-point towards the ledger item allowed", not err, str(err or "")[:160])

	# 7 · correct doc submits after repair
	se_ok = stock_entry("Material Issue", A, BA, 2)
	check("7", "correct Material Issue submits after repair", se_ok.docstatus == 1)
except Exception as e:
	traceback.print_exc()
	check("!", "unexpected error", False, repr(e)[:200])
finally:
	frappe.db.rollback()
	frappe.flags.allow_batch_item_reassignment = False

left = frappe.db.sql("select count(*) from tabItem where name like %s", TAG + "%")[0][0]
check("cln", "rollback left nothing behind", left == 0, "items left={}".format(left))
failed = [r for r in results if not r[2]]
print("\n{} checks, {} failed".format(len(results), len(failed)))
frappe.destroy()
sys.exit(1 if failed else 0)
