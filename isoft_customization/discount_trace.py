"""Stores the browser recorder's steps for a line that reached 100% discount by itself
(public/js/discount_trace.js). Read-only diagnostics: one Error Log per occurrence,
titled "Isoft discount trace", at most 30 per user per day."""
import json

import frappe
from frappe.utils import add_days, now_datetime

TITLE = "Isoft discount trace"
PER_DAY = 30


@frappe.whitelist()
def record(payload=None):
	if frappe.session.user == "Guest":
		return
	since = add_days(now_datetime(), -1)
	if frappe.db.count("Error Log", {"method": TITLE, "owner": frappe.session.user, "creation": (">", since)}) >= PER_DAY:
		return
	try:
		data = json.loads(payload or "{}")
	except ValueError:
		data = {"raw": str(payload)[:2000]}
	data["user"] = frappe.session.user
	text = json.dumps(data, indent=1, default=str)[:60000]
	frappe.get_doc({"doctype": "Error Log", "method": TITLE, "error": text}).insert(ignore_permissions=True)
	frappe.db.commit()
