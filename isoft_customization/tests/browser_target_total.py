"""Browser checks for the Target Total Assistant (Playwright against dev.isoft.ao).

Run from the bench root:
    env/bin/python apps/isoft_customization/isoft_customization/tests/browser_target_total.py \
        --task 2 --quotation "PP ALV2026/7"

Mints an Administrator session straight into tabSessions (no login form), drives
the desk form, and deletes the session row afterwards. Writes a full log to
--log (default: ./browser_target_total.log) because a hung Playwright script
piped through head/grep shows nothing.

NEVER saves or submits a Sales Invoice here: on dev every Sales Invoice save
reaches FE Angola / AGT. Quotations may be saved.
"""
import argparse
import json
import os
import sys
import time

BENCH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
SITE = "dev.isoft.ao"
BASE_URL = "https://dev.isoft.ao"


def mint_session():
    os.chdir(os.path.join(BENCH, "sites"))
    import frappe
    from frappe.sessions import Session

    frappe.init(site=SITE)
    frappe.connect()
    frappe.local.request = frappe._dict(cookies={}, headers={}, path="/", method="GET")
    frappe.local.request_ip = "127.0.0.1"
    frappe.local.form_dict = frappe._dict()
    s = Session(user="Administrator", resume=False, full_name="Administrator", user_type="System User")
    frappe.db.commit()
    return s.data.sid  # NOT s.sid (that is the "Guest" placeholder in v13)


def drop_session(sid):
    import frappe
    frappe.db.sql("delete from tabSessions where sid=%s", sid)
    frappe.db.commit()
    frappe.destroy()


class Log:
    def __init__(self, path):
        self.f = open(path, "w")
        self.failures = 0

    def __call__(self, *parts):
        line = " ".join(str(p) for p in parts)
        self.f.write(line + "\n")
        self.f.flush()
        print(line, flush=True)

    def check(self, cond, label, detail=""):
        self("PASS" if cond else "FAIL", label, detail)
        if not cond:
            self.failures += 1


def open_form(page, log, doctype, name):
    route = doctype.lower().replace(" ", "-")
    page.goto(f"{BASE_URL}/app/{route}/{name}", wait_until="networkidle")
    page.wait_for_function("() => window.cur_frm && cur_frm.doc && cur_frm.doc.items && cur_frm.doc.items.length", timeout=30000)
    page.wait_for_timeout(500)
    log("opened", doctype, name)


