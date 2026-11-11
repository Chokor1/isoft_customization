"""Invoice stock reservation, end to end with REAL documents (submit / cancel / make_* mappers).

One transaction, rolled back at the end. frappe.db.commit is replaced first so any hook that tries
to commit fails the check instead of leaving data on the site. That guard is also what keeps FE
Angola / AGT out of it: registration is queued with enqueue_after_commit, which never fires here.

Run from sites/: ../env/bin/python ../apps/isoft_customization/isoft_customization/tests/invoice_reservation_flow_check.py dev.isoft.ao
"""
import os
import sys

import frappe
from frappe.utils import flt, nowdate

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import invoice_reservation_fixtures as fx  # noqa: E402

frappe.init(site=sys.argv[1], sites_path=".")
frappe.connect()
frappe.set_user("Administrator")
check, state = fx.check_factory()
WH = fx.WH


def _no_commit(*args, **kwargs):
	raise Exception("commit attempted")


frappe.db.commit = _no_commit


def bin_qty(item, field):
	return flt(frappe.db.get_value("Bin", {"item_code": item, "warehouse": WH}, field))


def submit(doc):
	"""saft_xml submits non-POS sales invoices and returns during insert; submit whatever is left."""
	if doc.get("__islocal") or not doc.name or not frappe.db.exists(doc.doctype, doc.name):
		doc.insert(ignore_permissions=True)
	doc.reload()
	if doc.docstatus == 0:
		doc.submit()
	return doc


def cancel(doctype, name):
	d = frappe.get_doc(doctype, name)
	if d.meta.has_field("cancellation_reason"):
		d.cancellation_reason = "invoice reservation check"
	d.cancel()


def receive(items, qty=20):
	se = frappe.get_doc({
		"doctype": "Stock Entry", "stock_entry_type": "Material Receipt", "purpose": "Material Receipt",
		"company": fx.COMPANY, "posting_date": nowdate(),
		"items": [{"item_code": i, "qty": qty, "t_warehouse": WH, "basic_rate": 500, "uom": "Nos",
			"conversion_factor": 1, "transfer_qty": qty} for i in items],
	})
	se.insert(ignore_permissions=True)
	se.submit()


