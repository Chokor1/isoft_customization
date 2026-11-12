"""Quotation note -> Sales Invoice / Sales Order "Additional Notes" (posa_notes). Rolled back.

Run from sites/: ../env/bin/python ../apps/isoft_customization/isoft_customization/tests/quotation_note_check.py dev.isoft.ao
"""
import os
import sys

import frappe
from frappe.utils import nowdate

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import multi_buy_fixtures as fx  # noqa: E402

frappe.init(site=sys.argv[1], sites_path=".")
frappe.connect()
frappe.set_user("Administrator")
fails = 0
NOTE = "Entrega em 15 dias. Garantia de 12 meses."


def check(name, cond, detail=""):
	global fails
	print(("PASS" if cond else "FAIL"), name, "" if cond else str(detail)[:300])
	fails += not cond


try:
	q = frappe.get_doc({"doctype": "Quotation", "quotation_to": "Customer", "party_name": "Abbass", "company": fx.COMPANY,
		"transaction_date": nowdate(), "selling_price_list": fx.PL, "currency": fx.CURRENCY, "conversion_rate": 1,
		"plc_conversion_rate": 1, "order_type": "Sales", "note": NOTE, "taxes": [dict(fx.IVA_ROW)],
		"items": [{"item_code": "PAP-A4", "qty": 1}]})
	q.insert()
	q.db_set("docstatus", 1)  # fixture: the mappers need a submitted quotation (no hooks, rolled back)
	for it in q.items:
		it.db_set("docstatus", 1)

	from erpnext.selling.doctype.quotation.quotation import make_sales_invoice, make_sales_order

	si = make_sales_invoice(q.name)
	check("invoice_gets_note", si.get("posa_notes") == NOTE, si.get("posa_notes"))
	so = make_sales_order(q.name)
	check("sales_order_gets_note", so.get("posa_notes") == NOTE, so.get("posa_notes"))

	from isoft_customization.quotation_notes import copy_quotation_note

	si.posa_notes = "typed by the user"
	copy_quotation_note(si)
	check("never_overwrites_a_typed_note", si.posa_notes == "typed by the user", si.posa_notes)
except Exception as e:  # noqa: BLE001
	import traceback

	traceback.print_exc()
	check("no_exception", False, repr(e))
finally:
	frappe.db.rollback()
	frappe.destroy()

print("FAILURES:", fails)
sys.exit(1 if fails else 0)
