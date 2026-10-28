"""Item Group parent guard (isoft_customization/item_group_guard.py): a group may
not get itself or one of its descendants as parent. Everything is rolled back.
    env/bin/python apps/isoft_customization/isoft_customization/tests/item_group_cycle_check.py
"""
import os, sys
os.chdir("/home/frappe/frappe-bench/sites")
import frappe

failures = 0
def check(cond, label, detail=""):
    global failures
    print("PASS" if cond else "FAIL", label, detail); failures += (0 if cond else 1)

def raises(fn):
    try: fn(); return None
    except frappe.ValidationError as e: return str(e)

frappe.init(site="dev.isoft.ao"); frappe.connect(); frappe.set_user("Administrator")
try:
    # Acessórios -> MALAS/MOCHILAS -> (would close the loop) Acessórios
    parent = frappe.get_doc("Item Group", "Acessórios")
    child = frappe.get_doc("Item Group", "MALAS/MOCHILAS")
    check(child.parent_item_group == "Acessórios", "fixture: MALAS/MOCHILAS is under Acessórios", child.parent_item_group)
    parent.parent_item_group = "MALAS/MOCHILAS"
    msg = raises(lambda: parent.run_method("validate"))
    check(msg and "MALAS/MOCHILAS" in msg, "parent set to its own child is refused", msg)
    parent.parent_item_group = "Acessórios"
    msg = raises(lambda: parent.run_method("validate"))
    check(bool(msg), "parent set to itself is refused", msg)
    parent.parent_item_group = "All Item Groups"
    msg = raises(lambda: parent.run_method("validate"))
    check(msg is None, "a real parent is accepted", msg)
finally:
    frappe.db.rollback()
print("failures:", failures); sys.exit(1 if failures else 0)
