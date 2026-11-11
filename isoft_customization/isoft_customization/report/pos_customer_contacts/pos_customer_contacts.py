# Copyright (c) 2026, Isoft and contributors
"""POS Customer Contacts: who bought where, and how to reach them.

One row per customer with their phone and email (primary contact, else the first linked
contact, else the Customer's own fields) and one column per POS Profile, plus "Desk / B2B"
for invoices made outside the POS. Each profile column shows the amount, the quantity or
just Yes/No. Returns are netted by default.
"""
import frappe
from frappe import _
from frappe.utils import cint, flt

SHOW = ("Amount", "Qty", "Yes/No")
CONTACT = ("Phone or Email", "Phone", "Email", "Any")
DESK = "pos__desk"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	show = filters.get("show") if filters.get("show") in SHOW else "Amount"
	profiles = _profiles(filters)
	include_desk = cint(filters.get("include_desk", 1)) and not filters.get("pos_profiles")
	sales = _sales(filters, profiles, include_desk)
	if not sales:
		return _columns(profiles, include_desk, show), []
	contacts = _contacts(list(sales))
	data = []
	want = filters.get("contact") if filters.get("contact") in CONTACT else "Phone or Email"
	for customer, s in sales.items():
		c = contacts.get(customer, {})
		phone, email = c.get("phone"), c.get("email")
		if want == "Phone or Email" and not (phone or email):
			continue
		if want == "Phone" and not phone:
			continue
		if want == "Email" and not email:
			continue
		row = {
			"customer": customer, "customer_name": s["customer_name"], "customer_group": s["customer_group"],
			"tax_id": s["tax_id"], "phone": phone, "email": email, "contact": c.get("contact"),
			"total_amount": flt(s["amount"], 2), "total_qty": flt(s["qty"], 3), "invoices": s["invoices"],
			"last_purchase": s["last"],
		}
		for key, v in s["by"].items():
			if show == "Amount":
				row[key] = flt(v["amount"], 2)
			elif show == "Qty":
				row[key] = flt(v["qty"], 3)
			else:
				row[key] = _("Yes") if v["invoices"] else ""
		data.append(row)
	data.sort(key=lambda r: -flt(r["total_amount"]))
	return _columns(profiles, include_desk, show), data, None, _chart(data, profiles, include_desk, show)


def _profiles(filters):
	chosen = filters.get("pos_profiles")
	if isinstance(chosen, str):
		chosen = [p.strip() for p in chosen.split(",") if p.strip()]
	if chosen:
		return list(chosen)
	cond = {"company": filters.company} if filters.get("company") else {}
	return frappe.get_all("POS Profile", filters=cond, pluck="name", order_by="name")


def _key(profile):
	return "pos_" + frappe.scrub(profile)


def _sales(filters, profiles, include_desk):
	conds = ["si.docstatus = 1"]
	values = {}
	if filters.get("company"):
		conds.append("si.company = %(company)s")
		values["company"] = filters.company
	if filters.get("from_date"):
		conds.append("si.posting_date >= %(from_date)s")
		values["from_date"] = filters.from_date
	if filters.get("to_date"):
		conds.append("si.posting_date <= %(to_date)s")
		values["to_date"] = filters.to_date
	if not cint(filters.get("net_of_returns", 1)):
		conds.append("si.is_return = 0")
	if filters.get("customer_group"):
		lft, rgt = frappe.db.get_value("Customer Group", filters.customer_group, ["lft", "rgt"])
		conds.append("cust.customer_group in (select name from `tabCustomer Group` where lft >= %(lft)s and rgt <= %(rgt)s)")
		values.update(lft=lft, rgt=rgt)
	where_profile = []
	if profiles:
		where_profile.append("si.pos_profile in %(profiles)s")
		values["profiles"] = tuple(profiles)
	if include_desk:
		where_profile.append("ifnull(si.pos_profile, '') = ''")
	if not where_profile:
		return {}
	conds.append("(" + " or ".join(where_profile) + ")")

	rows = frappe.db.sql("""
		select si.customer, max(si.customer_name) as customer_name, max(cust.customer_group) as customer_group,
			max(cust.tax_id) as tax_id, ifnull(si.pos_profile, '') as pos_profile,
			sum(si.base_grand_total) as amount, sum(ifnull(it.qty, 0)) as qty,
			sum(case when si.is_return = 0 then 1 else 0 end) as invoices, max(si.posting_date) as last
		from `tabSales Invoice` si
		left join `tabCustomer` cust on cust.name = si.customer
		left join (select parent, sum(qty) as qty from `tabSales Invoice Item` group by parent) it on it.parent = si.name
		where {0}
		group by si.customer, ifnull(si.pos_profile, '')
	""".format(" and ".join(conds)), values, as_dict=True)

	out = {}
	for r in rows:
		s = out.setdefault(r.customer, {"customer_name": r.customer_name, "customer_group": r.customer_group,
			"tax_id": r.tax_id, "amount": 0.0, "qty": 0.0, "invoices": 0, "last": None, "by": {}})
		key = _key(r.pos_profile) if r.pos_profile else DESK
		s["by"][key] = {"amount": flt(r.amount), "qty": flt(r.qty), "invoices": cint(r.invoices)}
		s["amount"] += flt(r.amount)
		s["qty"] += flt(r.qty)
		s["invoices"] += cint(r.invoices)
		s["last"] = max(filter(None, [s["last"], r.last])) if (s["last"] or r.last) else None
	return out


