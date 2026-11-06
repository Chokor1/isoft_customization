"""Barcode UOM on scan (isoft_customization/barcode_uom.py + public/js/barcode_uom_scan.js,
and POS Awesome's ItemsSelector.trigger_onscan). Nothing is saved or submitted.

    env/bin/python apps/isoft_customization/isoft_customization/tests/scan_barcode_uom_check.py [server] [si] [pos]

Data on dev.isoft.ao: PAP-A4 barcodes 5602024006119 (Box, 5 PCS) and 5602024006102 (PCS);
MSE-LOG-M185 barcode 5099206012141 has no UOM; Test-05-11-2026 barcodes 1691828500002 (TESTE-B,
priced 2000) and 1691828500005 (TESTE-E, priced 5000).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import browser_target_total as h  # noqa: E402

failures = 0
BOX, PCS, PLAIN, TB, TE = "5602024006119", "5602024006102", "5099206012141", "1691828500002", "1691828500005"


def check(cond, label, detail=""):
    global failures
    print("PASS" if cond else "FAIL", label, detail, flush=True)
    if not cond:
        failures += 1


def server():
    import frappe
    method = "erpnext.selling.page.point_of_sale.point_of_sale.search_for_serial_or_batch_or_barcode_number"
    target = (frappe.get_hooks("override_whitelisted_methods") or {}).get(method)
    check(bool(target), "the scan lookup is overridden by isoft_customization", str(target))
    if not target:
        return
    fn = frappe.get_attr(target[-1])
    r = fn(BOX)
    check(r.get("item_code") == "PAP-A4" and r.get("barcode") == BOX and r.get("uom") == "Box", "Box barcode returns its UOM", json.dumps(r))
    r = fn(PCS)
    check(r.get("uom") == "PCS", "PCS barcode returns PCS", json.dumps(r))
    r = fn(PLAIN)
    check(r.get("item_code") == "MSE-LOG-M185" and not r.get("uom"), "barcode without UOM: same answer as before, no uom", json.dumps(r))
    serial = frappe.db.get_value("Serial No", {}, ["name", "item_code"], as_dict=True)
    if serial:
        r = fn(serial.name)
        check(r.get("serial_no") == serial.name and "uom" not in r, "serial number lookup unchanged", json.dumps(r))
    r = fn("__no_such_code__")
    check(r == {}, "unknown code still returns an empty answer", json.dumps(r))


def si(page):
    import frappe
    customer = frappe.db.get_value("Customer", {"disabled": 0}, "name")
    navs = []
    page.on("framenavigated", lambda f: navs.append(f.url) if f == page.main_frame else None)
    page.goto(f"{h.BASE_URL}/app", wait_until="networkidle")
    page.wait_for_timeout(4000)
    page.goto(f"{h.BASE_URL}/app/sales-invoice/new", wait_until="networkidle")
    page.wait_for_function("() => window.cur_frm && cur_frm.doc.doctype === 'Sales Invoice' && cur_frm.doc.__islocal", timeout=30000)
    page.wait_for_timeout(2000)
    page.evaluate("(c) => { cur_frm.set_value('customer', c); }", customer)
    page.wait_for_timeout(3000)
    page.wait_for_function("() => window.cur_frm && cur_frm.doc.doctype === 'Sales Invoice'", timeout=30000)
    page.evaluate("() => { frappe.model.clear_table(cur_frm.doc, 'items'); cur_frm.refresh_field('items'); }")

    def scan(code):
        page.evaluate("(c) => { cur_frm.set_value('scan_barcode', c); }", code)
        page.wait_for_timeout(1200)
        page.wait_for_function("() => !frappe.request.ajax_count && !(cur_frm.doc.scan_barcode)", timeout=30000)
        page.wait_for_timeout(1500)
        return page.evaluate("() => cur_frm.doc.items.filter(i => i.item_code).map(i => ({item: i.item_code, uom: i.uom, cf: i.conversion_factor, qty: i.qty, plr: i.price_list_rate, barcode: i.barcode}))")

    rows = scan(BOX)
    check(len(rows) == 1 and rows[0]["uom"] == "Box" and rows[0]["cf"] == 5 and abs(rows[0]["plr"] - 20278.5) < 0.01, "SI: Box barcode -> row in Box, factor 5, Box price", json.dumps(rows))
    rows = scan(BOX)
    check(len(rows) == 1 and rows[0]["qty"] == 2 and rows[0]["uom"] == "Box", "SI: same Box barcode again -> same row, qty 2", json.dumps(rows))
    rows = scan(PCS)
    check(len(rows) == 2 and rows[1]["item"] == "PAP-A4" and rows[1]["uom"] == "PCS" and abs(rows[1]["plr"] - 4055.7) < 0.01 and rows[0]["qty"] == 2,
          "SI: PCS barcode of the same item -> its own PCS row, Box row untouched", json.dumps(rows))
    rows = scan(PLAIN)
    plain_uom = frappe.db.get_value("Item", "MSE-LOG-M185", "sales_uom") or frappe.db.get_value("Item", "MSE-LOG-M185", "stock_uom")
    check(len(rows) == 3 and rows[2]["item"] == "MSE-LOG-M185" and rows[2]["uom"] == plain_uom, "SI: barcode without UOM behaves as before", json.dumps(rows[2:]))
    rows = scan(TB)
    check(len(rows) == 4 and rows[3]["uom"] == "TESTE-B" and abs(rows[3]["plr"] - 2000) < 0.01, "SI: TESTE-B barcode -> TESTE-B price 2000", json.dumps(rows[3:]))
    check(page.evaluate("() => cur_frm.doc.__islocal === 1"), "SI: invoice never saved")
    if len(navs) > 2:
        print("note: page navigations during the SI check:", navs[2:])


FIND = """const find = (v, name) => { if (!v) return null; if (v.$options && (v.$options.name === name || v.$options._componentTag === name)) return v; for (const c of v.$children || []) { const r = find(c, name); if (r) return r; } return null; };
          let top = Array.from(document.querySelectorAll('*')).map(e => e.__vue__).find(Boolean); while (top.$parent) top = top.$parent;
          const sel = find(top, 'ItemsSelector'), inv = find(top, 'Invoice');
          const holder = (v) => { if (!v) return null; if (v.$data && Object.prototype.hasOwnProperty.call(v.$data, 'payment') && Object.prototype.hasOwnProperty.call(v.$data, 'offers')) return v; for (const c of v.$children || []) { const r = holder(c); if (r) return r; } return null; };
          const pos = holder(top);   /* Pos.vue has no name: find the component owning payment/offers */"""


def pos(page):
    page.goto(f"{h.BASE_URL}/app/posapp", wait_until="networkidle")
    page.wait_for_timeout(9000)
    page.wait_for_function("() => { " + FIND + " return sel && sel.items && sel.items.length > 0; }", timeout=60000)

    def cart():
        return page.evaluate("() => {" + FIND + " return (inv.items || []).map(i => ({item: i.item_code, uom: i.uom, plr: i.price_list_rate, qty: i.qty})); }")

    def clear():
        page.evaluate("() => {" + FIND + " inv.items.splice(0); sel.first_search = null; sel.search = null; }")
        page.wait_for_timeout(400)

    def burst(code):
        page.keyboard.type(code, delay=4)
        page.keyboard.press("Enter")
        page.wait_for_timeout(3500)

    # 1. focus in the search box (today's working path): exactly one line, no double add
    clear()
    page.evaluate("() => {" + FIND + " sel.$refs.debounce_search.$el.querySelector('input').focus(); }")
    burst(TB)
    c = cart()
    check(len(c) == 1 and c[0]["uom"] == "TESTE-B" and abs(c[0]["plr"] - 2000) < 0.01, "POS: scan in the search box adds one TESTE-B line", json.dumps(c))
    # 2. focus outside any field: the scan now adds the item with the barcode's UOM
    clear()
    page.evaluate("() => { document.activeElement && document.activeElement.blur(); }")
    burst(TE)
    c = cart()
    check(len(c) == 1 and c[0]["uom"] == "TESTE-E" and abs(c[0]["plr"] - 5000) < 0.01, "POS: scan with no field focused adds one TESTE-E line", json.dumps(c))
    # 3. focus in another field (the quantity box): nothing is added, as before
    clear()
    before_qty = page.evaluate("() => {" + FIND + " return sel.qty; }")
    page.evaluate("() => {" + FIND + " const q = sel.$refs.qty_input; const el = q && q.$el ? q.$el.querySelector('input') : null; if (el) el.focus(); return !!el; }")
    burst(TB)
    c = cart()
    check(len(c) == 0, "POS: scan while typing in another field adds nothing (unchanged)", json.dumps(c))
    page.evaluate("(q) => {" + FIND + " sel.qty = q; document.activeElement && document.activeElement.blur(); }", before_qty)
    # 4. payment screen showing: nothing is added
    clear()
    page.evaluate("() => {" + FIND + " pos.payment = true; }")
    page.wait_for_timeout(500)
    page.evaluate("() => { document.activeElement && document.activeElement.blur(); }")
    burst(TB)
    c = cart()
    page.evaluate("() => {" + FIND + " pos.payment = false; }")
    check(len(c) == 0, "POS: scan while the payment screen shows adds nothing", json.dumps(c))
    clear()

    # 5. the tester's case: barcode typed by hand (too slow to count as a scan), then the
    #    item clicked with the mouse, in the list view and in the tile view
    def type_and_click(text, view):
        clear()
        page.evaluate("(v) => {" + FIND + " sel.items_view = v; }", view)
        page.wait_for_timeout(500)
        page.evaluate("() => {" + FIND + " sel.$refs.debounce_search.$el.querySelector('input').focus(); }")
        page.keyboard.type(text, delay=80)
        page.wait_for_timeout(1200)
        target = (".pos-tiles .pos-tile" if view == "card" else ".items table tbody tr") + " >> visible=true"
        page.locator(target).first.click()
        page.wait_for_timeout(3500)
        return cart()

    for view in ("list", "card"):
        c = type_and_click(TB, view)
        check(len(c) == 1 and c[0]["uom"] == "TESTE-B" and abs(c[0]["plr"] - 2000) < 0.01,
              f"POS: barcode typed by hand + item clicked ({view} view) -> TESTE-B at 2000", json.dumps(c))
    c = type_and_click("Test-05-11-2026", "list")
    check(len(c) == 1 and c[0]["uom"] == "PCS", "POS: item found by its code + clicked keeps the default UOM", json.dumps(c))
    page.evaluate("() => {" + FIND + " sel.items_view = 'list'; }")
    clear()


def main(parts):
    sid = h.mint_session()
    try:
        if "server" in parts:
            server()
        if "si" in parts or "pos" in parts:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                b = pw.chromium.launch()
                ctx = b.new_context(ignore_https_errors=True, viewport={"width": 1500, "height": 950})
                ctx.add_cookies([{"name": "sid", "value": sid, "domain": "dev.isoft.ao", "path": "/"}])
                errors = []
                if "si" in parts:
                    page = ctx.new_page()
                    page.on("pageerror", lambda e: errors.append(str(e)[:200]))
                    si(page)
                if "pos" in parts:
                    page = ctx.new_page()
                    page.on("pageerror", lambda e: errors.append(str(e)[:200]))
                    pos(page)
                check(not errors, "no page errors", json.dumps(errors[:3]))
                b.close()
    finally:
        h.drop_session(sid)


if __name__ == "__main__":
    parts = [a for a in sys.argv[1:] if not a.startswith("-")] or ["server", "si", "pos"]
    main(parts)
    print("failures:", failures)
    sys.exit(1 if failures else 0)
