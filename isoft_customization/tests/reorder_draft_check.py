"""Stock Settings "Leave automatic Material Requests as Draft" (reorder_draft.py). Rolled back, no email sent.

Run from sites/: ../env/bin/python ../apps/isoft_customization/isoft_customization/tests/reorder_draft_check.py dev.isoft.ao
"""
import sys

import frappe

frappe.init(site=sys.argv[1], sites_path=".")
frappe.connect()
frappe.set_user("Administrator")
fails = 0
REQ = {"Purchase": {"ITEC LDA": [{"item_code": "PAP-A4", "warehouse": "01 - Loja Alvalade - ITEC", "reorder_qty": 5}]}}


def check(name, cond, detail=""):
	global fails
	print(("PASS" if cond else "FAIL"), name, "" if cond else str(detail)[:300])
	fails += not cond


orig_sendmail = frappe.sendmail
frappe.sendmail = lambda *a, **k: None
try:
	check("setting_field_exists", frappe.get_meta("Stock Settings").has_field("isoft_auto_mr_draft"))
	for method in frappe.get_hooks("before_job"):  # as the scheduler does before running the reorder job
		frappe.get_attr(method)()
	from erpnext.stock import reorder_item

	frappe.db.set_value("Stock Settings", None, "isoft_auto_mr_draft", 1)
	made = reorder_item.create_material_request(REQ) or []
	check("draft_when_on", made and all(m.docstatus == 0 for m in made) and frappe.db.get_value("Material Request", made[0].name, "docstatus") == 0,
		[(m.name, m.docstatus) for m in made])

	frappe.db.set_value("Stock Settings", None, "isoft_auto_mr_draft", 0)
	made = reorder_item.create_material_request(REQ) or []
	check("submitted_when_off", made and all(m.docstatus == 1 for m in made), [(m.name, m.docstatus) for m in made])

	from erpnext.stock.doctype.material_request.material_request import MaterialRequest

	check("submit_restored_after_run", getattr(MaterialRequest.submit, "__isoft_draft__", False) is False)
except Exception as e:  # noqa: BLE001
	import traceback

	traceback.print_exc()
	check("no_exception", False, repr(e))
finally:
	frappe.sendmail = orig_sendmail
	frappe.db.rollback()
	frappe.destroy()

print("FAILURES:", fails)
sys.exit(1 if fails else 0)