def task2(page, log, args):
    """write_rate + recalc_silent on a draft Quotation. Nothing is saved."""
    open_form(page, log, "Quotation", args.quotation)
    before = page.evaluate("() => ({rate: cur_frm.doc.items[0].rate, plr: cur_frm.doc.items[0].price_list_rate, qty: cur_frm.doc.items[0].qty, net: cur_frm.doc.net_total})")
    log("before", json.dumps(before))
    new_rate = 123.45
    after = page.evaluate("""(new_rate) => {
        const r = isoft.target_total.write_rate(cur_frm.doc.items[0], new_rate, 'Rate');
        isoft.target_total.recalc_silent(cur_frm);
        return {ret: r, rate: cur_frm.doc.items[0].rate, disc: cur_frm.doc.items[0].discount_percentage,
                net: cur_frm.doc.net_total, snap: isoft.target_total.snapshot(cur_frm).length};
    }""", new_rate)
    log("after", json.dumps(after))
    plr = before["plr"]
    exp_disc = (plr - new_rate) / plr * 100
    log.check(abs(after["disc"] - exp_disc) < 0.005, "Rate mode writes discount_percentage (field precision 2)", f"{after['disc']} vs {exp_disc}")
    log.check(after["rate"] == new_rate, "rate written")
    log.check(abs((after["net"] - before["net"]) - (new_rate - before["rate"]) * before["qty"]) < 0.011, "net_total moved by delta*qty",
              f"{after['net'] - before['net']} vs {(new_rate - before['rate']) * before['qty']}")
    log.check(after["ret"] == {"margin": False}, "no margin flag below price list rate", json.dumps(after["ret"]))
    # Rate above the price list rate must flag a margin and set margin fields.
    m = page.evaluate("""() => {
        const it = cur_frm.doc.items[0];
        const r = isoft.target_total.write_rate(it, it.price_list_rate + 10, 'Rate');
        isoft.target_total.recalc_silent(cur_frm);
        return {ret: r, margin_type: it.margin_type, m: it.margin_rate_or_amount, rwm: it.rate_with_margin, rate: it.rate, disc: it.discount_percentage};
    }""")
    log("margin", json.dumps(m))
    log.check(m["ret"] == {"margin": True} and m["margin_type"] == "Amount" and abs(m["m"] - 10) < 1e-9 and m["disc"] == 0, "Rate above price list rate -> margin Amount")
    # Price List Rate mode keeps an existing discount: the price list rate is set
    # so that rate = price_list_rate * (1 - discount%) lands on the new rate.
    p = page.evaluate("""(orig) => {
        const it = cur_frm.doc.items[0];
        it.price_list_rate = orig.plr; it.rate = orig.rate; it.margin_type = ''; it.margin_rate_or_amount = 0; it.rate_with_margin = 0;
        it.discount_percentage = 10; it.discount_amount = orig.plr * 0.1;   // an existing 10% discount
        const r = isoft.target_total.write_rate(it, 200, 'Price List Rate');
        isoft.target_total.recalc_silent(cur_frm);
        return {ret: r, plr: it.price_list_rate, rate: it.rate, disc: it.discount_percentage, da: it.discount_amount, mt: it.margin_type, m: it.margin_rate_or_amount, rwm: it.rate_with_margin,
                cur_gt: isoft.target_total.current(cur_frm, 'Grand Total'), gt: cur_frm.doc.grand_total, cur_nt: isoft.target_total.current(cur_frm, 'Net Total'), nt: cur_frm.doc.net_total};
    }""", before)
    log("plr", json.dumps(p))
    log.check(p["rate"] == 200 and p["disc"] == 10 and abs(p["plr"] - 222.22) < 0.006 and abs(p["da"] - (p["plr"] - 200)) < 0.011 and not p["mt"] and not p["m"] and not p["rwm"],
              "Price List Rate mode keeps the existing 10% discount", json.dumps(p))
    # ... and with no discount it simply rewrites the price list rate.
    p0 = page.evaluate("""() => {
        const it = cur_frm.doc.items[0];
        it.discount_percentage = 0; it.discount_amount = 0;
        const r = isoft.target_total.write_rate(it, 200, 'Price List Rate');
        isoft.target_total.recalc_silent(cur_frm);
        return {plr: it.price_list_rate, rate: it.rate, disc: it.discount_percentage, da: it.discount_amount};
    }""")
    log.check(p0["plr"] == 200 and p0["rate"] == 200 and not p0["disc"] and not p0["da"], "Price List Rate mode without a discount rewrites the price list rate", json.dumps(p0))
    # A fixed discount amount (no percentage) is kept too.
    p1 = page.evaluate("""() => {
        const it = cur_frm.doc.items[0];
        it.discount_percentage = 0; it.discount_amount = 15;
        const r = isoft.target_total.write_rate(it, 200, 'Price List Rate');
        isoft.target_total.recalc_silent(cur_frm);
        return {plr: it.price_list_rate, rate: it.rate, disc: it.discount_percentage, da: it.discount_amount};
    }""")
    log.check(p1["plr"] == 215 and p1["rate"] == 200 and p1["da"] == 15, "Price List Rate mode keeps a fixed discount amount", json.dumps(p1))
    log.check(p["cur_gt"] == p["gt"] and p["cur_nt"] == p["nt"], "current() reads the form totals")
    # restore() brings the snapshot back.
    restored = page.evaluate("""(orig) => {
        const snap = isoft.target_total.snapshot(cur_frm);
        snap[0].rate = orig.rate; snap[0].price_list_rate = orig.plr; snap[0].discount_percentage = 0; snap[0].discount_amount = 0;
        snap[0].margin_type = ''; snap[0].margin_rate_or_amount = 0; snap[0].rate_with_margin = 0;
        isoft.target_total.restore(cur_frm, snap);
        isoft.target_total.recalc_silent(cur_frm);
        return {rate: cur_frm.doc.items[0].rate, net: cur_frm.doc.net_total};
    }""", before)
    log("restored", json.dumps(restored))
    log.check(restored["rate"] == before["rate"], "restore() writes the snapshot back")


def dialog_set_target(page, value):
    page.evaluate("(v) => { isoft.target_total._dialog.tt.set_target(v); }", value)
    page.wait_for_timeout(400)


