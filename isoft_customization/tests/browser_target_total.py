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


TASKS = {"2": task2}


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
