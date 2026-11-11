"""Throwaway data for the invoice reservation checks (always inside a transaction the check rolls back)."""
import frappe
from frappe.utils import nowdate

COMPANY = "Nova Distribuição Angola"
WH = "03 - Loja Talatona - NDA"
CUSTOMER = "Supermercado Boa Vida, Lda"
SUPPLIER = "Kwanza Office Solutions, Lda"
GROUP = "Equipamento Informático"


def check_factory():
	state = {"fails": 0}

	def check(name, cond, detail=""):
		print(("PASS" if cond else "FAIL"), name, "" if cond else str(detail)[:600], flush=True)
		state["fails"] += not cond

	return check, state


def stock_item(code, stock=True, uoms=None):
	"""uoms: [(uom, factor)] besides Nos."""
	if not frappe.db.exists("Item", code):
		frappe.get_doc({
			"doctype": "Item", "item_code": code, "item_name": code, "item_group": GROUP, "stock_uom": "Nos",
			"is_stock_item": 1 if stock else 0, "include_item_in_manufacturing": 0,
			"brand": frappe.db.get_value("Brand", {}, "name"),
			"uoms": [{"uom": "Nos", "conversion_factor": 1}] + [{"uom": u, "conversion_factor": f} for u, f in (uoms or [])],
			"taxes": [{"item_tax_template": "IVA 14% - NDA", "tax_category": "Angola IVA", "valid_from": "2026-01-01"}],
		}).insert(ignore_permissions=True)
	return code


def bundle(code, components):
	"""components: [(item_code, qty per bundle)] -> Product Bundle over a non-stock parent item."""
	stock_item(code, stock=False)
	if not frappe.db.exists("Product Bundle", code):
		frappe.get_doc({
			"doctype": "Product Bundle", "new_item_code": code,
			"items": [{"item_code": c, "qty": q} for c, q in components],
		}).insert(ignore_permissions=True)
	return code


def draft_si(lines, reserve=1, **kw):
	"""lines: [(item_code, qty)] or [(item_code, qty, extra_row_dict)] -> unsaved Sales Invoice."""
	d = frappe.get_doc(dict({
		"doctype": "Sales Invoice", "company": COMPANY, "customer": CUSTOMER, "posting_date": nowdate(),
		"due_date": nowdate(), "currency": "AKZ", "conversion_rate": 1, "selling_price_list": "Standard Selling",
		"isoft_reserve_stock": reserve,
		"items": [dict({"item_code": ln[0], "qty": ln[1], "rate": 1000, "warehouse": WH},
			**(ln[2] if len(ln) > 2 else {})) for ln in lines],
	}, **kw))
	d.set_missing_values()
	return d


def draft_pi(lines, order=1, **kw):
	d = frappe.get_doc(dict({
		"doctype": "Purchase Invoice", "company": COMPANY, "supplier": SUPPLIER, "posting_date": nowdate(),
		"due_date": nowdate(), "currency": "AKZ", "conversion_rate": 1, "buying_price_list": "Standard Buying",
		"isoft_order_stock": order, "bill_no": frappe.generate_hash(length=8),
		"items": [dict({"item_code": ln[0], "qty": ln[1], "rate": 1000, "warehouse": WH},
			**(ln[2] if len(ln) > 2 else {})) for ln in lines],
	}, **kw))
	d.set_missing_values()
	return d


def validate(doc):
	doc._action = "save"
	doc.run_method("validate")
	return doc
