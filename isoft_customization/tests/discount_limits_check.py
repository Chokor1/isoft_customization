"""Sales discount limits (isoft_customization/discount_limits.py).

Run from the bench root; everything is created inside one transaction that is
rolled back at the end, and no sales document is ever inserted:
    env/bin/python apps/isoft_customization/isoft_customization/tests/discount_limits_check.py
"""
import os
import sys

os.chdir("/home/frappe/frappe-bench/sites")
import frappe  # noqa: E402
from frappe.utils import nowdate  # noqa: E402

failures = 0


def check(cond, label, detail=""):
    global failures
    print("PASS" if cond else "FAIL", label, detail)
    if not cond:
        failures += 1


def raises(fn):
    try:
        fn()
        return None
    except frappe.ValidationError as e:
        return str(e)


def main():
    frappe.init(site="dev.isoft.ao")
    frappe.connect()
    frappe.set_user("Administrator")
    from isoft_customization import discount_limits as dl

    # --- pure resolution: user row for doctype > user row All > best role row > settings default
    settings = frappe._dict(enabled=1, users_without_limit="No limit (100%)")
    user_rows = [frappe._dict(document_type="All", max_discount_stock=5, max_discount_service=20),
                 frappe._dict(document_type="Quotation", max_discount_stock=15, max_discount_service=30)]
    role_rows = [frappe._dict(role="Sales User", document_type="All", max_discount_stock=1, max_discount_service=2),
                 frappe._dict(role="Sales Manager", document_type="Sales Invoice", max_discount_stock=8, max_discount_service=40)]
    check(dl.resolve_limit("Quotation", settings, user_rows, role_rows, {"Sales User"}) == (15, 30), "user row for the doctype wins")
    check(dl.resolve_limit("Sales Invoice", settings, user_rows, role_rows, {"Sales User"}) == (5, 20), "user 'All' row is the fallback")
    check(dl.resolve_limit("Sales Invoice", settings, [], role_rows, {"Sales User", "Sales Manager"}) == (8, 40), "best role row when the user has none")
    check(dl.resolve_limit("Quotation", settings, [], role_rows, {"Sales User", "Sales Manager"}) == (1, 2), "role 'All' row when no role row for the doctype")
    check(dl.resolve_limit("Quotation", settings, [], [], set()) == (100, 100), "setting: users without a limit get 100%")
    settings.users_without_limit = "No discount allowed (0%)"
    check(dl.resolve_limit("Quotation", settings, [], [], set()) == (0, 0), "setting: users without a limit get 0%")

    # --- end to end on a real (unsaved) Quotation with a stock item and a service item
    stock_item = frappe.db.get_value("Item", {"is_stock_item": 1, "disabled": 0, "has_variants": 0}, "name")
    service_item = frappe.db.get_value("Item", {"is_stock_item": 0, "disabled": 0, "has_variants": 0}, "name")
    customer = frappe.db.get_value("Customer", {"disabled": 0}, "name")
    company = frappe.db.get_single_value("Global Defaults", "default_company")
    print("items", stock_item, service_item, "customer", customer, "company", company)

    s = frappe.get_doc("Sales Discount Limit Settings")
    s.enabled = 1
    s.users_without_limit = "No discount allowed (0%)"
    s.check_quotation = 1; s.check_sales_order = 1; s.check_delivery_note = 1; s.check_sales_invoice = 1
    s.skip_pos = 1; s.skip_returns = 1; s.allow_pricing_rule_discounts = 1
    s.limit_user = "User saving the document"
    s.set("role_limits", [])
    s.save()

    tester = "discount.limit.tester@example.com"
    if not frappe.db.exists("User", tester):
        frappe.get_doc({"doctype": "User", "email": tester, "first_name": "Discount Tester", "send_welcome_email": 0,
                        "roles": [{"role": "Sales User"}]}).insert(ignore_permissions=True)
    frappe.delete_doc("Sales Discount Limit", tester, force=1, ignore_permissions=True) if frappe.db.exists("Sales Discount Limit", tester) else None
    frappe.get_doc({"doctype": "Sales Discount Limit", "user": tester, "enabled": 1, "limits": [
        {"document_type": "Quotation", "max_discount_stock": 10, "max_discount_service": 50},
        {"document_type": "All", "max_discount_stock": 3, "max_discount_service": 3},
    ]}).insert(ignore_permissions=True)

    def make(doctype, stock_disc, service_disc, **extra):
        d = frappe.get_doc(dict({"doctype": doctype, "company": company, "customer" if doctype != "Quotation" else "party_name": customer,
                                 "quotation_to": "Customer", "transaction_date": nowdate(), "posting_date": nowdate(), "delivery_date": nowdate(),
                                 "items": [{"item_code": stock_item, "qty": 1, "price_list_rate": 1000, "rate": 1000 * (1 - stock_disc / 100.0), "discount_percentage": stock_disc},
                                           {"item_code": service_item, "qty": 1, "price_list_rate": 1000, "rate": 1000 * (1 - service_disc / 100.0), "discount_percentage": service_disc}]},
                                **extra))
        return d

    frappe.set_user(tester)
    msg = raises(lambda: dl.validate_discounts(make("Quotation", 10, 50)))
    check(msg is None, "quotation within the user's quotation limits passes", msg)
    msg = raises(lambda: dl.validate_discounts(make("Quotation", 11, 50)))
    check(msg and "10" in msg and stock_item in msg, "stock line over the quotation stock limit is blocked", msg)
    msg = raises(lambda: dl.validate_discounts(make("Quotation", 10, 51)))
    check(msg and "50" in msg and service_item in msg, "service line over the quotation service limit is blocked", msg)
    msg = raises(lambda: dl.validate_discounts(make("Sales Invoice", 4, 3)))
    check(msg and "3" in msg, "Sales Invoice falls back to the 'All' row (3%)", msg)
    msg = raises(lambda: dl.validate_discounts(make("Sales Invoice", 4, 3, is_pos=1)))
    check(msg is None, "POS invoices are skipped", msg)
    msg = raises(lambda: dl.validate_discounts(make("Sales Invoice", 4, 3, is_return=1)))
    check(msg is None, "returns are skipped", msg)
    # discount granted by a pricing rule is allowed even above the limit
    d = make("Sales Invoice", 25, 0)
    d.items[0].pricing_rules = frappe.as_json(["__fake_rule__"])
    orig = dl.pricing_rule_discount
    dl.pricing_rule_discount = lambda item: 25.0
    try:
        msg = raises(lambda: dl.validate_discounts(d))
    finally:
        dl.pricing_rule_discount = orig
    check(msg is None, "discount coming from a pricing rule is allowed", msg)
    # discount_amount without a percentage counts too
    d = make("Sales Invoice", 0, 0)
    d.items[0].discount_percentage = 0; d.items[0].discount_amount = 100; d.items[0].rate = 900
    msg = raises(lambda: dl.validate_discounts(d))
    check(msg and "10" in msg, "a discount amount is converted to a percentage", msg)
    # a user without any limit record under the 0% setting
    frappe.set_user("Administrator")
    nobody = "discount.limit.nobody@example.com"
    if not frappe.db.exists("User", nobody):
        frappe.get_doc({"doctype": "User", "email": nobody, "first_name": "Nobody", "send_welcome_email": 0, "roles": [{"role": "Sales User"}]}).insert(ignore_permissions=True)
    frappe.set_user(nobody)
    msg = raises(lambda: dl.validate_discounts(make("Quotation", 1, 0)))
    check(msg and "0" in msg, "user without a limit record gets 0% under that setting", msg)
    msg = raises(lambda: dl.validate_discounts(make("Quotation", 0, 0)))
    check(msg is None, "... and passes with no discount", msg)
    frappe.set_user("Administrator")
    s.users_without_limit = "No limit (100%)"; s.save()
    frappe.set_user(nobody)
    msg = raises(lambda: dl.validate_discounts(make("Quotation", 90, 90)))
    check(msg is None, "user without a limit record gets 100% under the other setting", msg)
    frappe.set_user("Administrator")
    s.enabled = 0; s.save()
    frappe.set_user(tester)
    msg = raises(lambda: dl.validate_discounts(make("Quotation", 99, 99)))
    check(msg is None, "disabled settings check nothing", msg)
    frappe.set_user("Administrator")
    frappe.db.rollback()


if __name__ == "__main__":
    try:
        main()
    finally:
        try:
            frappe.db.rollback()
        except Exception:
            pass
    print("failures:", failures)
    sys.exit(1 if failures else 0)
