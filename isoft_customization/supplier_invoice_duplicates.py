# Copyright (c) 2026, Isoft and Contributors
# MIT License. See license.txt

"""One supplier invoice number may be entered once per supplier.

A supplier's invoice number is the reference printed on the bill they sent us,
kept in `bill_no` ("Supplier Invoice No"). Booking the same bill twice pays it
twice and doubles the deductible IVA, so a second Purchase Invoice carrying a
number that supplier already used is refused, with a link to the one that has
it.

ERPNext ships a similar check, but it is off by default
(Accounts Settings -> "Check Supplier Invoice Uniqueness") and, when on, only
looks inside the fiscal year of the posting date -- so the same bill re-entered
in January after a December invoice passes straight through. This one has no
such window.

What it deliberately does NOT block:

* **Debit notes.** A return copies the original bill's number, because it is
  about that bill; blocking it would make returns impossible.
* **Amendments.** The cancelled original is docstatus 2 and never counted.
* **Other companies.** Each company keeps its own books, and the same number
  reaching two companies is a separate question from entering it twice in one.
* **Editing an old invoice.** The rule only runs when the document is new, when
  the supplier or the number changes, and on submit. Sites that already hold
  duplicates (dev had eight such pairs when this was written) can therefore
  still open and edit them; only a new duplicate, or submitting one, is stopped.
"""

from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.utils import cint

KEY_FIELDS = ("supplier", "bill_no", "company")


class DuplicateSupplierInvoice(frappe.ValidationError):
	pass


def _clean(value):
	"""Compare without surrounding or repeated spaces. Case is handled by the
	database collation, which is case-insensitive on this bench."""
	return " ".join((value or "").split())


def find_duplicate(doc):
	"""The other Purchase Invoice holding this supplier's number, or None."""
	bill_no = _clean(doc.get("bill_no"))
	if not bill_no or not doc.get("supplier") or cint(doc.get("is_return")):
		return None

	rows = frappe.db.sql(
		"""select name, posting_date, bill_date, docstatus, grand_total, currency
		from `tabPurchase Invoice`
		where supplier = %(supplier)s
			and company = %(company)s
			and trim(bill_no) = %(bill_no)s
			and ifnull(is_return, 0) = 0
			and docstatus < 2
			and name != %(name)s
		order by docstatus desc, creation asc
		limit 1""",
		{
			"supplier": doc.get("supplier"),
			"company": doc.get("company"),
			"bill_no": bill_no,
			"name": doc.get("name") or "",
		},
		as_dict=True,
	)
	return rows[0] if rows else None


def _report(doc, other):
	state = _("submitted") if other.docstatus == 1 else _("a draft")
	link = frappe.utils.get_link_to_form("Purchase Invoice", other.name)
	frappe.throw(
		_(
			"Supplier Invoice No {0} has already been entered for {1}, on {2} ({3})."
		).format(
			frappe.bold(_clean(doc.get("bill_no"))),
			frappe.bold(doc.get("supplier_name") or doc.get("supplier")),
			link,
			state,
		)
		+ "<br><br>"
		+ _(
			"If this is the same bill, open that invoice instead of entering it again. "
			"If the supplier really issued two bills with this number, correct the number here."
		),
		title=_("Duplicate Supplier Invoice"),
		exc=DuplicateSupplierInvoice,
	)


def _changed(doc):
	"""True for a new document, or when the supplier, number or company changed."""
	before = doc.get_doc_before_save() if doc.get("name") else None
	if not before:
		return True
	return any(doc.get(f) != before.get(f) for f in KEY_FIELDS)


def validate(doc, method=None):
	"""Purchase Invoice validate.

	Only on a new document or a changed number, so that an unrelated edit to an
	invoice booked before this rule existed is never refused.
	"""
	if _changed(doc):
		check(doc)


def check(doc, method=None):
	"""Purchase Invoice before_submit, and the check itself. Always runs: a
	duplicate must not reach the ledger, however long it sat in draft."""
	other = find_duplicate(doc)
	if other:
		_report(doc, other)
