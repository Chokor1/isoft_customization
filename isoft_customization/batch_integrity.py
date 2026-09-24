"""Batch <-> Item integrity guards.

ERPNext keeps two opinions about which item owns a batch and never reconciles them:

* Selling side: ``get_batch_qty`` builds the sellable batch list from ``tabStock Ledger
  Entry`` grouped by ``batch_no`` and never reads ``Batch.item``.
* Posting side: ``StockLedgerEntry.validate_item`` refuses any entry whose ``batch_no``
  is not owned by the row's ``item_code`` in ``tabBatch``.

Nothing in core stops ``Batch.item`` from being re-pointed after the batch already has
ledger movement (``Batch.validate`` only checks ``has_batch_no``). Once that happens the
old stock is still visible and sellable but can never be posted, or written off. On
ptperp.isoft.ao (2026-09-21) this surfaced inside ``on_submit`` of two POS invoices,
after ``docstatus`` had been written: the invoices ended up submitted, Paid and
AGT-registered with no Stock Ledger and no GL entries.

Three guards, all in this module, no core patched:

1. ``prevent_item_reassignment`` (Batch.validate) refuses to change ``Batch.item`` while
   uncancelled ledger entries exist under the batch for a different item. New batches
   and batches with no history are untouched. ``frappe.flags.allow_batch_item_reassignment``
   is the only bypass, for supervised console cleanup; there is deliberately no
   ``in_import`` exemption, the incident came in through Data Import.
2. ``validate_batch_belongs_to_item`` (before_submit on every stock-moving document)
   checks each batch-bearing row, including Sales Invoice / Delivery Note
   ``packed_items``, against ``Batch.item`` *before* ``docstatus`` is written, so drift
   that is already in the data fails cleanly instead of half-submitting.

   before_submit alone misses one path. saft_xml's ``auto_submit_sales_invoice_before_insert``
   (a Sales Invoice *before_save* hook) flips every non-POS invoice and every return to
   ``docstatus = 1`` during a plain save. Frappe has already chosen the save branch by
   then, so ``validate`` + ``before_save`` run, then ``on_update`` + ``on_submit``, and
   ``before_submit`` never does. ``validate_batch_on_auto_submit`` covers it: from
   before_save it arms a one-shot check on the document's ``db_insert`` / ``db_update``
   that runs only if the row is about to be written as submitted. Arming at the write
   works whichever order the two apps' before_save hooks run in.

   Why the half-submit persists at all: ERPNext's ``SalesInvoice.on_submit`` calls
   ``add_mapped_identity()``, which does ``frappe.db.commit()``, before
   ``update_stock_ledger()`` and ``make_gl_entries()``. Any exception after that point
   leaves a submitted invoice with no ledger. That is core and is not patched here.
3. ``find_batch_item_mismatches`` reports batches whose master item disagrees with the
   ledger, for manual runs or a scheduled sweep.

ERPNext 13 has no Serial and Batch Bundle: ``batch_no`` sits directly on the item row.
"""
from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.utils import flt

from isoft_customization.document_reasons import _check_before_write

# Child tables that carry batch_no, per submittable parent. Anything not listed falls
# back to "items". packed_items are what actually move stock for a Product Bundle.
BATCH_TABLES = {
	"Sales Invoice": ("items", "packed_items"),
	"Delivery Note": ("items", "packed_items"),
	"Purchase Invoice": ("items",),
	"Purchase Receipt": ("items",),
	"Stock Entry": ("items",),
	"Stock Reconciliation": ("items",),
}

REASSIGNMENT_FLAG = "allow_batch_item_reassignment"


class BatchItemReassignmentError(frappe.ValidationError):
	pass


class BatchItemMismatchError(frappe.ValidationError):
	pass


# ---------------------------------------------------------------------------
# Guard 1: Batch.validate
# ---------------------------------------------------------------------------


def get_ledger_under_other_items(batch_no, item_code):
	"""Uncancelled ledger movement recorded under ``batch_no`` for items other than
	``item_code``, one row per item: entry count and net quantity."""
	return frappe.db.sql(
		"""
		select item_code, count(*) as entries, sum(actual_qty) as qty
		from `tabStock Ledger Entry`
		where batch_no = %(batch_no)s
		  and is_cancelled = 0
		  and item_code != %(item_code)s
		group by item_code
		order by item_code
		""",
		{"batch_no": batch_no, "item_code": item_code},
		as_dict=True,
	)


