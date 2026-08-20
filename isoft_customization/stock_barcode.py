"""Optional Barcode column on five ERPNext stock reports, owned by this app.

Stock Balance, Stock Analytics, Stock Projected Qty, Warehouse-wise Item Balance and
Stock Ledger each gained an "Include Barcode" filter and a Barcode column, plus a
shared get_item_barcode_map() helper in erpnext/stock/utils.py. All of it used to be
edits inside ERPNext.

There is no seam for this in Frappe v13. Reports are discovered by folder, and
frappe.desk.query_report.get_script() reads a report's .js from disk, falling back to
the Report DocType's `javascript` field only when no file exists -- so an app cannot
contribute a filter to another app's Script Report from the server at all. The filter
is therefore added client-side (see public/js/report_barcode_filter.js) and the column
here, by wrapping each report's execute().

The wrappers are additive: they call ERPNext's own execute(), then insert one column
and one value per row. Nothing of upstream's logic is duplicated, so an upgrade that
rewrites a report leaves the wrapper with less to do rather than stale. When the
filter is off -- which is its default -- every wrapper returns ERPNext's result
untouched.

INSERT_AT below is where each report placed the column originally, so the layout is
unchanged. If upstream reorders its columns the barcode simply lands elsewhere; it
does not break.
"""
import frappe

FIELD = "include_barcode"
COLUMN = {"label": "Barcode", "fieldname": "barcode", "fieldtype": "Data", "width": 120}

# report name -> (module path, index to insert the column at, how rows carry it)
#   "dict" rows take row["barcode"]; "list" rows take an insert at the same index.
REPORTS = {
	"Stock Balance": ("erpnext.stock.report.stock_balance.stock_balance", 3, "dict", "item_code"),
	"Stock Projected Qty": ("erpnext.stock.report.stock_projected_qty.stock_projected_qty", 2, "list", 0),
	"Warehouse wise Item Balance Age and Value": (
		"erpnext.stock.report.warehouse_wise_item_balance_age_and_value.warehouse_wise_item_balance_age_and_value",
		2, "list", 0,
	),
	"Stock Analytics": ("erpnext.stock.report.stock_analytics.stock_analytics", 5, "dict", "name"),
	"Stock Ledger": ("erpnext.stock.report.stock_ledger.stock_ledger", 3, "dict", "item_code"),
}

_patched = False
_originals = {}


def get_item_barcode_map(item_codes):
	"""Return {item_code: first barcode} for the given items.

	"First" is the Item Barcode row with the lowest idx, so an item with several
	barcodes always reports the same one. Moved here from erpnext/stock/utils.py.
	"""
	barcode_map = {}
	item_codes = [i for i in set(item_codes or []) if i]
	if not item_codes:
		return barcode_map

	barcodes = frappe.db.sql(
		"""
		select parent, barcode
		from `tabItem Barcode`
		where parent in ({0}) and ifnull(barcode, '') != ''
		order by idx
		""".format(", ".join(["%s"] * len(item_codes))),
		tuple(item_codes),
		as_dict=1,
	)

	for row in barcodes:
		# keep the first (lowest idx) barcode per item
		barcode_map.setdefault(row.parent, row.barcode)

	return barcode_map


def _item_code_of(row, accessor):
	try:
		return row[accessor]
	except Exception:
		return None


def _make_wrapper(report_name, original, insert_at, row_kind, accessor):
	from frappe import _

	def execute(filters=None):
		result = original(filters)
		f = filters or {}
		if not (f.get(FIELD) if hasattr(f, "get") else None):
			return result

		result = list(result)
		columns, data = result[0], result[1]
		if columns is None or data is None:
			return tuple(result)

		codes = [_item_code_of(r, accessor) for r in data]
		barcodes = get_item_barcode_map(codes)

		at = min(insert_at, len(columns))
		if row_kind == "list":
			# String-style columns ("Barcode::120") for reports that use them.
			columns.insert(at, _("Barcode") + "::120" if isinstance(columns[0], str) else dict(COLUMN, label=_("Barcode")))
			for r in data:
				if isinstance(r, list):
					r.insert(min(at, len(r)), barcodes.get(_item_code_of(r, accessor)))
		else:
			columns.insert(at, dict(COLUMN, label=_("Barcode")))
			for r in data:
				if isinstance(r, dict):
					r["barcode"] = barcodes.get(_item_code_of(r, accessor))

		# Stock Analytics builds its chart from the columns after the fixed block, so
		# the extra column shifts where the period labels start.
		if len(result) > 3 and isinstance(result[3], dict):
			chart = result[3]
			labels = chart.get("data", {}).get("labels")
			if labels is not None:
				chart["data"]["labels"] = [c.get("label") for c in columns[insert_at + 1:] if isinstance(c, dict)]

		result[0], result[1] = columns, data
		return tuple(result)

	execute.__name__ = "execute"
	execute.__doc__ = "%s with this app's optional Barcode column." % report_name
	return execute


def install_patches():
	"""Wrap each report's execute() with the barcode-aware version. Idempotent."""
	global _patched
	if _patched:
		return True

	import importlib

	installed = 0
	for report_name, (module_path, insert_at, row_kind, accessor) in REPORTS.items():
		try:
			mod = importlib.import_module(module_path)
		except Exception:
			continue
		if getattr(mod.execute, "__doc__", "") and "this app's optional Barcode column" in (mod.execute.__doc__ or ""):
			installed += 1
			continue
		_originals[report_name] = mod.execute
		mod.execute = _make_wrapper(report_name, mod.execute, insert_at, row_kind, accessor)
		installed += 1

	_patched = installed > 0
	return _patched
