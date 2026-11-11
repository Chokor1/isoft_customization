"""Browser check: POS Awesome Customer Orders shows reserving invoices read-only (Playwright, dev.isoft.ao).

Run from the bench root:
    env/bin/python apps/isoft_customization/isoft_customization/tests/browser_pos_customer_orders.py

Nothing is saved: the panel's rows are injected client-side and frappe.call is mocked for the
line lookup, so it works whatever orders the store has on dev.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import browser_target_total as h  # noqa: E402
from scan_barcode_uom_check import FIND  # noqa: E402

ROWS = [
	{"doctype": "Sales Invoice", "name": "IR-POS-INV", "customer": "C1", "customer_name": "Cliente Um",
		"transaction_date": "2026-11-01", "delivery_date": "2026-11-01", "status": "To Deliver", "grand_total": 1000,
		"currency": "AKZ", "per_delivered": 40, "po_no": "", "item_pending": 3, "item_count": 1},
	{"doctype": "Sales Order", "name": "IR-POS-SO", "customer": "C2", "customer_name": "Cliente Dois",
		"transaction_date": "2026-11-01", "delivery_date": "2099-01-01", "status": "To Deliver and Bill", "grand_total": 500,
		"currency": "AKZ", "per_delivered": 0, "po_no": "", "item_pending": 2, "item_count": 1},
]


def run(page, log):
	page.goto(h.BASE_URL + "/app/posapp", wait_until="networkidle")
	page.wait_for_function("() => { " + FIND + " return sel && sel.items && sel.items.length > 0; }", timeout=90000)
	page.evaluate("""(rows) => {
		""" + FIND + """
		const co = find(top, 'CustomerOrders');
		window.__co = co;
		co.open = true;
		co.loading = false;
		co.rows = rows;
	}""", ROWS)
	page.wait_for_timeout(800)
	state = page.evaluate("""() => {
		const rows = Array.from(document.querySelectorAll('tr.pos-co-list__row'));
		const byName = (n) => rows.find((tr) => tr.textContent.includes(n));
		const inv = byName('IR-POS-INV'), so = byName('IR-POS-SO');
		return {
			inv_chip: !!(inv && inv.querySelector('.pos-co-list__kind')),
			inv_pull: !!(inv && inv.querySelector('.pos-co-list__pull')),
			inv_state: inv ? (inv.querySelector('.pos-co-list__state') || {}).textContent : null,
			so_chip: !!(so && so.querySelector('.pos-co-list__kind')),
			so_pull: !!(so && so.querySelector('.pos-co-list__pull')),
			to_deliver: __('To deliver'),
		};
	}""")
	log.check(state["inv_chip"] and not state["inv_pull"] and (state["inv_state"] or "").strip() == state["to_deliver"],
		"pos_invoice_row_read_only", state)
	log.check(not state["so_chip"] and state["so_pull"], "pos_order_row_unchanged", state)

	args = page.evaluate("""() => new Promise((resolve) => {
		const orig = frappe.call;
		frappe.call = (opts) => {
			if (opts.method && opts.method.endsWith('get_customer_order_items')) {
				frappe.call = orig;
				opts.callback({message: [{item_code: 'X', item_name: 'X', uom: 'Nos', qty: 5, delivered_qty: 2, pending: 3, rate: 0, amount: 0}]});
				setTimeout(() => resolve(Object.assign({}, opts.args, {
					shown: document.querySelectorAll('tr.pos-co-list__items').length})), 300);
				return Promise.resolve();
			}
			return orig.apply(this, arguments);
		};
		window.__co.toggle(window.__co.rows[0]);
	})""")
	log.check(args.get("doctype") == "Sales Invoice" and args.get("sales_order") == "IR-POS-INV" and args.get("shown") == 1,
		"pos_invoice_lines_request", args)
	page.evaluate("() => { window.__co.open = false; window.__co.rows = []; }")


def main():
	log = h.Log(os.path.join(os.getcwd(), "browser_pos_customer_orders.log"))
	sid = h.mint_session()
	try:
		from playwright.sync_api import sync_playwright

		with sync_playwright() as pw:
			browser = pw.chromium.launch(headless=True)
			ctx = browser.new_context(ignore_https_errors=True, viewport={"width": 1400, "height": 900})
			ctx.add_cookies([{"name": "sid", "value": sid, "domain": "dev.isoft.ao", "path": "/"}])
			page = ctx.new_page()
			page.on("pageerror", lambda e: log("pageerror", e))
			try:
				run(page, log)
			except Exception as e:  # noqa: BLE001
				log.check(False, "no_exception", repr(e))
			browser.close()
	finally:
		h.drop_session(sid)
	log("failures:", log.failures)
	sys.exit(1 if log.failures else 0)


if __name__ == "__main__":
	main()
