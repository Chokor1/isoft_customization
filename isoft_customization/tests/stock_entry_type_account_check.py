"""Stock Entry Type default expense account (isoft_customization/stock_entry_type_accounts.py).
Rolled back; no document is saved.
    env/bin/python apps/isoft_customization/isoft_customization/tests/stock_entry_type_account_check.py
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
    from isoft_customization import stock_entry_type_accounts as seta
    company = "ITEC LDA"
    adj = frappe.get_cached_value("Company", company, "stock_adjustment_account")
    other = frappe.db.get_value("Account", {"company": company, "root_type": "Expense", "is_group": 0, "name": ["!=", adj]}, "name")
    manual = frappe.db.get_value("Account", {"company": company, "root_type": "Expense", "is_group": 0, "name": ["not in", [adj, other]]}, "name")
    print("company adjustment:", adj, "| type account:", other, "| manual:", manual)

    t = frappe.get_doc("Stock Entry Type", "Oferta")
    t.set("default_accounts", [{"company": company, "expense_account": other}])
    t.save(ignore_permissions=True)
    check(seta.get_default_expense_account("Oferta", company) == other, "lookup returns the type's account for the company")
    check(seta.get_default_expense_account("Oferta", "Nova Distribuição Angola") is None, "no account for another company")
    check(seta.get_default_expense_account("Material Issue", company) is None, "a type without accounts gives nothing")

    item = frappe.db.get_value("Item", {"is_stock_item": 1, "disabled": 0, "has_variants": 0}, "name")
    wh = frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "name")
    def entry(stype, rows):
        d = frappe.new_doc("Stock Entry")
        d.update({"company": company, "stock_entry_type": stype, "purpose": "Material Issue", "posting_date": nowdate(),
                  "items": [{"item_code": item, "qty": 1, "s_warehouse": wh, "expense_account": acc} for acc in rows]})
        return d
    d = entry("Oferta", [None, adj, manual])
    seta.apply_to_stock_entry(d)
    accs = [r.expense_account for r in d.items]
    check(accs[0] == other, "empty row takes the type's account", accs[0])
    check(accs[1] == other, "row holding the company default is replaced by the type's account", accs[1])
    check(accs[2] == manual, "a hand-picked account is kept", accs[2])
    d = entry("Material Issue", [None, adj])
    seta.apply_to_stock_entry(d)
    check([r.expense_account for r in d.items] == [None, adj], "a type without accounts changes nothing")
    frappe.db.rollback()

if __name__ == "__main__":
    try: main()
    finally:
        try: frappe.db.rollback()
        except Exception: pass
    print("failures:", failures); sys.exit(1 if failures else 0)
