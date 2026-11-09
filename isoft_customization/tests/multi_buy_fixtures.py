"""Throwaway data for the multi-buy checks (always inside a transaction the check rolls back)."""
import frappe

COMPANY, PL, CURRENCY = "ITEC LDA", "Standard Selling", "AKZ"


def item_group(name, parent="All Item Groups"):
	if not frappe.db.exists("Item Group", name):
		frappe.get_doc({"doctype": "Item Group", "item_group_name": name, "parent_item_group": parent, "is_group": 0}).insert()
	return name


def brand(name="MB Test Brand"):
	if not frappe.db.exists("Brand", name):
		frappe.get_doc({"doctype": "Brand", "brand": name}).insert()
	return name


def item(code, group, price, stock_uom="Nos", uoms=None, max_discount=0, brand_name=None):
	"""uoms: [(uom, factor)]; price is per stock_uom on PL."""
	doc = frappe.get_doc({
		"doctype": "Item", "item_code": code, "item_name": code.replace("-", " "), "item_group": group, "stock_uom": stock_uom,
		"is_stock_item": 0, "include_item_in_manufacturing": 0, "max_discount": max_discount, "brand": brand_name or brand(),
		"taxes": [{"item_tax_template": "NORMAL IVA", "tax_category": "Angola IVA", "valid_from": "2020-01-01"}],
		"uoms": [{"uom": stock_uom, "conversion_factor": 1}] + [{"uom": u, "conversion_factor": f} for u, f in (uoms or [])],
	})
	doc.insert()
	frappe.get_doc({"doctype": "Item Price", "item_code": code, "price_list": PL, "price_list_rate": price, "uom": stock_uom}).insert()
	return code


def rule(title, group, priority, multibuy=True, **kw):
	base = {"doctype": "Pricing Rule", "title": title, "apply_on": "Item Group", "item_groups": [{"item_group": group}],
		"selling": 1, "company": COMPANY, "currency": CURRENCY, "applicable_for": "Customer Group",
		"customer_group": "All Customer Groups", "priority": str(priority), "rate_or_discount": "Discount Percentage"}
	if multibuy:
		base.update({"isoft_multibuy": 1, "isoft_buy_qty": 1, "isoft_get_qty": 1, "isoft_multibuy_discount": 50})
	base.update(kw)
	d = frappe.get_doc(base)
	d.flags.ignore_permissions = True
	return d
