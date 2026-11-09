// Multi-buy (Buy X get Y at d%) pricing rules on Quotation / Sales Order / Delivery Note /
// Sales Invoice forms: shows, while the user edits, what the server engine will apply on
// save (isoft_customization/multi_buy.py `preview`). The server result on save is the
// authority; this only keeps the form honest in the meantime.
frappe.provide("isoft.multi_buy");

(function () {
	const ns = isoft.multi_buy;
	const DOCTYPES = ["Quotation", "Sales Order", "Delivery Note", "Sales Invoice"];

	ns.signature = function (frm) {
		const d = frm.doc;
		return JSON.stringify([d.customer || d.party_name, d.company, d.selling_price_list, d.currency, d.ignore_pricing_rule,
			d.set_warehouse, d.transaction_date || d.posting_date, (d.items || []).map((i) => [i.item_code, flt(i.qty), i.uom,
				flt(i.conversion_factor), flt(i.price_list_rate), flt(i.discount_percentage), flt(i.rate), i.warehouse])]);
	};

	ns.schedule = function (frm) {
		if (ns.none || !frm.doc || frm.doc.docstatus !== 0 || frm.doc.is_return) return;
		clearTimeout(frm.__isoft_mb_t);
		frm.__isoft_mb_t = setTimeout(() => ns.refresh(frm), 500);
	};

	ns.refresh = function (frm) {
		const items = (frm.doc.items || []).filter((i) => i.item_code);
		if (!items.length || frappe.request.ajax_count) {
			if (items.length) ns.schedule(frm); // ERPNext is still filling the rows
			ns.indicator(frm);
			return;
		}
		const sig = ns.signature(frm);
		if (sig === frm.__isoft_mb_sig) return;
		const seq = (frm.__isoft_mb_seq = (frm.__isoft_mb_seq || 0) + 1);
		const codes = (frm.doc.items || []).map((i) => i.item_code);
		frappe.call({
			method: "isoft_customization.multi_buy.preview",
			args: { doc: JSON.stringify(frm.doc) },
			callback: (r) => {
				const m = r && r.message;
				if (!m || seq !== frm.__isoft_mb_seq) return;
				if (m.none) { ns.none = true; return; }
				ns.apply(frm, m, codes);
				frm.__isoft_mb_sig = ns.signature(frm);
			},
		});
	};

	ns.apply = function (frm, m, codes) {
		let changed = false;
		(m.rows || []).forEach((row, i) => {
			const item = (frm.doc.items || [])[i];
			if (!item || item.item_code !== codes[i]) return;
			if (!row.isoft_multibuy_rule && !item.isoft_multibuy_rule) return;
			if (item.isoft_multibuy_rule === (row.isoft_multibuy_rule || null) && flt(item.rate) === flt(row.rate)
				&& flt(item.discount_percentage) === flt(row.discount_percentage)) return;
			// straight onto the row: set_value would run ERPNext's rate/discount triggers, which
			// turn a rate change into a margin (rejected by the AGT)
			Object.assign(item, {
				isoft_multibuy_rule: row.isoft_multibuy_rule || null, isoft_multibuy_units: row.isoft_multibuy_units || 0,
				isoft_multibuy_pct: row.isoft_multibuy_pct || 0, discount_percentage: flt(row.discount_percentage),
				discount_amount: flt(row.discount_amount), rate: flt(row.rate), margin_type: "", margin_rate_or_amount: 0,
				rate_with_margin: 0, pricing_rules: row.pricing_rules || "",
			});
			changed = true;
		});
		ns.discount = flt(m.multibuy_discount);
		if (changed) {
			frm.dirty();
			frm.cscript && frm.cscript.calculate_taxes_and_totals && frm.cscript.calculate_taxes_and_totals();
			frm.refresh_field("items");
		}
		ns.indicator(frm);
	};

	ns.indicator = function (frm) {
		const $w = $(frm.layout && frm.layout.wrapper);
		if (!$w.length) return;
		let $ind = $w.find(".isoft-mb-indicator");
		const rows = (frm.doc.items || []).filter((i) => i.isoft_multibuy_rule && flt(i.isoft_multibuy_units) > 0);
		if (!rows.length) { $ind.remove(); return; }
		const amount = rows.reduce((a, i) => a + (flt(i.price_list_rate) - flt(i.rate)) * flt(i.qty), 0);
		const units = rows.reduce((a, i) => a + flt(i.isoft_multibuy_units), 0);
		if (!$ind.length) $ind = $('<div class="isoft-mb-indicator alert alert-success small" style="margin: 0 0 10px"></div>').prependTo($w);
		$ind.html(`<i class="fa fa-tags"></i> ${__("Multi-buy")}: −${format_currency(amount, frm.doc.currency)} · ${__("{0} discounted unit(s)", [units])}`);
	};

	const parent_events = {
		refresh: (frm) => { frm.__isoft_mb_sig = null; ns.indicator(frm); ns.schedule(frm); },
		customer: ns.schedule, party_name: ns.schedule, selling_price_list: ns.schedule, ignore_pricing_rule: ns.schedule,
		set_warehouse: ns.schedule, company: ns.schedule, transaction_date: ns.schedule, posting_date: ns.schedule,
		items_remove: ns.schedule, items_add: ns.schedule,
	};
	const row_events = {};
	["item_code", "qty", "uom", "conversion_factor", "price_list_rate", "discount_percentage", "discount_amount", "rate", "warehouse"]
		.forEach((f) => { row_events[f] = (frm) => ns.schedule(frm); });
	DOCTYPES.forEach((dt) => {
		frappe.ui.form.on(dt, parent_events);
		frappe.ui.form.on(dt + " Item", row_events);
	});
})();
