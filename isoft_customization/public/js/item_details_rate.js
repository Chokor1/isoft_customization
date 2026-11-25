// Selling lines: an item load must never leave "rate 0" on a line that has a price.
//
// ERPNext v13's item load (erpnext.stock.get_item_details.get_item_details) always answers
// with rate 0 next to the price list rate; the form copies that onto the line and only then
// recalculates the rate from the price. Frappe runs the handlers of an event one after
// another, each waiting for the server to be quiet, so a "rate" handler queued by an
// earlier load of the SAME line (a scan, a script re-loading the lines, a re-typed item...)
// can run in that gap, read rate 0 against the price, and write a 100% discount that every
// later recalculation keeps. Seen at random on o-index Sales Invoices (2026-11).
//
// The answer's rate is filled in here - price list rate less the answer's own discount,
// which is what ERPNext computes a moment later - before the form copies it onto the line.
// With no rate-0 gap, a second load of a line is harmless whatever caused it.
frappe.provide("isoft.item_details_rate");

(function (ns) {
	const METHOD = "erpnext.stock.get_item_details.get_item_details";
	const ITEM_DOCTYPES = ["Quotation Item", "Sales Order Item", "Delivery Note Item", "Sales Invoice Item", "POS Invoice Item"];

	ns.fix_reply = function (msg) {
		if (!msg || typeof msg !== "object" || flt(msg.rate) || !(flt(msg.price_list_rate) > 0)) return;
		let rate = flt(msg.price_list_rate);
		if (flt(msg.discount_percentage)) rate = rate * (1 - flt(msg.discount_percentage) / 100);
		else if (flt(msg.discount_amount)) rate = rate - flt(msg.discount_amount);
		if (rate > 0) msg.rate = rate;
	};

	ns.install = function () {
		if (ns.installed || !frappe.call) return;
		ns.installed = true;
		const call = frappe.call;
		frappe.call = function (opts) {
			if (opts && typeof opts === "object" && opts.method === METHOD && opts.child
					&& ITEM_DOCTYPES.includes(opts.child.doctype) && !ns.off) {
				const callback = opts.callback;
				opts.callback = function (r) {
					try { ns.fix_reply(r && r.message); } catch (e) { /* never block an item load */ }
					return callback && callback.apply(this, arguments);
				};
			}
			return call.apply(this, arguments);
		};
	};

	ns.install();
	$(document).on("app_ready", ns.install);
})(isoft.item_details_rate);
