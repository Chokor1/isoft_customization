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
    # Price List Rate mode rewrites price_list_rate and clears discount + margin.
    p = page.evaluate("""() => {
        const it = cur_frm.doc.items[0];
        const r = isoft.target_total.write_rate(it, 200, 'Price List Rate');
        isoft.target_total.recalc_silent(cur_frm);
        return {ret: r, plr: it.price_list_rate, rate: it.rate, disc: it.discount_percentage, da: it.discount_amount, mt: it.margin_type, m: it.margin_rate_or_amount, rwm: it.rate_with_margin,
                cur_gt: isoft.target_total.current(cur_frm, 'Grand Total'), gt: cur_frm.doc.grand_total, cur_nt: isoft.target_total.current(cur_frm, 'Net Total'), nt: cur_frm.doc.net_total};
    }""")
    log("plr", json.dumps(p))
    log.check(p["plr"] == 200 and p["rate"] == 200 and not p["disc"] and not p["da"] and not p["mt"] and not p["m"] and not p["rwm"], "Price List Rate mode clears discount and margin")
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
    page.evaluate("(v) => { const d = isoft.target_total._dialog; d.set_value('target', v); }", value)
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
    page.evaluate("() => { isoft.target_total._dialog.set_value('default_mode', 'Rate'); }")
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


TASKS = {"2": task2, "3": task3}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--quotation", default="PP ALV2026/7")
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
