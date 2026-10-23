"""Form side of the sales discount limits: with a 0% limit the discount fields
on the lines are read-only (public/js/discount_limits.js).

Run from the bench root (changes Sales Discount Limit Settings on dev for the
duration of the run and restores them; never saves a sales document):
    env/bin/python apps/isoft_customization/isoft_customization/tests/discount_limits_ui_check.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import browser_target_total as h  # noqa: E402

failures = 0


def check(cond, label, detail=""):
    global failures
    print("PASS" if cond else "FAIL", label, detail)
    if not cond:
        failures += 1


def set_settings(**values):
    """Through the document API, like the form does, so every cache is cleared."""
    import frappe
    doc = frappe.get_single("Sales Discount Limit Settings")
    for k, v in values.items():
        if v is not None:
            doc.set(k, v)
    doc.save(ignore_permissions=True)
    frappe.db.commit()


def main():
    import frappe
    sid = h.mint_session()  # also connects frappe
    saved = frappe.db.get_singles_dict("Sales Discount Limit Settings")
    keep = {k: saved.get(k) for k in ("enabled", "users_without_limit", "limit_user", "check_sales_invoice", "check_quotation", "skip_pos")}
    keep_roles = [dict(role=r.role, document_type=r.document_type, max_discount_stock=r.max_discount_stock, max_discount_service=r.max_discount_service)
                  for r in frappe.get_single("Sales Discount Limit Settings").get("role_limits") or []]
    stock_item = frappe.db.get_value("Item", {"is_stock_item": 1, "disabled": 0, "has_variants": 0}, "name")
    service_item = frappe.db.get_value("Item", {"is_stock_item": 0, "disabled": 0, "has_variants": 0}, "name")
    customer = frappe.db.get_value("Customer", {"disabled": 0}, "name")
    admin_has_record = frappe.db.exists("Sales Discount Limit", "Administrator")
    if admin_has_record:
        frappe.db.set_value("Sales Discount Limit", "Administrator", "enabled", 0); frappe.db.commit()
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            ctx = b.new_context(ignore_https_errors=True, viewport={"width": 1400, "height": 900})
            ctx.add_cookies([{"name": "sid", "value": sid, "domain": "dev.isoft.ao", "path": "/"}])
            page = ctx.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)[:200]))

            def new_invoice():
                page.goto(f"{h.BASE_URL}/app/sales-invoice/new", wait_until="networkidle")
                page.wait_for_function("() => window.cur_frm && cur_frm.doc && cur_frm.doc.doctype === 'Sales Invoice'", timeout=30000)
                page.evaluate("(c) => cur_frm.set_value('customer', c)", customer)
                page.wait_for_timeout(1500)
                page.evaluate("(codes) => { frappe.model.clear_table(cur_frm.doc, 'items'); codes.forEach(c => { const r = cur_frm.add_child('items', {qty: 1}); frappe.model.set_value(r.doctype, r.name, 'item_code', c); }); cur_frm.refresh_field('items'); }", [stock_item, service_item])
                page.wait_for_function("() => cur_frm.doc.items.length === 2 && cur_frm.doc.items.every(i => i.price_list_rate > 0)", timeout=30000)
                page.wait_for_timeout(1500)

            def row_state():
                return page.evaluate("""() => cur_frm.doc.items.map(r => ({
                    code: r.item_code,
                    pct_ro: frappe.meta.get_docfield('Sales Invoice Item', 'discount_percentage', r.name).read_only,
                    amt_ro: frappe.meta.get_docfield('Sales Invoice Item', 'discount_amount', r.name).read_only}))""")

            # 1. Administrator without a record, fallback 0%: both discount fields read-only on every row.
            set_settings(enabled=1, users_without_limit="No discount allowed (0%)", limit_user="User saving the document", check_sales_invoice=1, skip_pos=1)
            new_invoice()
            st = row_state(); print("0% ->", json.dumps(st))
            check(all(r["pct_ro"] and r["amt_ro"] for r in st), "0% limit: discount % and amount read-only on every row", json.dumps(st))
            # a row added afterwards is read-only too
            page.evaluate("(c) => { const r = cur_frm.add_child('items', {qty: 1}); frappe.model.set_value(r.doctype, r.name, 'item_code', c); cur_frm.refresh_field('items'); }", stock_item)
            page.wait_for_function("() => cur_frm.doc.items.length === 3 && cur_frm.doc.items[2].price_list_rate > 0", timeout=30000)
            page.wait_for_timeout(1200)
            st = row_state()
            check(st[2]["pct_ro"] and st[2]["amt_ro"], "a row added later is read-only as well", json.dumps(st[2]))
            check(page.evaluate("() => cur_frm.doc.__islocal === 1"), "invoice never saved")

            # 2. Mixed: stock 0%, services 10% via a role limit -> only the stock row is locked.
            set_settings(users_without_limit="No limit (100%)")
            frappe.get_doc("Sales Discount Limit Settings").update({"role_limits": [
                {"role": "System Manager", "document_type": "Sales Invoice", "max_discount_stock": 0, "max_discount_service": 10}]}).save(ignore_permissions=True)
            frappe.db.commit(); frappe.clear_cache(doctype="Sales Discount Limit Settings")
            new_invoice()
            st = row_state(); print("mixed ->", json.dumps(st))
            check(st[0]["pct_ro"] == 1 and not st[1]["pct_ro"], "stock 0% / service 10%: only the stock row is read-only", json.dumps(st))

            # 3. 100%: nothing locked.
            frappe.get_doc("Sales Discount Limit Settings").update({"role_limits": []}).save(ignore_permissions=True)
            frappe.db.commit(); frappe.clear_cache(doctype="Sales Discount Limit Settings")
            new_invoice()
            st = row_state(); print("100% ->", json.dumps(st))
            check(not any(r["pct_ro"] or r["amt_ro"] for r in st), "100% limit: discount fields editable", json.dumps(st))
            check(not errors, "no page errors", json.dumps(errors))
            b.close()
    finally:
        doc = frappe.get_single("Sales Discount Limit Settings")
        doc.set("role_limits", keep_roles)
        doc.save(ignore_permissions=True); frappe.db.commit()
        set_settings(**keep)
        if admin_has_record:
            frappe.db.set_value("Sales Discount Limit", "Administrator", "enabled", 1); frappe.db.commit()
        h.drop_session(sid)


if __name__ == "__main__":
    main()
    print("failures:", failures)
    sys.exit(1 if failures else 0)