try:
	from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import make_debit_note, make_purchase_receipt
	from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_delivery_note, make_sales_return
	from erpnext.stock.doctype.delivery_note.delivery_note import make_sales_return as make_dn_return
	from erpnext.stock.stock_balance import repost_stock


	item = fx.stock_item("IR-T3-A")
	ca = fx.stock_item("IR-T3-CA")
	cb = fx.stock_item("IR-T3-CB")
	bun = fx.bundle("IR-T3-BUN", [(ca, 2), (cb, 3)])
	plain = fx.stock_item("IR-T3-PLAIN")
	receive([item, ca, cb, plain])
	B = bin_qty(item, "reserved_qty")
	P0 = bin_qty(item, "projected_qty")

	# ---- sales
	si = submit(fx.draft_si([(item, 5)]))
	check("e2e_si_reserves", bin_qty(item, "reserved_qty") == B + 5, bin_qty(item, "reserved_qty") - B)
	check("e2e_si_projected", bin_qty(item, "projected_qty") == P0 - 5, bin_qty(item, "projected_qty") - P0)

	dn = make_delivery_note(si.name)
	dn.items[0].qty = 2
	dn = submit(dn)
	check("e2e_dn_partial", bin_qty(item, "reserved_qty") == B + 3, bin_qty(item, "reserved_qty") - B)

	cn = make_sales_return(si.name)
	cn.items[0].qty = -1
	cn.return_reason = "invoice reservation check"
	cn = submit(cn)
	check("e2e_credit_note", bin_qty(item, "reserved_qty") == B + 2, bin_qty(item, "reserved_qty") - B)

	dnr = make_dn_return(dn.name)
	dnr.items[0].qty = -1
	dnr.items[0].warehouse = dnr.items[0].warehouse or WH  # the return mapper leaves it empty on this fork
	dnr = submit(dnr)
	check("e2e_dn_return", bin_qty(item, "reserved_qty") == B + 3, bin_qty(item, "reserved_qty") - B)

	from isoft_customization.invoice_reservation import pending_summary, set_stopped

	set_stopped("Sales Invoice", si.name, 1)
	summ = pending_summary("Sales Invoice", si.name)
	check("e2e_stop", bin_qty(item, "reserved_qty") == B and summ.get("stopped") == 1 and summ.get("pending_qty") == 3,
		(bin_qty(item, "reserved_qty") - B, summ))
	set_stopped("Sales Invoice", si.name, 0)
	check("e2e_resume", bin_qty(item, "reserved_qty") == B + 3, bin_qty(item, "reserved_qty") - B)

	repost_stock(item, WH)
	check("e2e_repost_keeps_invoice_part", bin_qty(item, "reserved_qty") == B + 3, bin_qty(item, "reserved_qty") - B)

	cancel("Delivery Note", dnr.name)
	cancel("Delivery Note", dn.name)
	check("e2e_dn_cancel_restores", bin_qty(item, "reserved_qty") == B + 4, bin_qty(item, "reserved_qty") - B)
	cancel("Sales Invoice", cn.name)
	cancel("Sales Invoice", si.name)
	check("e2e_cancel_all", bin_qty(item, "reserved_qty") == B, bin_qty(item, "reserved_qty") - B)

	# ---- purchase
	O = bin_qty(item, "ordered_qty")
	pi = submit(fx.draft_pi([(item, 4)]))
	check("e2e_pi_orders", bin_qty(item, "ordered_qty") == O + 4, bin_qty(item, "ordered_qty") - O)
	pr = make_purchase_receipt(pi.name)
	pr.items[0].qty = 3
	pr.items[0].received_qty = 3
	pr = submit(pr)
	check("e2e_pr_partial", bin_qty(item, "ordered_qty") == O + 1, bin_qty(item, "ordered_qty") - O)
	cancel("Purchase Receipt", pr.name)
	check("e2e_pr_cancel", bin_qty(item, "ordered_qty") == O + 4, bin_qty(item, "ordered_qty") - O)
	dbn = make_debit_note(pi.name)
	dbn.update_stock = 0
	dbn.items[0].qty = -4
	dbn = submit(dbn)
	check("e2e_debit_note", bin_qty(item, "ordered_qty") == O, bin_qty(item, "ordered_qty") - O)
	cancel("Purchase Invoice", dbn.name)
	check("e2e_debit_note_cancel", bin_qty(item, "ordered_qty") == O + 4, bin_qty(item, "ordered_qty") - O)
	cancel("Purchase Invoice", pi.name)
	check("e2e_pi_cancel", bin_qty(item, "ordered_qty") == O, bin_qty(item, "ordered_qty") - O)

	# ---- bundle
	A, Bq = bin_qty(ca, "reserved_qty"), bin_qty(cb, "reserved_qty")
	sb = submit(fx.draft_si([(bun, 2)]))
	check("e2e_bundle", (bin_qty(ca, "reserved_qty") - A, bin_qty(cb, "reserved_qty") - Bq) == (4, 6),
		(bin_qty(ca, "reserved_qty") - A, bin_qty(cb, "reserved_qty") - Bq))
	dnb = make_delivery_note(sb.name)
	dnb.items[0].qty = 1
	submit(dnb)
	check("e2e_bundle_dn", (bin_qty(ca, "reserved_qty") - A, bin_qty(cb, "reserved_qty") - Bq) == (2, 3),
		(bin_qty(ca, "reserved_qty") - A, bin_qty(cb, "reserved_qty") - Bq))

	# ---- an unticked invoice changes nothing
	U = bin_qty(plain, "reserved_qty")
	submit(fx.draft_si([(plain, 3)], reserve=0))
	check("e2e_untouched_invoice", bin_qty(plain, "reserved_qty") == U, bin_qty(plain, "reserved_qty") - U)

	# ---- permission / state guards of the API
	try:
		set_stopped("Delivery Note", dnb.name, 1)
		check("set_stopped_rejects_other_doctypes", False, "no error")
	except frappe.ValidationError:
		check("set_stopped_rejects_other_doctypes", True)
except Exception as e:  # noqa: BLE001
	import traceback

	traceback.print_exc()
	check("no_exception", False, repr(e))
finally:
	frappe.db.rollback()
	frappe.destroy()
	sys.exit(1 if state["fails"] else 0)
