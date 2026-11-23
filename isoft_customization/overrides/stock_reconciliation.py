"""Stock Reconciliation that can change only the cost of serialized stock back-dated.

See isoft_customization.serial_cost_reconciliation.
"""
from erpnext.stock.doctype.stock_reconciliation.stock_reconciliation import StockReconciliation

from isoft_customization import serial_cost_reconciliation as scr


class IsoftStockReconciliation(StockReconciliation):
	def _without(self, rows, method):
		names = {r.name for r in rows}
		items = self.items
		self.items = [r for r in items if r.name not in names]
		try:
			if self.items:
				method()
		finally:
			self.items = items

	def update_stock_ledger(self):
		rows = scr.value_only_rows(self)
		if not rows:
			return super(IsoftStockReconciliation, self).update_stock_ledger()
		self._without(rows, super(IsoftStockReconciliation, self).update_stock_ledger)
		scr.post_value_only(self, rows)

	def make_sle_on_cancel(self):
		rows = scr.posted_value_only_rows(self)
		if not rows:
			return super(IsoftStockReconciliation, self).make_sle_on_cancel()
		self._without(rows, super(IsoftStockReconciliation, self).make_sle_on_cancel)
		scr.cancel_value_only(self, rows)
