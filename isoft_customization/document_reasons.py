"""Mandatory reasons for cancelling selling documents and submitting credit notes.

Two switches on Selling Settings, both off by default:

* Require Reason on Cancel -- Quotation, Sales Order, Delivery Note and Sales Invoice
  cannot be cancelled without a `cancellation_reason`. Sales Invoice already has that
  field in the ERPNext fork; the other three get it as a read-only Custom Field.
* Require Reason on Credit Note Submit -- a Sales Invoice with is_return = 1 cannot be
  submitted without `return_reason`.

The reason is asked for only once the document has passed validation, so nobody types
a reason for a cancel that FE Angola, a closed accounting period or ERPNext then
refuses. The check runs at the last moment before the row is written: every app's
before_cancel / before_submit hook and core validation have run, and no on_cancel /
on_submit handler has. It cannot go any later -- FE Angola queues the AGT annulment in
on_cancel straight to redis, which a rollback does not take back. It cannot be a plain
before_cancel handler either: hooks run in app install order and
angola_accounting_periods' period guard sorts after this app. So the handler arms a
one-shot guard on the document's db_update / db_insert instead.

A missing reason raises CancellationReasonRequired / CreditNoteReasonRequired;
public/js/document_reasons.js catches exactly those, asks, and replays the request.
REST, scripts and list-view bulk actions simply get the error.

The desk cancel endpoint reloads the document from the DB, so the cancel reason cannot
ride along with the request: the desk stashes it in redis for the user first
(stash_cancel_reason). "Cancel All" cancels the linked documents before the one the
user pressed Cancel on; the stash lists them, they inherit the reason, and the parent's
own request then finds it without asking again.

POS Awesome returns are exempt from the credit note rule: the till has no prompt, and
blocking a return at the counter is worse than an unexplained one.
"""
from __future__ import unicode_literals

import json

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.utils import cint, now

SETTINGS = "Selling Settings"
CANCEL_FLAG = "isoft_require_cancel_reason"
CREDIT_NOTE_FLAG = "isoft_require_credit_note_reason"

CANCEL_REASON_DOCTYPES = ("Quotation", "Sales Order", "Delivery Note", "Sales Invoice")

STASH_TTL = 600


class CancellationReasonRequired(frappe.ValidationError):
	pass


class CreditNoteReasonRequired(frappe.ValidationError):
	pass


def get_custom_fields():
	fields = {
		SETTINGS: [
			{
				"fieldname": "isoft_document_reasons_section",
				"fieldtype": "Section Break",
				"label": "Document Reasons",
				"insert_after": "credit_note_auto_naming_angola",
			},
			{
				"fieldname": CANCEL_FLAG,
				"fieldtype": "Check",
				"label": "Require Reason on Cancel",
				"description": "Ask for a reason when cancelling a Quotation, Sales Order, Delivery Note or Sales Invoice. The document cannot be cancelled without one.",
				"insert_after": "isoft_document_reasons_section",
			},
			{
				"fieldname": CREDIT_NOTE_FLAG,
				"fieldtype": "Check",
				"label": "Require Reason on Credit Note Submit",
				"description": "Ask for a reason when submitting a credit note (Sales Invoice return). Returns made in POS Awesome are exempt.",
				"insert_after": CANCEL_FLAG,
			},
		],
		"Sales Invoice": [
			{
				"fieldname": "return_reason",
				"fieldtype": "Small Text",
				"label": "Credit Note Reason",
				"insert_after": "return_against",
				"depends_on": "eval:doc.is_return",
				"no_copy": 1,
				"translatable": 0,
			},
		],
	}
	for doctype in CANCEL_REASON_DOCTYPES:
		if doctype == "Sales Invoice":
			continue  # standard field in the ERPNext fork
		fields[doctype] = [
			{
				"fieldname": "cancellation_reason",
				"fieldtype": "Small Text",
				"label": "Cancellation Reason",
				"insert_after": "amended_from",
				"depends_on": "eval:doc.cancellation_reason",
				"read_only": 1,
				"allow_on_submit": 1,
				"no_copy": 1,
				"translatable": 0,
			},
		]
	return fields


