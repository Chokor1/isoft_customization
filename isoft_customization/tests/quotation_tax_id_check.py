"""Sales Invoice / Sales Order made from a Quotation must carry the customer's Tax Id.

Run from the bench root (nothing is saved; every change is rolled back):
    env/bin/python apps/isoft_customization/isoft_customization/tests/quotation_tax_id_check.py [--browser]

Background: Quotation.tax_id is a no_copy Custom Field (saft_xml), and frappe's
mapper skips no_copy fields on either side, so without party_tax_id.py the mapped
document arrives with tax_id None. --browser repeats the check through the desk's
own Create > Sales Invoice button on dev.isoft.ao, never saving.
"""
import os
import sys

BENCH = "/home/frappe/frappe-bench"
os.chdir(os.path.join(BENCH, "sites"))
import frappe  # noqa: E402

failures = 0


def check(cond, label, detail=""):
    global failures
    print("PASS" if cond else "FAIL", label, detail)
    if not cond:
        failures += 1


def server_checks():
    frappe.init(site="dev.isoft.ao")
    frappe.connect()
    frappe.set_user("Administrator")
    frappe.enqueue = lambda *a, **k: None  # no background jobs from any hook we trip
    from erpnext.selling.doctype.quotation.quotation import make_sales_invoice, make_sales_order

    q = frappe.db.sql("""select q.name, q.party_name, c.tax_id from tabQuotation q join tabCustomer c on c.name=q.party_name
        where q.docstatus=1 and q.quotation_to='Customer' and ifnull(c.tax_id,'')!='' order by q.modified desc limit 1""", as_dict=1)[0]
    print("quotation", q.name, "customer", q.party_name, "customer tax_id", q.tax_id)

    si = make_sales_invoice(q.name)
    check(si.tax_id == q.tax_id, "Sales Invoice mapped from Quotation carries the customer's tax_id", repr(si.tax_id))
    so = make_sales_order(q.name)
    check(so.tax_id == q.tax_id, "Sales Order mapped from Quotation carries the customer's tax_id", repr(so.tax_id))

    # A tax_id already on the document is never overwritten (invoice to a consumer with their own NIF).
    si.tax_id = "123456789"
    si.run_method("set_missing_values")
    check(si.tax_id == "123456789", "an existing tax_id on the document is kept", repr(si.tax_id))
    frappe.db.rollback()
    return q.name


def browser_check(quotation):
    sys.path.insert(0, os.path.dirname(__file__))
    import browser_target_total as h
    from playwright.sync_api import sync_playwright
    sid = h.mint_session()
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            ctx = b.new_context(ignore_https_errors=True, viewport={"width": 1400, "height": 900})
            ctx.add_cookies([{"name": "sid", "value": sid, "domain": "dev.isoft.ao", "path": "/"}])
            page = ctx.new_page()
            page.goto(f"{h.BASE_URL}/app/quotation/{quotation}", wait_until="networkidle")
            page.wait_for_function("() => window.cur_frm && cur_frm.doc && cur_frm.doc.docstatus === 1", timeout=30000)
            page.wait_for_timeout(500)
            expected = page.evaluate("() => cur_frm.doc.tax_id")
            # the desk's own button: Create > Sales Invoice (same whitelisted mapper)
            page.evaluate("() => { frappe.model.open_mapped_doc({method: 'erpnext.selling.doctype.quotation.quotation.make_sales_invoice', frm: cur_frm}); }")
            page.wait_for_function("() => window.cur_frm && cur_frm.doc.doctype === 'Sales Invoice' && cur_frm.doc.__islocal", timeout=30000)
            page.wait_for_timeout(800)
            got = page.evaluate("() => cur_frm.doc.tax_id")
            check(got == expected and bool(got), "desk Create > Sales Invoice shows the tax_id on the unsaved form", f"{got!r} vs {expected!r}")
            check(page.evaluate("() => cur_frm.doc.__islocal === 1"), "invoice was never saved")
            b.close()
    finally:
        h.drop_session(sid)


if __name__ == "__main__":
    name = server_checks()
    if "--browser" in sys.argv:
        browser_check(name)
    print("failures:", failures)
    sys.exit(1 if failures else 0)
