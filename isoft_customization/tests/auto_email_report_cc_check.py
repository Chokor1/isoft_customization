"""Auto Email Report CC field. Nothing is sent (frappe.sendmail is captured), everything rolled back.

Run from sites/: ../env/bin/python ../apps/isoft_customization/isoft_customization/tests/auto_email_report_cc_check.py dev.isoft.ao
"""
import sys

import frappe

frappe.init(site=sys.argv[1], sites_path=".")
frappe.connect()
frappe.set_user("Administrator")
fails = 0


def check(name, cond, detail=""):
	global fails
	print(("PASS" if cond else "FAIL"), name, "" if cond else str(detail)[:300])
	fails += not cond


try:
	check("cc_field_exists", frappe.get_meta("Auto Email Report").has_field("isoft_email_cc"))
	d = frappe.get_doc({"doctype": "Auto Email Report", "report": "POS Customer Contacts", "user": "Administrator",
		"email_to": "a@example.com", "isoft_email_cc": "b@example.com, c@example.com\nb@example.com", "format": "HTML",
		"frequency": "Daily", "enabled": 0,
		"filters": frappe.as_json({"company": "ITEC LDA", "from_date": "2026-01-01", "to_date": "2026-01-31"})})
	d.insert(ignore_permissions=True)
	check("cc_normalised", d.isoft_email_cc == "b@example.com\nc@example.com", repr(d.isoft_email_cc))

	sent = []
	orig = frappe.sendmail
	frappe.sendmail = lambda *a, **kw: sent.append(kw)
	try:
		d.get_report_content = lambda: "<p>report</p>"
		d.send()
	finally:
		frappe.sendmail = orig
	check("sent_with_cc", sent and sent[0].get("cc") == ["b@example.com", "c@example.com"] and sent[0].get("recipients") == ["a@example.com"], sent)
	check("sendmail_restored", frappe.sendmail is orig)

	bad = frappe.get_doc("Auto Email Report", d.name)
	bad.isoft_email_cc = "not-an-email"
	try:
		bad.save(ignore_permissions=True)
		check("invalid_cc_refused", False, "saved")
	except frappe.ValidationError:
		check("invalid_cc_refused", True)
except Exception as e:  # noqa: BLE001
	import traceback

	traceback.print_exc()
	check("no_exception", False, repr(e))
finally:
	frappe.db.rollback()
	frappe.destroy()

print("FAILURES:", fails)
sys.exit(1 if fails else 0)