def _contacts(customers):
	"""Phone / email per customer: primary contact, else the first linked contact, else the
	Customer's own mobile_no / email_id. Within a contact: mobile, phone, then its phone list."""
	out = {}
	cust = {c.name: c for c in frappe.get_all("Customer", filters={"name": ["in", customers]},
		fields=["name", "customer_primary_contact", "mobile_no", "email_id"])}
	linked = {}
	for link in frappe.db.sql("""select dl.link_name, dl.parent from `tabDynamic Link` dl
		where dl.link_doctype = 'Customer' and dl.parenttype = 'Contact' and dl.link_name in %s
		order by dl.creation, dl.idx""", (tuple(customers),), as_dict=True):
		linked.setdefault(link.link_name, link.parent)
	contact_names = {c.customer_primary_contact or linked.get(n) for n, c in cust.items()} - {None, ""}
	contacts = {c.name: c for c in frappe.get_all("Contact", filters={"name": ["in", list(contact_names)]},
		fields=["name", "mobile_no", "phone", "email_id"])} if contact_names else {}
	phones, emails = {}, {}
	if contact_names:
		for p in frappe.db.sql("""select parent, phone from `tabContact Phone` where parent in %s
			and ifnull(phone, '') != '' order by idx""", (tuple(contact_names),), as_dict=True):
			phones.setdefault(p.parent, p.phone)
		for e in frappe.db.sql("""select parent, email_id from `tabContact Email` where parent in %s
			and ifnull(email_id, '') != '' order by idx""", (tuple(contact_names),), as_dict=True):
			emails.setdefault(e.parent, e.email_id)
	for name, c in cust.items():
		cname = c.customer_primary_contact or linked.get(name)
		k = contacts.get(cname) or {}
		phone = (k.get("mobile_no") or k.get("phone") or phones.get(cname) or c.mobile_no or "").strip()
		email = (k.get("email_id") or emails.get(cname) or c.email_id or "").strip()
		out[name] = {"contact": cname if k else None, "phone": phone or None, "email": email or None}
	return out


def _columns(profiles, include_desk, show):
	cols = [
		{"fieldname": "customer", "label": _("Customer"), "fieldtype": "Link", "options": "Customer", "width": 150},
		{"fieldname": "customer_name", "label": _("Customer Name"), "fieldtype": "Data", "width": 200},
		{"fieldname": "phone", "label": _("Phone"), "fieldtype": "Data", "width": 130},
		{"fieldname": "email", "label": _("Email"), "fieldtype": "Data", "width": 190},
		{"fieldname": "tax_id", "label": _("Tax Id"), "fieldtype": "Data", "width": 110},
		{"fieldname": "customer_group", "label": _("Customer Group"), "fieldtype": "Link", "options": "Customer Group", "width": 130},
	]
	kind = {"Amount": ("Currency", 120), "Qty": ("Float", 90), "Yes/No": ("Data", 80)}[show]
	for p in profiles:
		cols.append({"fieldname": _key(p), "label": p, "fieldtype": kind[0], "width": kind[1]})
	if include_desk:
		cols.append({"fieldname": DESK, "label": _("Desk / B2B"), "fieldtype": kind[0], "width": kind[1]})
	cols += [
		{"fieldname": "total_amount", "label": _("Total Amount"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "total_qty", "label": _("Total Qty"), "fieldtype": "Float", "width": 90},
		{"fieldname": "invoices", "label": _("Invoices"), "fieldtype": "Int", "width": 80},
		{"fieldname": "last_purchase", "label": _("Last Purchase"), "fieldtype": "Date", "width": 110},
		{"fieldname": "contact", "label": _("Contact"), "fieldtype": "Link", "options": "Contact", "width": 140},
	]
	return cols


def _chart(data, profiles, include_desk, show):
	"""Customers reached per POS Profile (how many of the listed customers bought there)."""
	keys = [(_key(p), p) for p in profiles] + ([(DESK, _("Desk / B2B"))] if include_desk else [])
	counts = [sum(1 for r in data if (r.get(k) and r.get(k) != "")) for k, _l in keys]
	if not any(counts):
		return None
	return {"data": {"labels": [l for _k, l in keys], "datasets": [{"name": _("Customers"), "values": counts}]},
		"type": "bar", "colors": ["#2563eb"]}
