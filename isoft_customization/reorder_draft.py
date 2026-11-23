"""Stock Settings "Leave automatic Material Requests as Draft".

ERPNext's automatic reorder (Stock Settings > "Raise Material Request when stock reaches
re-order level", the daily reorder_item job) inserts AND submits each Material Request.
With this switch on, create_material_request still inserts them but skips the submit:
they wait as drafts for someone to review, edit and submit. Only that job is affected;
Material Requests made by hand or from other documents are untouched.

The wrapper is installed like the other runtime patches (before_request / before_job).
"""
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cint

FIELD = "isoft_auto_mr_draft"
_original = {}


def setup_custom_fields(*args, **kwargs):
	create_custom_fields({"Stock Settings": [{
		"fieldname": FIELD, "fieldtype": "Check", "default": "0", "insert_after": "reorder_email_notify",
		"label": "Leave automatic Material Requests as Draft", "depends_on": "eval:doc.auto_indent",
		"description": "Material Requests raised at re-order level are saved but not submitted, so they can be "
			"reviewed, changed and submitted by hand.",
	}]}, update=True)


def _enabled():
	return cint(frappe.db.get_single_value("Stock Settings", FIELD)) if frappe.get_meta("Stock Settings").has_field(FIELD) else 0


def create_material_request(material_requests):
	if not _enabled():
		return _original["create_material_request"](material_requests)
	from erpnext.stock.doctype.material_request.material_request import MaterialRequest

	submit = MaterialRequest.submit

	def keep_as_draft(self, *args, **kwargs):
		return None  # inserted by the reorder job, left for a person to submit

	keep_as_draft.__isoft_draft__ = True
	MaterialRequest.submit = keep_as_draft
	try:
		return _original["create_material_request"](material_requests)
	finally:
		MaterialRequest.submit = submit


def apply(*args, **kwargs):
	"""Point ERPNext's reorder at the wrapper. Idempotent; takes before_job's arguments."""
	from erpnext.stock import reorder_item

	if reorder_item.create_material_request is not create_material_request:
		_original.setdefault("create_material_request", reorder_item.create_material_request)
		reorder_item.create_material_request = create_material_request
