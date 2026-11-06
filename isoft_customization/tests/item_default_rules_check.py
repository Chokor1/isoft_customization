"""Item Default Rules (isoft_customization/item_default_rules.py). Everything runs in
one transaction that is rolled back; no document is saved.
    env/bin/python apps/isoft_customization/isoft_customization/tests/item_default_rules_check.py
"""
import os, sys
os.chdir("/home/frappe/frappe-bench/sites")
import frappe
from frappe.utils import nowdate

failures = 0
def check(cond, label, detail=""):
    global failures
    print("PASS" if cond else "FAIL", label, detail); failures += (0 if cond else 1)

def main():
    frappe.init(site="dev.isoft.ao"); frappe.connect(); frappe.set_user("Administrator")
    frappe.enqueue = lambda *a, **k: None
    from isoft_customization import item_default_rules as idr
    company = "ITEC LDA"
    co_income = frappe.db.get_value("Company", company, "default_income_account")
    service_income = frappe.db.get_value("Account", {"company": company, "root_type": "Income", "is_group": 0, "name": ["!=", co_income]}, "name")
    group = frappe.db.get_value("Item Group", {"is_group": 0, "name": ["not in", ["Acessórios"]]}, "name")
    group_income = frappe.db.get_value("Account", {"company": company, "root_type": "Income", "is_group": 0, "name": ["not in", [co_income, service_income]]}, "name")
    print("company default:", co_income, "| service rule ->", service_income, "| group rule", group, "->", group_income)

    s = frappe.get_single("Item Default Rules")
    s.enabled = 1; s.apply_on_sales_invoice = 1
    s.set("rules", [
        {"company": company, "condition": "Always", "item_group": group, "income_account": group_income},
        {"company": company, "condition": "Maintain Stock is No", "income_account": service_income},
    ])
    s.save(ignore_permissions=True)

    def new_item(code, is_stock, item_group="Services" if frappe.db.exists("Item Group", "Services") else None, defaults=None):
        d = frappe.new_doc("Item")  # new_doc initialises every child table; get_doc(dict) leaves e.g. barcodes unset
        d.update({"item_code": code, "item_name": code, "item_group": item_group or frappe.db.get_value("Item Group", {"is_group": 0, "name": ["!=", group]}, "name"),
                  "stock_uom": "Nos", "is_stock_item": is_stock, "item_defaults": defaults or []})
        for df in d.meta.get_table_fields():  # ERPNext's validate reads e.g. self.barcodes
            if d.get(df.fieldname) is None:
                d.set(df.fieldname, [])
        d.flags.ignore_permissions = True
        d.run_method("validate")
        return d

    # 1. service item, no defaults: rule fills the income account for the company (row created)
    d = new_item("_IDR-SERVICE", 0)
    rows = {r.company: r.income_account for r in d.item_defaults}
    check(rows.get(company) == service_income, "service item gets the service income account", str(rows))
    # 2. stock item in a plain group: nothing matches -> no account from us
    d = new_item("_IDR-STOCK", 1)
    rows = {r.company: r.income_account for r in d.item_defaults}
    check(not rows.get(company), "stock item in a plain group is left to the company default", str(rows))
    # 3. first match wins: a stock item of the configured group gets the group account
    d = new_item("_IDR-GROUP", 1, item_group=group)
    rows = {r.company: r.income_account for r in d.item_defaults}
    check(rows.get(company) == group_income, "item group rule wins for a stock item of that group", str(rows))
    # 4. a service item of that group: first row (group) wins over the service row
    d = new_item("_IDR-GROUP-SVC", 0, item_group=group)
    rows = {r.company: r.income_account for r in d.item_defaults}
    check(rows.get(company) == group_income, "rules are evaluated top to bottom, first match wins", str(rows))
    # 5. an account set by hand is never overwritten
    d = new_item("_IDR-MANUAL", 0, defaults=[{"company": company, "income_account": co_income}])
    rows = {r.company: r.income_account for r in d.item_defaults}
    check(rows.get(company) == co_income, "hand-set account on the item is kept", str(rows))
    # 6. disabled settings do nothing
    s.enabled = 0; s.save(ignore_permissions=True)
    d = new_item("_IDR-OFF", 0)
    check(not {r.company: r.income_account for r in d.item_defaults}.get(company), "disabled: nothing filled")
    s.enabled = 1; s.save(ignore_permissions=True)

    # 6b. condition AND item group AND brand: every filter that is set must match
    other_group = frappe.db.get_value("Item Group", {"is_group": 0, "name": ["not in", [group, "Acessórios"]]}, "name")
    brand = frappe.db.get_value("Brand", {}, "name")
    s.set("rules", [{"company": company, "condition": "Maintain Stock is No", "item_group": group, "income_account": group_income}])
    s.save(ignore_permissions=True)
    acc = lambda d: {r.company: r.income_account for r in d.item_defaults}.get(company)
    check(acc(new_item("_IDR-AND-1", 0, item_group=group)) == group_income, "AND: service item of the group gets the account")
    check(not acc(new_item("_IDR-AND-2", 0, item_group=other_group)), "AND: service item of another group does not")
    check(not acc(new_item("_IDR-AND-3", 1, item_group=group)), "AND: stock item of the group does not")
    s.set("rules", [{"company": company, "condition": "Always", "item_group": group, "brand": brand, "income_account": group_income}])
    s.save(ignore_permissions=True)
    d = new_item("_IDR-AND-4", 1, item_group=group); d.brand = brand; d.set("item_defaults", []); d.run_method("validate")
    check(acc(d) == group_income, "AND: group + brand both match")
    d = new_item("_IDR-AND-5", 1, item_group=group)
    check(not acc(d), "AND: group matches but brand missing -> no match")
    # legacy rows saved with condition "Item Group" still work as "group only"
    legacy = frappe._dict(company=company, condition="Item Group", item_group=group, brand=None)
    check(idr.rule_matches(legacy, {"item_group": group, "is_stock_item": 1}) and not idr.rule_matches(legacy, {"item_group": other_group}),
          "legacy 'Item Group' condition still matches by group")
    meta = frappe.get_meta("Item Default Rule")
    check("Item Group" not in (meta.get_field("condition").options or "").split("\n"), "condition no longer offers Item Group / Brand")
    check(not meta.get_field("item_group").depends_on and not meta.get_field("brand").depends_on, "item group and brand always visible")
    s.set("rules", [
        {"company": company, "condition": "Always", "item_group": group, "income_account": group_income},
        {"company": company, "condition": "Maintain Stock is No", "income_account": service_income},
    ])
    s.save(ignore_permissions=True)

    # 7. Sales Invoice line for an EXISTING service item with no own default: company default -> service account
    svc = frappe.db.get_value("Item", {"is_stock_item": 0, "disabled": 0, "has_variants": 0, "item_group": ["!=", group]}, "name")
    frappe.db.sql("update `tabItem Default` set income_account=NULL where parent=%s", svc)
    frappe.clear_cache(doctype="Item")
    customer = frappe.db.get_value("Customer", {"disabled": 0}, "name")
    si = frappe.get_doc({"doctype": "Sales Invoice", "customer": customer, "company": company, "posting_date": nowdate(), "due_date": nowdate(),
                         "items": [{"item_code": svc, "qty": 1, "rate": 100, "income_account": co_income}]})
    si.flags.ignore_permissions = True; si._action = "save"
    idr.apply_on_transaction(si)
    check(si.items[0].income_account == service_income, "Sales Invoice: company-default income account replaced by the rule's", si.items[0].income_account)
    si.items[0].income_account = group_income
    idr.apply_on_transaction(si)
    check(si.items[0].income_account == group_income, "Sales Invoice: a non-default account on the line is kept", si.items[0].income_account)

    # 8. apply to existing items: dry run counts candidates, run fills them
    before = idr.apply_to_existing_items(dry_run=1)
    check(before.get("would_update", 0) >= 1, "dry run reports items that would be updated", str(before))
    done = idr.apply_to_existing_items(dry_run=0)
    check(done.get("updated", 0) == before["would_update"], "run updates exactly the reported items", str(done))
    check(frappe.db.get_value("Item Default", {"parent": svc, "company": company}, "income_account") == service_income, "existing service item now carries the service account")
    frappe.db.rollback()

if __name__ == "__main__":
    try: main()
    finally:
        try: frappe.db.rollback()
        except Exception: pass
    print("failures:", failures); sys.exit(1 if failures else 0)