def dialog_state(page):
    return page.evaluate("""() => ({
        gt: cur_frm.doc.grand_total, nt: cur_frm.doc.net_total,
        rates: cur_frm.doc.items.map(i => i.rate),
        modes: Array.from(document.querySelectorAll('.isoft-tt-table select.tt-mode')).map(s => s.value),
        status: (document.querySelector('.isoft-tt-status') || {}).textContent,
        ok: !!document.querySelector('.isoft-tt-status.tt-ok'),
        bad: !!document.querySelector('.isoft-tt-status.tt-bad'),
        margin_rows: document.querySelectorAll('.isoft-tt-table tr.tt-margin').length,
        open: !!(isoft.target_total._dialog && isoft.target_total._dialog.$wrapper.is(':visible'))
    })""")


def task3(page, log, args):
    """Solver + dialog on a draft Quotation. Nothing is saved."""
    open_form(page, log, "Quotation", args.quotation)
    orig = dialog_state(page)
    log("orig", json.dumps(orig))
    page.evaluate("() => { isoft.target_total.open(cur_frm); }")
    page.wait_for_selector(".modal:visible .isoft-tt-table", timeout=10000)
    page.wait_for_timeout(300)
    target = round(orig["gt"] + 1000, 2)
    dialog_set_target(page, target)
    st = dialog_state(page)
    log("fit+1000", json.dumps(st))
    log.check(abs(st["gt"] - target) <= 0.005, "grand total equals target", f"{st['gt']} vs {target}")
    log.check(st["ok"], "footer shows on target")
    moved = [i for i, (a, b) in enumerate(zip(orig["rates"], st["rates"])) if a != b]
    log.check(len(moved) == len(orig["rates"]), "all free lines moved proportionally", json.dumps(moved))

    # Fix row 0: it returns to its original rate and the others absorb the difference.
    page.select_option(".isoft-tt-table tr:nth-child(1) select.tt-mode", "Fixed")
    page.wait_for_timeout(400)
    st = dialog_state(page)
    log("fixed0", json.dumps(st))
    log.check(st["rates"][0] == orig["rates"][0], "fixed row keeps its original rate", f"{st['rates'][0]} vs {orig['rates'][0]}")
    # Rows 2-4 all have qty 2: the net total can only move in 2-cent steps, so an
    # odd cent is unreachable and the panel must say so (orange "Off by ... (rounding)").
    within = round(abs(st["gt"] - target), 2) <= 0.01
    warned = page.evaluate("() => !!document.querySelector('.isoft-tt-status.tt-ok, .isoft-tt-status.tt-warn')")
    log.check(within and warned, "row 0 fixed: within one cent and status is ok/warn", f"{st['gt']} status={st['status']}")

    # Type a rate on row 1: it becomes Fixed at that rate, target still met by the rest.
    typed = round(orig["rates"][1] * 1.5, 2)
    page.fill(".isoft-tt-table tr:nth-child(2) input.tt-rate", str(typed))
    page.wait_for_timeout(500)
    st = dialog_state(page)
    log("typed1", json.dumps(st))
    log.check(st["modes"][1] == "Fixed", "typed row becomes Fixed", st["modes"][1])
    log.check(st["rates"][1] == typed, "typed rate is written", f"{st['rates'][1]} vs {typed}")
    warned = page.evaluate("() => !!document.querySelector('.isoft-tt-status.tt-ok, .isoft-tt-status.tt-warn')")
    log.check(round(abs(st["gt"] - target), 2) <= 0.01 and warned, "typed: within one cent and status is ok/warn", f"{st['gt']} status={st['status']}")

    # Changing the default mode must not touch Fixed rows.
    page.evaluate("() => { isoft.target_total._dialog.tt.set_default_mode('Rate'); }")
    page.wait_for_timeout(400)
    st = dialog_state(page)
    log.check(st["modes"][0] == "Fixed" and st["modes"][1] == "Fixed" and st["modes"][2] == "Rate", "default mode leaves Fixed rows alone", json.dumps(st["modes"]))

    # Target too low: below the fixed rows' contribution -> red reason, lines unchanged.
    dialog_set_target(page, 1)
    st = dialog_state(page)
    log("toolow", json.dumps(st))
    log.check(st["bad"] and st["status"].startswith("Target too low"), "target too low is refused", st["status"])

    # Reset restores the opening snapshot and all rows to the default mode.
    page.click(".modal:visible button:has-text('Reset')")
    page.wait_for_timeout(400)
    st = dialog_state(page)
    log("reset", json.dumps(st))
    log.check(st["rates"] == orig["rates"] and st["gt"] == orig["gt"], "Reset restores original rates and total")
    log.check(all(m == "Rate" for m in st["modes"]), "Reset puts rows back in the default mode", json.dumps(st["modes"]))

    # Cancel: close without applying -> original values, form not dirty.
    dialog_set_target(page, target)
    page.click(".modal:visible button:has-text('Cancel')")
    page.wait_for_timeout(400)
    st = dialog_state(page)
    log("cancel", json.dumps(st))
    log.check(not st["open"], "dialog closed on Cancel")
    log.check(st["rates"] == orig["rates"] and st["gt"] == orig["gt"], "Cancel restores original values")

    # Apply keeps the fitted values and marks the form dirty.
    page.evaluate("() => { isoft.target_total.open(cur_frm); }")
    page.wait_for_selector(".modal:visible .isoft-tt-table", timeout=10000)
    dialog_set_target(page, target)
    page.click(".modal:visible button:has-text('Apply')")
    page.wait_for_timeout(400)
    st = dialog_state(page)
    dirty = page.evaluate("() => cur_frm.is_dirty()")
    log("apply", json.dumps(st), "dirty", dirty)
    log.check(not st["open"] and abs(st["gt"] - target) <= 0.005 and dirty, "Apply keeps the fit and dirties the form")
    page.evaluate("() => { cur_frm.reload_doc(); }")
    page.wait_for_timeout(1000)


