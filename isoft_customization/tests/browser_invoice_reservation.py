"""Browser check of the invoice reservation desk script (Playwright against dev.isoft.ao).

Run from the bench root:
    env/bin/python apps/isoft_customization/isoft_customization/tests/browser_invoice_reservation.py

Uses UNSAVED new forms only: on dev a Sales Invoice save auto-submits and reaches FE Angola / AGT.
The submitted states are simulated client-side (docstatus forced to 1, frappe.call mocked).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import browser_target_total as h  # noqa: E402

CASES = {
	"Sales Invoice": {"route": "sales-invoice", "box": "isoft_reserve_stock", "pending": "Reserving {0} units until delivered",
		"stopped": "Reservation stopped", "stop": "Stop reserving", "resume": "Resume reserving"},
	"Purchase Invoice": {"route": "purchase-invoice", "box": "isoft_order_stock", "pending": "Ordering {0} units until received",
		"stopped": "Ordering stopped", "stop": "Stop ordering", "resume": "Resume ordering"},
}

STATE_JS = """([summary, box]) => {
	const frm = cur_frm;
	window.__ir_calls = [];
	window.__ir_orig_call = window.__ir_orig_call || frappe.call;
	frappe.call = function (opts) {
		if (opts && opts.method === 'isoft_customization.invoice_reservation.pending_summary') {
			window.__ir_calls.push(opts.args);
			opts.callback && opts.callback({message: summary});
			return Promise.resolve({message: summary});
		}
		return window.__ir_orig_call.apply(this, arguments);
	};
	frm.layout.show_message();
	frm.doc.docstatus = 1;
	frm.doc[box] = 1;
	frm.doc.name = 'IR-BROWSER-TEST';
	frm.script_manager.trigger('refresh');
	return true;
}"""

READ_JS = """(labels) => {
	const msg = cur_frm.layout.message ? $(cur_frm.layout.message).text().trim() : '';
	return {
		headline: cur_frm.layout.message && $(cur_frm.layout.message).is(':visible') ? msg : '',
		// the DOM, not frm.custom_buttons: v13 remove_custom_button leaves the map entry behind
		stop: cur_frm.page.inner_toolbar.find('a[data-label="' + encodeURIComponent(__(labels.stop)) + '"]').length > 0,
		resume: cur_frm.page.inner_toolbar.find('a[data-label="' + encodeURIComponent(__(labels.resume)) + '"]').length > 0,
		calls: (window.__ir_calls || []).length,
		pending_text: __(labels.pending, ['5']),
		stopped_text: __(labels.stopped),
	};
}"""


def run(page, log):
	for doctype, c in CASES.items():
		page.goto("%s/app/%s/new" % (h.BASE_URL, c["route"]), wait_until="networkidle")
		page.wait_for_function("(dt) => window.cur_frm && cur_frm.doc.doctype === dt && cur_frm.doc.__islocal", arg=doctype, timeout=30000)
		page.wait_for_timeout(800)

		if doctype == "Sales Invoice":
			vis = page.evaluate("""() => {
				const f = cur_frm.get_field('isoft_reserve_stock');
				const before = f && f.disp_status;
				cur_frm.doc.update_stock = 1; cur_frm.refresh_fields();
				const after = f && f.disp_status;
				cur_frm.doc.update_stock = 0; cur_frm.refresh_fields();
				return [before, after, cur_frm.doc.isoft_reserve_stock];
			}""")
			log.check(vis[0] == "Write" and vis[1] == "None" and not vis[2], "draft_box_visible", vis)

		# "Source Warehouse" (set_warehouse) shows with the box, as it does with Update Stock
		wh = page.evaluate("""(box) => {
			const f = cur_frm.get_field('set_warehouse');
			cur_frm.doc[box] = 0; cur_frm.doc.update_stock = 0; cur_frm.refresh_fields();
			const off = f.disp_status;
			cur_frm.doc[box] = 1; cur_frm.refresh_fields();
			const on = f.disp_status;
			cur_frm.doc[box] = 0; cur_frm.refresh_fields();
			return [off, on];
		}""", c["box"])
		log.check(wh == ["None", "Write"], "source_warehouse_with_box " + doctype, wh)

		page.evaluate(STATE_JS, [{"enabled": 1, "stopped": 0, "pending_qty": 5}, c["box"]])
		page.wait_for_timeout(300)
		s = page.evaluate(READ_JS, c)
		log.check(s["calls"] >= 1 and s["headline"] == s["pending_text"] and s["stop"] and not s["resume"],
			"submitted_indicator pending " + doctype, s)

		page.evaluate(STATE_JS, [{"enabled": 1, "stopped": 1, "pending_qty": 5}, c["box"]])
		page.wait_for_timeout(300)
		s = page.evaluate(READ_JS, c)
		log.check(s["headline"] == s["stopped_text"] and s["resume"] and not s["stop"], "submitted_indicator stopped " + doctype, s)

		page.evaluate(STATE_JS, [{"enabled": 1, "stopped": 0, "pending_qty": 0}, c["box"]])
		page.wait_for_timeout(300)
		s = page.evaluate(READ_JS, c)
		log.check(not s["headline"] and not s["stop"] and not s["resume"], "submitted_indicator zero " + doctype, s)

		page.evaluate("() => { frappe.call = window.__ir_orig_call; cur_frm.doc.docstatus = 0; }")


def main():
	log = h.Log(os.path.join(os.getcwd(), "browser_invoice_reservation.log"))
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
