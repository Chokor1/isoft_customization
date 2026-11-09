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
		frappe.call({
			method: "isoft_customization.multi_buy.preview",
			args: { doc: JSON.stringify(frm.doc) },
			callback: (r) => {
				const m = r && r.message;
				if (!m || seq !== frm.__isoft_mb_seq) return;
				if (m.none) { ns.none = true; return; }
				if (ns.signature(frm) !== sig) { ns.schedule(frm); return; } // edited meanwhile
				ns.apply(frm, m);
				frm.__isoft_mb_sig = ns.signature(frm);
			},
		});
	};

	// The server's answer is the line structure too: discounted units sit on their own line
	// (split off just above the line they came from) and lines that no longer need to be
	// apart are merged back. Values go straight onto the rows: set_value would run ERPNext's
	// rate/discount triggers, which turn a rate change into a margin (rejected by the AGT).
	const VALUE_FIELDS = ["qty", "stock_qty", "isoft_multibuy_rule", "isoft_multibuy_units", "isoft_multibuy_pct",
		"discount_percentage", "discount_amount", "rate", "pricing_rules", "custom_location_allocation", "custom_from_location"];
	const SKIP = ["name", "idx", "parent", "parenttype", "parentfield", "doctype", "docstatus", "creation", "modified",
		"modified_by", "owner", "__islocal", "__unsaved"];

	ns.apply = function (frm, m) {
		const cdt = frm.fields_dict.items.grid.doctype;
		const current = (frm.doc.items || []).slice();
		const by_name = {};
		current.forEach((r) => { by_name[r.name] = r; });
		const order = [];
		let changed = false;
		(m.rows || []).forEach((pr) => {
			let row = pr.name && by_name[pr.name];
			if (!row) {
				if (!pr.doc || !pr.isoft_multibuy_rule) return;
				row = frappe.model.add_child(frm.doc, cdt, "items");
				Object.keys(pr.doc).forEach((k) => { if (!SKIP.includes(k)) row[k] = pr.doc[k]; });
				changed = true;
			} else if (pr.isoft_multibuy_rule || row.isoft_multibuy_rule) {
				VALUE_FIELDS.forEach((f) => {
					if (!(f in pr) || (f.startsWith("custom_") && !(f in row))) return;
					const v = pr[f] === undefined ? null : pr[f];
					const same = typeof v === "number" ? flt(row[f]) === flt(v) : (row[f] || null) === (v || null);
					if (!same) { row[f] = v; changed = true; }
				});
				if (row.isoft_multibuy_rule && (flt(row.margin_rate_or_amount) || row.margin_type)) {
					Object.assign(row, { margin_type: "", margin_rate_or_amount: 0, rate_with_margin: 0 });
				}
			}
			order.push(row);
		});
		// merged away on the server
		current.forEach((row) => {
			if (!order.includes(row) && row.isoft_multibuy_rule && row.item_code) {
				frappe.model.clear_doc(cdt, row.name);
				changed = true;
			}
		});
		if (changed) {
			const rest = (frm.doc.items || []).filter((row) => !order.includes(row));
			frm.doc.items = order.filter((row) => locals[cdt] && locals[cdt][row.name]).concat(rest);
			frm.doc.items.forEach((row, i) => { row.idx = i + 1; });
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