def make_test_quotation(source):
    """Server-side copy of a quotation with a 5% document discount; deleted by drop_test_doc."""
    import frappe
    src = frappe.get_doc("Quotation", source)
    doc = frappe.copy_doc(src)
    doc.additional_discount_percentage = 5
    doc.apply_discount_on = "Net Total"  # AGT rule on dev forbids Grand Total
    doc.insert()
    frappe.db.commit()
    return doc


def drop_test_doc(doctype, name):
    """Deletes the test document and gives its series number back when it was the last one."""
    import frappe
    from frappe.model.naming import parse_naming_series
    try:
        series = frappe.db.get_value(doctype, name, "naming_series")
        frappe.delete_doc(doctype, name, force=1)
        if series:
            prefix = parse_naming_series(series.split(".#")[0])  # "PP ALV.YYYY./" -> "PP ALV2026/"
            number = name[len(prefix):] if name.startswith(prefix) else None
            if number and number.isdigit():
                frappe.db.sql("update tabSeries set current = current - 1 where name=%s and current=%s", (prefix, int(number)))
        frappe.db.commit()
    except Exception as e:
        print("cleanup failed", doctype, name, e)


def button_present(page):
    return page.evaluate("() => !!Array.from(document.querySelectorAll('.page-actions button, .page-actions a')).find(b => b.textContent.trim() === __('Pricing Assistant') && b.offsetParent !== null)")


