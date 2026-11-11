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
		"isoft_reserve_stock": reserve, "taxes_and_charges": "IVA 14% - NDA",
		"items": [dict({"item_code": ln[0], "qty": ln[1], "rate": 1000, "warehouse": WH},
			**(ln[2] if len(ln) > 2 else {})) for ln in lines],
	}, **kw))
	d.set_missing_values()
	if not d.get("taxes"):
		d.append_taxes_from_master()
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


# ---- submitted-document fixtures written straight to the DB (no hooks, no GL, no Bin update)
_seq = [0]


def _name(prefix):
	_seq[0] += 1
	return "%s-%d-%s" % (prefix, _seq[0], frappe.generate_hash(length=4))


def insert(doctype, fields, tables):
	"""tables: {parentfield: (child_doctype, [row dicts])}. Returns {"name", parentfield: [row names]}."""
	name = _name("IRX")
	parent = frappe.get_doc(dict({"doctype": doctype, "name": name, "docstatus": 1, "company": COMPANY}, **fields))
	parent.db_insert()
	out = {"name": name}
	for parentfield, (child_dt, rows) in tables.items():
		out[parentfield] = []
		for idx, row in enumerate(rows, 1):
			r = frappe.get_doc(dict({"doctype": child_dt, "name": "%s-%s-%d" % (name, parentfield[:2], idx),
				"parent": name, "parenttype": doctype, "parentfield": parentfield, "idx": idx,
				"docstatus": fields.get("docstatus", 1)}, **row))
			r.db_insert()
			out[parentfield].append(r.name)
	return out


def line(item_code, qty, cf=1, uom="Nos", **kw):
	return dict({"item_code": item_code, "qty": qty, "conversion_factor": cf, "stock_qty": qty * cf, "uom": uom,
		"stock_uom": "Nos", "warehouse": WH}, **kw)


def si(lines, packed=None, **fields):
	f = dict({"customer": CUSTOMER, "isoft_reserve_stock": 1, "update_stock": 0, "is_pos": 0, "is_return": 0}, **fields)
	t = {"items": ("Sales Invoice Item", lines)}
	if packed:
		t["packed_items"] = ("Packed Item", packed)
	return insert("Sales Invoice", f, t)


def credit_note(orig, rows, **fields):
	"""rows: [(original line name, item_code, qty>0 returned)]"""
	f = dict({"customer": CUSTOMER, "is_return": 1, "return_against": orig["name"], "update_stock": 0}, **fields)
	return insert("Sales Invoice", f, {"items": ("Sales Invoice Item",
		[line(code, -q, sales_invoice_item=ln) for ln, code, q in rows])})


def pi(lines, **fields):
	f = dict({"supplier": SUPPLIER, "isoft_order_stock": 1, "update_stock": 0, "is_return": 0}, **fields)
	return insert("Purchase Invoice", f, {"items": ("Purchase Invoice Item", lines)})


def debit_note(orig, rows, update_stock=0):
	f = {"supplier": SUPPLIER, "is_return": 1, "return_against": orig["name"], "update_stock": update_stock}
	return insert("Purchase Invoice", f, {"items": ("Purchase Invoice Item",
		[line(code, -q, purchase_invoice_item=ln) for ln, code, q in rows])})


def receipt(rows, is_return=0, docstatus=1):
	"""rows: [(pi line name or None, item_code, received stock qty)]"""
	return insert("Purchase Receipt", {"supplier": SUPPLIER, "is_return": is_return, "docstatus": docstatus},
		{"items": ("Purchase Receipt Item", [line(code, q, received_qty=q, received_stock_qty=q,
			purchase_invoice_item=ln) for ln, code, q in rows])})


def set_line(name, doctype="Sales Invoice Item", **values):
	for k, v in values.items():
		frappe.db.set_value(doctype, name, k, v, update_modified=False)


def set_doc(name, doctype="Sales Invoice", **values):
	for k, v in values.items():
		frappe.db.set_value(doctype, name, k, v, update_modified=False)