def setup_custom_fields():
	"""Idempotent; runs from after_migrate."""
	fields = get_custom_fields()
	missing = {
		doctype
		for doctype, rows in fields.items()
		for row in rows
		if not frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": row["fieldname"]})
	}
	create_custom_fields(fields, update=True)

	# An amendment must not inherit the reason its cancelled original was given.
	if not frappe.db.exists(
		"Property Setter",
		{"doc_type": "Sales Invoice", "field_name": "cancellation_reason", "property": "no_copy", "value": "1"},
	):
		make_property_setter(
			"Sales Invoice", "cancellation_reason", "no_copy", 1, "Check", validate_fields_for_doctype=False
		)
		missing.add("Sales Invoice")

	# Browsers cache form meta in localStorage keyed on DocType.modified, which adding a
	# Custom Field does not touch; without this the new fields never show up.
	for doctype in missing:
		frappe.db.set_value("DocType", doctype, "modified", now(), update_modified=False)
		frappe.clear_cache(doctype=doctype)


def _enabled(flag):
	return cint(frappe.get_cached_doc(SETTINGS, SETTINGS).get(flag))


def _clean(text):
	return (text or "").strip()


def _stash_key():
	return "isoft_cancel_reason|" + frappe.session.user


@frappe.whitelist()
def stash_cancel_reason(doctype, name, reason, links=None):
	"""Hold the reason typed in the desk prompt for the cancel request replayed next.

	*links* are the documents "Cancel All" cancels before doctype / name itself.
	"""
	reason = _clean(reason)
	if not reason:
		frappe.throw(_("Please enter a reason."))
	frappe.get_doc(doctype, name).check_permission("cancel")
	if isinstance(links, str):
		links = json.loads(links)
	links = [[d.get("doctype"), d.get("name")] for d in (links or []) if isinstance(d, dict)]
	frappe.cache().set_value(
		_stash_key(),
		{"doctype": doctype, "name": name, "reason": reason, "links": links},
		expires_in_sec=STASH_TTL,
	)


class _RestoreStash(object):
	"""Puts a consumed stash back when the cancel that used it rolls back, so a retry
	after an unrelated failure further on does not ask for the reason again."""

	def __init__(self, key, value):
		self.key = key
		self.value = value

	def on_rollback(self):
		frappe.cache().set_value(self.key, self.value, expires_in_sec=STASH_TTL)


def _reason_from_stash(doc):
	key = _stash_key()
	# expires=True, or a miss is memoised for the process and a later stash is never seen.
	stashed = frappe.cache().get_value(key, expires=True)
	if not stashed:
		return None
	if [stashed.get("doctype"), stashed.get("name")] == [doc.doctype, doc.name]:
		frappe.cache().delete_value(key)
		frappe.local.rollback_observers.append(_RestoreStash(key, stashed))
		return stashed["reason"]
	if [doc.doctype, doc.name] in (stashed.get("links") or []):
		# Left in place for the parent, which is cancelled in the next request.
		return _("{0} (cancelled together with {1} {2})").format(
			stashed["reason"], _(stashed["doctype"]), stashed["name"]
		)
	return None


def _check_before_write(doc, check):
	"""Run *check* right before the document's row is written -- see the module docstring."""

	def arm(attr):
		original = getattr(doc, attr)

		def guarded(*args, **kwargs):
			doc.__dict__.pop("db_update", None)
			doc.__dict__.pop("db_insert", None)
			check(doc)
			return original(*args, **kwargs)

		doc.__dict__[attr] = guarded

	arm("db_update")
	arm("db_insert")


def _require_cancel_reason(doc):
	reason = _reason_from_stash(doc)
	if reason:
		doc.cancellation_reason = reason
	if not _clean(doc.get("cancellation_reason")):
		frappe.throw(
			_("A cancellation reason is required to cancel {0} {1}.").format(_(doc.doctype), doc.name),
			exc=CancellationReasonRequired,
			title=_("Cancellation Reason"),
		)


def _require_credit_note_reason(doc):
	doc.return_reason = _clean(doc.get("return_reason"))
	if not doc.return_reason:
		frappe.throw(
			_("A reason is required to submit credit note {0}.").format(doc.name),
			exc=CreditNoteReasonRequired,
			title=_("Credit Note Reason"),
		)


def validate_cancel_reason(doc, method=None):
	"""before_cancel for CANCEL_REASON_DOCTYPES."""
	if _enabled(CANCEL_FLAG):
		_check_before_write(doc, _require_cancel_reason)


def validate_credit_note_reason(doc, method=None):
	"""before_submit for Sales Invoice."""
	if not cint(doc.get("is_return")) or not _enabled(CREDIT_NOTE_FLAG):
		return
	if (frappe.form_dict.get("cmd") or "").startswith("posawesome."):
		return
	_check_before_write(doc, _require_credit_note_reason)
