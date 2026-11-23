"""Stock repost backport: re-cost a later transfer into a warehouse already reposted.

A repost walks every item-warehouse a back-dated document touched, one after another.
When it re-costs an issue (a transfer out of warehouse A), the receiving entry in B
must be re-costed too. v13 queues B again only when that receiving entry is EARLIER
than where B's repost started; if B was among the document's own warehouses and was
reposted first, a later transfer A -> B keeps its old cost (the issue side changes,
the receipt side does not). A back-dated Stock Reconciliation of one item in several
warehouses hits this every time stock moved between them afterwards.

ERPNext fixed it later ("future dependent voucher not reposted"): a warehouse already
reposted in this run is queued again from the receiving entry. Same here, once per
receiving entry so a chain of transfers back and forth always ends.
"""
from frappe.utils import getdate

from erpnext.stock import stock_ledger

_MARK = "_isoft_dependent_repost"


def update_distinct_item_warehouses(self, dependant_sle):
	import frappe

	key = (dependant_sle.item_code, dependant_sle.warehouse)
	val = frappe._dict({"sle": dependant_sle})
	existing = self.distinct_item_warehouses.get(key)
	if existing is None:
		self.distinct_item_warehouses[key] = val
		self.new_items_found = True
		return

	if getdate(dependant_sle.posting_date) < getdate((existing.get("sle") or {}).get("posting_date")):
		val.sle_changed = True
		self.distinct_item_warehouses[key] = val
		self.new_items_found = True
		return

	if not existing.get("reposting_status"):
		return  # still to be reposted from an earlier point: that covers this entry

	done = list(existing.get("dependent_entries") or [])
	stamp = str(dependant_sle.get("timestamp") or "{0} {1}".format(dependant_sle.posting_date, dependant_sle.posting_time))
	if stamp in done:
		return
	val.sle_changed = True
	val.reposting_status = True  # repost_future_sle appends it again from this entry
	val.dependent_entries = done + [stamp]
	self.distinct_item_warehouses[key] = val
	self.new_items_found = True


def apply(*args, **kwargs):
	cls = stock_ledger.update_entries_after
	if getattr(cls, _MARK, False):
		return
	cls.update_distinct_item_warehouses = update_distinct_item_warehouses
	setattr(cls, _MARK, True)