def prevent_item_reassignment(doc, method=None):
	"""Batch.validate: refuse to move a batch to another item while uncancelled ledger
	entries exist under it for any item other than the new one. Net quantity does not
	matter: emptied stock still leaves entries whose documents could never be cancelled,
	because the reversing entry fails the same ownership check.

	``get_doc_before_save`` is loaded by ``run_before_save_methods`` before ``validate``
	runs and is ``None`` on insert, so a new batch passes without a separate check.
	Re-pointing towards the item the ledger already uses is allowed: that is the repair
	for drift that is already in the data.
	"""
	if frappe.flags.get(REASSIGNMENT_FLAG):
		return

	before = doc.get_doc_before_save()
	if not before or (before.item or "") == (doc.item or ""):
		return

	stranded = get_ledger_under_other_items(doc.name, doc.item)
	if not stranded:
		return

	lines = [
		_("Item {0}: {1} ledger entries, net quantity {2}").format(
			frappe.bold(row.item_code), row.entries, flt(row.qty)
		)
		for row in stranded
	]
	frappe.throw(
		_(
			"Batch {0} cannot be moved from Item {1} to Item {2}: it already has stock "
			"movement recorded under another item, which would become impossible to "
			"post or write off."
		).format(frappe.bold(doc.name), frappe.bold(before.item), frappe.bold(doc.item))
		+ "<br><br>"
		+ "<br>".join(lines)
		+ "<br><br>"
		+ _("Create a new batch for Item {0} instead, or cancel the documents behind those entries first.").format(
			frappe.bold(doc.item)
		),
		BatchItemReassignmentError,
		title=_("Batch has stock history"),
	)


# ---------------------------------------------------------------------------
# Guard 2: before_submit on stock-moving documents
# ---------------------------------------------------------------------------


# Invoices move stock only with update_stock ticked; otherwise batch_no on the row is
# informational and no ledger entry will ever be validated against it.
UPDATE_STOCK_DOCTYPES = ("Sales Invoice", "Purchase Invoice")


def get_batch_rows(doc):
	"""(table fieldname, row) for every child row carrying a batch_no that will reach
	the Stock Ledger."""
	if doc.doctype in UPDATE_STOCK_DOCTYPES and not doc.get("update_stock"):
		return []

	rows = []
	for table in BATCH_TABLES.get(doc.doctype, ("items",)):
		for row in doc.get(table) or []:
			if row.get("batch_no"):
				rows.append((table, row))
	return rows


def get_batch_owners(batch_nos):
	"""{batch_no: Batch.item} for the batches that exist."""
	if not batch_nos:
		return {}
	return dict(
		frappe.db.sql(
			"select name, item from `tabBatch` where name in %(names)s",
			{"names": tuple(batch_nos)},
		)
	)


def validate_batch_belongs_to_item(doc, method=None):
	"""before_submit: every batch on the document must be owned by the row's item.

	Runs before ``db_update`` writes ``docstatus``, so a mismatch leaves the document
	as a draft with no Stock Ledger and no GL rows, instead of the ledger throw firing
	half-way through ``on_submit``.
	"""
	rows = get_batch_rows(doc)
	if not rows:
		return

	owners = get_batch_owners({row.batch_no for _table, row in rows})
	problems = []
	for table, row in rows:
		owner = owners.get(row.batch_no)
		where = _("Row #{0}").format(row.idx)
		if table != "items":
			where = "{0} ({1})".format(where, _(frappe.unscrub(table)))
		if owner is None:
			problems.append(
				_("{0}: Batch {1} does not exist (Item {2})").format(
					where, frappe.bold(row.batch_no), frappe.bold(row.item_code)
				)
			)
		elif owner != row.item_code:
			problems.append(
				_("{0}: Batch {1} belongs to Item {2}, not to Item {3}").format(
					where, frappe.bold(row.batch_no), frappe.bold(owner), frappe.bold(row.item_code)
				)
			)

	if problems:
		frappe.throw(
			_("This document cannot be submitted: some batches are not owned by the item on the row.")
			+ "<br><br>"
			+ "<br>".join(problems)
			+ "<br><br>"
			+ _("Pick a batch that belongs to the item, or correct the Batch master before submitting."),
			BatchItemMismatchError,
			title=_("Batch does not belong to Item"),
		)


def validate_batch_on_auto_submit(doc, method=None):
	"""before_save: catch the save that saft_xml turns into a submit.

	The check itself runs from the armed db_insert / db_update, after every before_save
	hook, and only when the row is being written with docstatus 1.
	"""

	def check(d):
		if d.docstatus == 1:
			validate_batch_belongs_to_item(d)

	_check_before_write(doc, check)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


@frappe.whitelist()
def find_batch_item_mismatches():
	"""Batches whose master item disagrees with the uncancelled ledger under them.

	One row per (batch, master item, ledger item) with the net quantity and entry
	count. Fully cancelled pairs are ignored: they block nothing.
	"""
	if frappe.session.user != "Administrator" and not frappe.has_permission("Batch", "write"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	return frappe.db.sql(
		"""
		select sle.batch_no, b.item as master_item, sle.item_code as ledger_item,
		       sum(sle.actual_qty) as qty, count(*) as entries
		from `tabStock Ledger Entry` sle
		join `tabBatch` b on b.name = sle.batch_no
		where sle.is_cancelled = 0
		  and ifnull(sle.batch_no, '') != ''
		  and b.item != sle.item_code
		group by sle.batch_no, b.item, sle.item_code
		having sum(sle.actual_qty) != 0
		order by sle.batch_no
		""",
		as_dict=True,
	)