def task4(page, log, args):
    """Toolbar button on the three forms; real save on a test quotation; SI margin flag without saving."""
    import frappe
    q = make_test_quotation(args.quotation)
    log("test quotation", q.name, "customer", q.party_name, "item", q.items[0].item_code)
    try:
        # Button on drafts, not on submitted documents.
        open_form(page, log, "Quotation", q.name)
        log.check(button_present(page), "Pricing Assistant button on draft Quotation")
        for dt, name in (("Delivery Note", args.delivery_note), ("Sales Invoice", args.sales_invoice)):
            if not name:
                log("skip submitted", dt)
                continue
            open_form(page, log, dt, name)
            log.check(not button_present(page), f"no button on submitted {dt}")
        if args.delivery_note_draft:
            open_form(page, log, "Delivery Note", args.delivery_note_draft)
            log.check(button_present(page), "Pricing Assistant button on draft Delivery Note")

        # Spec test 1: Grand Total fit, saved for real, persisted after reload.
        open_form(page, log, "Quotation", q.name)
        orig = dialog_state(page)
        page.click(".page-actions button:has-text('Pricing Assistant')")
        page.wait_for_selector(".modal:visible .isoft-tt-table", timeout=10000)
        target = 500000.0
        dialog_set_target(page, target)
        st = dialog_state(page)
        log("fit", json.dumps(st))
        log.check(abs(st["gt"] - target) <= 0.005 and st["ok"], "quotation fitted to 500 000,00 grand total", f"{st['gt']} {st['status']}")
        page.click(".modal:visible button:has-text('Apply')")
        page.wait_for_timeout(300)
        page.evaluate("() => { cur_frm.save(); }")
        page.wait_for_function("() => !cur_frm.is_dirty() && cur_frm.doc.__unsaved !== 1", timeout=30000)
        page.wait_for_timeout(500)
        page.reload(wait_until="networkidle")
        page.wait_for_function("() => window.cur_frm && cur_frm.doc && cur_frm.doc.items && cur_frm.doc.items.length", timeout=30000)
        gt = page.evaluate("() => cur_frm.doc.grand_total")
        db_gt = frappe.db.get_value("Quotation", q.name, "grand_total")
        log.check(abs(gt - target) <= 0.005 and abs(db_gt - target) <= 0.005, "saved quotation keeps the target after reload", f"form {gt} db {db_gt}")

        # Spec test 2: Net Total target with the 5% document discount in force.
        page.click(".page-actions button:has-text('Pricing Assistant')")
        page.wait_for_selector(".modal:visible .isoft-tt-table", timeout=10000)
        page.evaluate("() => { isoft.target_total._dialog.tt.set_kind('Net Total'); }")
        page.wait_for_timeout(300)
        nt_target = 400000.0
        dialog_set_target(page, nt_target)
        st = dialog_state(page)
        log("net fit", json.dumps(st))
        disc = page.evaluate("() => cur_frm.doc.additional_discount_percentage")
        log.check(disc == 5 and abs(st["nt"] - nt_target) <= 0.005 and st["ok"], "net total target met with 5% document discount", f"{st['nt']} {st['status']}")
        page.click(".modal:visible button:has-text('Cancel')")
        page.wait_for_timeout(300)
        st = dialog_state(page)
        log.check(abs(st["gt"] - target) <= 0.005, "Cancel keeps the saved values", f"{st['gt']}")

        # Spec test 3: new Sales Invoice, never saved. Rate mode above price list rate -> margin flag.
        page.goto(f"{BASE_URL}/app/sales-invoice/new", wait_until="networkidle")
        page.wait_for_function("() => window.cur_frm && cur_frm.doc && cur_frm.doc.doctype === 'Sales Invoice'", timeout=30000)
        page.evaluate("(c) => cur_frm.set_value('customer', c)", q.party_name)
        page.wait_for_timeout(1500)
        # The new form opens with one blank row: drop it, then add the priced item.
        page.evaluate("(code) => { frappe.model.clear_table(cur_frm.doc, 'items'); const r = cur_frm.add_child('items', {qty: 1}); frappe.model.set_value(r.doctype, r.name, 'item_code', code); }", q.items[0].item_code)
        page.wait_for_function("() => cur_frm.doc.items.length && cur_frm.doc.items[0].price_list_rate > 0 && cur_frm.doc.grand_total > 0", timeout=30000)
        page.evaluate("() => { cur_frm.refresh(); }")
        page.wait_for_timeout(500)
        log.check(button_present(page), "Pricing Assistant button on new Sales Invoice")
        page.click(".page-actions button:has-text('Pricing Assistant')")
        page.wait_for_selector(".modal:visible .isoft-tt-table", timeout=10000)
        page.evaluate("() => { isoft.target_total._dialog.tt.set_default_mode('Rate'); }")
        page.wait_for_timeout(300)
        gt0 = page.evaluate("() => cur_frm.doc.grand_total")
        dialog_set_target(page, round(gt0 * 1.2, 2))
        st = dialog_state(page)
        log("si fit", json.dumps(st))
        log.check(st["margin_rows"] >= 1, "Rate mode above price list rate flags a margin row", str(st["margin_rows"]))
        page.click(".modal:visible button:has-text('Cancel')")
        page.wait_for_timeout(300)
        gt1 = page.evaluate("() => cur_frm.doc.grand_total")
        log.check(gt1 == gt0, "Cancel restores the invoice total", f"{gt1} vs {gt0}")
        log.check(page.evaluate("() => cur_frm.doc.__islocal === 1"), "sales invoice was never saved")
    finally:
        drop_test_doc("Quotation", q.name)
        log("deleted test quotation", q.name, "exists:", bool(frappe.db.exists("Quotation", q.name)))


