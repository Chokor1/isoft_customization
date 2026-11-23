"""Stock Reconciliation: change only the cost of serialized stock, even back-dated.

ERPNext v13 posts a serialized row as "every serial no out, then back in at the new
rate", and refuses it when any of those serial nos moved after the posting date ("has
been used in the future transactions, cancel them first"). That blocks a year-end
write-down of serialized items that were transferred or sold since.

A row that keeps the same quantity and the same serial nos is a cost-only change, so
when its serial nos have later movements it is posted here as a value-only entry,
exactly as ERPNext posts a non-serialized row: one ledger entry with no serial nos that
sets the warehouse value at that date. Nothing moves, so the serial nos' own history,
warehouse and status stay as they are. Each serial no's cost (Serial No.purchase_rate,
which v13 uses as the value of every later issue of that serial no) becomes the new
rate, the same as the standard path does; the stock repost then re-costs the later
transfers and sales. Cancel posts the reverse and puts the serial nos' cost back.

Rows that change qty or serial nos, and cost-only rows with no later movements, keep
ERPNext's standard path.
"""
import frappe
from frappe import _
from frappe.utils import flt

from erpnext.stock.doctype.serial_no.serial_no import get_serial_nos
from erpnext.stock.utils import get_stock_balance


def _timestamp(doc):
	return "{0} {1}".format(doc.posting_date, doc.posting_time or "00:00:00")


def _serial_items(doc):
	codes = list({row.item_code for row in doc.items if row.item_code})
	if not codes:
		return {}
	rows = frappe.get_all(
		"Item", filters={"name": ("in", codes)}, fields=["name", "has_serial_no", "has_batch_no"]
	)
	return {r.name: r for r in rows if r.has_serial_no and not r.has_batch_no}


def _moved_later(doc, item_code, serial_nos):
	"""Serial nos of this list with a ledger entry after the reconciliation's date."""
	wanted = set(serial_nos)
	moved = set()
	for sle in frappe.db.sql(
		"""select serial_no from `tabStock Ledger Entry`
		where item_code = %s and is_cancelled = 0 and voucher_no != %s
			and ifnull(serial_no, '') != ''
			and timestamp(posting_date, posting_time) > timestamp(%s, %s)""",
		(item_code, doc.name, doc.posting_date, doc.posting_time or "00:00:00"),
		as_dict=True,
	):
		moved.update(wanted.intersection(get_serial_nos(sle.serial_no)))
		if moved == wanted:
			break
	return moved


def value_only_rows(doc):
	"""Rows posted value-only on submit (see module docstring)."""
	items = _serial_items(doc)
	if not items:
		return []
	seen = {}
	for row in doc.items:
		key = (row.item_code, row.warehouse)
		seen[key] = seen.get(key, 0) + 1

	out = []
	for row in doc.items:
		if row.item_code not in items or row.batch_no or seen[(row.item_code, row.warehouse)] > 1:
			continue
		serial_nos = get_serial_nos(row.serial_no)
		qty = flt(row.qty)
		if not serial_nos or qty <= 0 or len(serial_nos) != qty or flt(row.current_qty) != qty:
			continue
		if set(serial_nos) != set(get_serial_nos(row.current_serial_no)):
			continue
		# what the ledger says was there at that moment, not what the form fetched
		ledger_qty, _rate, ledger_serials = get_stock_balance(
			row.item_code, row.warehouse, doc.posting_date, doc.posting_time,
			with_valuation_rate=True, with_serial_no=True,
		)
		if isinstance(ledger_serials, (list, tuple)):
			ledger_serials = "\n".join(ledger_serials)
		if flt(ledger_qty) != qty or set(get_serial_nos(ledger_serials or "")) != set(serial_nos):
			continue
		if not _moved_later(doc, row.item_code, serial_nos):
			continue  # nothing blocks the standard path
		out.append(row)
	return out


def post_value_only(doc, rows):
	sl_entries = []
	for row in rows:
		sle = doc.get_sle_for_items(row)
		sle.serial_no = ""
		sl_entries.append(sle)
	# via_landed_cost_voucher: the entry has no serial nos, so the per-serial-no checks
	# (which would ask for them) are skipped — the same flag a Landed Cost Voucher uses
	# to re-post serialized purchases.
	doc.make_sl_entries(sl_entries, via_landed_cost_voucher=True)
	for row in rows:
		doc.update_valuation_rate_for_serial_nos(row, get_serial_nos(row.serial_no))
		frappe.msgprint(
			_(
				"Row #{0}: only the cost of {1} changed and its serial nos moved after this date, so the new cost was posted without moving them. Later movements are re-costed by the stock repost."
			).format(row.idx, frappe.bold(row.item_code)),
			alert=True,
			indicator="blue",
		)


def posted_value_only_rows(doc):
	"""Rows of this reconciliation whose ledger entries carry no serial nos."""
	items = _serial_items(doc)
	if not items:
		return []
	by_row = {}
	for sle in frappe.get_all(
		"Stock Ledger Entry",
		filters={"voucher_type": doc.doctype, "voucher_no": doc.name},
		fields=["voucher_detail_no", "serial_no"],
	):
		by_row.setdefault(sle.voucher_detail_no, []).append(sle.serial_no)
	return [
		row
		for row in doc.items
		if row.item_code in items and by_row.get(row.name) and not any(by_row[row.name])
	]


def _cost_before(doc, serial_no):
	rate = frappe.db.sql(
		"""select incoming_rate from `tabStock Ledger Entry`
		where is_cancelled = 0 and actual_qty > 0 and voucher_no != %s
			and (serial_no = %s or serial_no like %s or serial_no like %s or serial_no like %s)
			and timestamp(posting_date, posting_time) <= timestamp(%s, %s)
		order by posting_date desc, posting_time desc, creation desc limit 1""",
		(
			doc.name,
			serial_no,
			serial_no + "\n%",
			"%\n" + serial_no,
			"%\n" + serial_no + "\n%",
			doc.posting_date,
			doc.posting_time or "00:00:00",
		),
	)
	return flt(rate[0][0]) if rate else None


def cancel_value_only(doc, rows):
	sl_entries = []
	for row in rows:
		sle = doc.get_sle_for_items(row)
		sle.serial_no = ""
		sl_entries.append(sle)
	doc.make_sl_entries(sl_entries)
	for row in rows:
		for serial_no in get_serial_nos(row.serial_no):
			current = frappe.db.get_value("Serial No", serial_no, "purchase_rate")
			if current is None or flt(current) != flt(row.valuation_rate):
				continue  # changed since by someone else: leave it
			before = _cost_before(doc, serial_no)
			if before is None:
				before = row.current_valuation_rate
			frappe.db.set_value("Serial No", serial_no, "purchase_rate", flt(before))
