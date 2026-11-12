"""CC on Auto Email Report: a "CC" field next to "Email To", sent as Cc on every run
(scheduled and "Send Now"). See overrides/auto_email_report.py."""
import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import validate_email_address

FIELD = "isoft_email_cc"


def setup_custom_fields(*args, **kwargs):
	create_custom_fields({"Auto Email Report": [{
		"fieldname": FIELD, "fieldtype": "Small Text", "label": "CC", "insert_after": "email_to",
		"description": "One email per line (or separated by commas). They receive the report in Cc.",
	}]}, update=True)


def clean_cc(value):
	"""'a@x, b@x\\na@x' -> ['a@x', 'b@x']; raises on an invalid address."""
	out = []
	for part in (value or "").replace(",", "\n").replace(";", "\n").split():
		email = part.strip()
		if not email:
			continue
		if not validate_email_address(email):
			frappe.throw(_("{0} in CC is not a valid email address").format(frappe.bold(email)))
		if email not in out:
			out.append(email)
	return out