def task5(page, log, args):
    """Review fixes: credit notes (negative qty) fit in the right direction; a
    debounced refit never runs after Cancel. Nothing is saved."""
    import frappe
    q = frappe.get_doc("Quotation", args.quotation)
    # Credit note: new Sales Invoice with is_return and a negative-qty line, never saved.
    page.goto(f"{BASE_URL}/app/sales-invoice/new", wait_until="networkidle")
    page.wait_for_function("() => window.cur_frm && cur_frm.doc && cur_frm.doc.doctype === 'Sales Invoice'", timeout=30000)
    page.evaluate("(c) => cur_frm.set_value('customer', c)", q.party_name)
    page.wait_for_timeout(1500)
    page.evaluate("() => cur_frm.set_value('is_return', 1)")
    page.wait_for_timeout(500)
    page.evaluate("(code) => { frappe.model.clear_table(cur_frm.doc, 'items'); const r = cur_frm.add_child('items', {qty: -2}); frappe.model.set_value(r.doctype, r.name, 'item_code', code); }", q.items[0].item_code)
    page.wait_for_function("() => cur_frm.doc.items.length && cur_frm.doc.items[0].price_list_rate > 0 && cur_frm.doc.grand_total < 0", timeout=30000)
    page.evaluate("() => { cur_frm.refresh(); }")
    page.wait_for_timeout(500)
    gt0 = page.evaluate("() => cur_frm.doc.grand_total")
    page.click(".page-actions button:has-text('Pricing Assistant')")
    page.wait_for_selector(".modal:visible .isoft-tt-table", timeout=10000)
    page.wait_for_timeout(300)
    st = dialog_state(page)
    log("return open", json.dumps(st))
    log.check(st["ok"], "credit note: opening target (current total) is accepted", st["status"])
    target = round(gt0 - 1000, 2)
    dialog_set_target(page, target)
    st = dialog_state(page)
    log("return fit", json.dumps(st))
    # Single line with qty -2: 2-cent steps, so an odd cent may only be reachable within 0,01 (warning).
    warned = page.evaluate("() => !!document.querySelector('.isoft-tt-status.tt-ok, .isoft-tt-status.tt-warn')")
    log.check(round(abs(st["gt"] - target), 2) <= 0.01 and warned, "credit note fitted to a more negative target", f"{st['gt']} vs {target} {st['status']}")
    dialog_set_target(page, 500)
    st = dialog_state(page)
    log.check(st["bad"] and st["status"].startswith("Target too high"), "credit note: positive target refused as too high", st["status"])
    page.click(".modal:visible button:has-text('Cancel')")
    page.wait_for_timeout(300)
    log.check(page.evaluate("() => cur_frm.doc.grand_total") == gt0, "credit note: Cancel restores total")
    log.check(page.evaluate("() => cur_frm.doc.__islocal === 1"), "credit note was never saved")

    # Debounce race: type a rate and hide the dialog in the same tick; the pending refit must not run.
    open_form(page, log, "Quotation", args.quotation)
    orig = dialog_state(page)
    page.click(".page-actions button:has-text('Pricing Assistant')")
    page.wait_for_selector(".modal:visible .isoft-tt-table", timeout=10000)
    page.wait_for_timeout(300)
    page.evaluate("""() => {
        const inp = document.querySelector('.modal.show .isoft-tt-table tr:nth-child(2) input.tt-rate');
        inp.value = '1';
        inp.dispatchEvent(new Event('input', {bubbles: true}));
        isoft.target_total._dialog.hide();
    }""")
    page.wait_for_timeout(600)
    st = dialog_state(page)
    log("race", json.dumps(st))
    log.check(st["rates"] == orig["rates"] and st["gt"] == orig["gt"], "no refit after Cancel within the debounce window", f"{st['rates']} vs {orig['rates']}")


TASKS = {"2": task2, "3": task3, "4": task4, "5": task5}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--quotation", default="PP ALV2026/7")
    ap.add_argument("--delivery-note", default="GR SPL2026/10", help="a submitted Delivery Note")
    ap.add_argument("--delivery-note-draft", default="GR 2026/359", help="a draft Delivery Note with items")
    ap.add_argument("--sales-invoice", default="FR FR3726S1246N/102", help="a submitted Sales Invoice")
    ap.add_argument("--log", default="browser_target_total.log")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    log = Log(args.log)
    sid = mint_session()
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=not args.headed)
            ctx = browser.new_context(ignore_https_errors=True, viewport={"width": 1400, "height": 900})
            ctx.add_cookies([{"name": "sid", "value": sid, "domain": "dev.isoft.ao", "path": "/"}])
            page = ctx.new_page()
            page.on("console", lambda m: log("console", m.type, m.text) if m.type in ("error", "warning") else None)
            page.on("pageerror", lambda e: log("pageerror", e))
            for t in args.task.split(","):
                log("=== task", t)
                try:
                    TASKS[t](page, log, args)
                except Exception as e:  # keep going, record it
                    log("FAIL exception in task", t, repr(e))
                    log.failures += 1
            browser.close()
    finally:
        drop_session(sid)
    log("failures:", log.failures)
    sys.exit(1 if log.failures else 0)


if __name__ == "__main__":
    main()
