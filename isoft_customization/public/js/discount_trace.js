// Recorder for the "line suddenly at 100% discount" bug (server: discount_trace.py).
//
// Read-only: it never changes a document. For every line of a selling form it keeps the
// last steps (item loads and their replies, field changes, events, which field the user
// was typing in). When a line reaches 100% discount with a price list rate while the user
// was NOT typing in that line's discount / rate / amount fields, the steps are sent once
// to the server, which stores them as an Error Log titled "Isoft discount trace".
frappe.provide("isoft.discount_trace");

(function (ns) {
	const DOCTYPES = ["Quotation", "Sales Order", "Delivery Note", "Sales Invoice"];
	const ITEM_DT = DOCTYPES.map((d) => d + " Item");
	const USER_FIELDS = ["discount_percentage", "discount_amount", "rate", "amount", "net_rate"];
	const KEEP = 60, MAX_SENT = 5;
	const logs = {};          // row name -> [steps]
	const sent = new Set();
	let t0 = Date.now(), last_input = null;

	function now() { return Date.now() - t0; }
	function snap(r) {
		return r ? { plr: r.price_list_rate, rate: r.rate, disc: r.discount_percentage, da: r.discount_amount,
			mt: r.margin_type, mra: r.margin_rate_or_amount, cf: r.conversion_factor, uom: r.uom, qty: r.qty } : null;
	}
	function where() {
		return (new Error().stack || "").split("\n").slice(3, 7)
			.map((s) => s.trim().split("/assets/").pop().replace(/\?ver=[0-9.]+/, "").slice(0, 90)).join(" < ");
	}
	function log(cdn, what, extra) {
		if (!cdn) return;
		const l = logs[cdn] || (logs[cdn] = []);
		const r = row_of(cdn);
		l.push(Object.assign({ t: now(), what: what, row: snap(r) }, extra || {}));
		if (l.length > KEEP) l.shift();
		check(cdn);
	}
	function row_of(cdn) {
		for (const dt of ITEM_DT) if (locals[dt] && locals[dt][cdn]) return locals[dt][cdn];
		return null;
	}
	function user_typed(cdn) {
		return last_input && last_input.cdn === cdn && USER_FIELDS.includes(last_input.field) && now() - last_input.t < 5000;
	}
	function check(cdn) {
		if (sent.has(cdn) || sent.size >= MAX_SENT) return;
		const r = row_of(cdn);
		if (!r || !flt(r.price_list_rate) || flt(r.discount_percentage) < 99.99 || user_typed(cdn)) return;
		sent.add(cdn);
		setTimeout(() => send(cdn), 1500);   // keep what happens right after, too
	}
	function send(cdn) {
		const r = row_of(cdn), frm = window.cur_frm;
		frappe.call({
			method: "isoft_customization.discount_trace.record",
			args: { payload: JSON.stringify({
				doctype: r && r.parenttype, docname: r && r.parent, row: r && r.idx, item_code: r && r.item_code,
				final: snap(r), last_input: last_input, items: frm && frm.doc && (frm.doc.items || []).length,
				customer: frm && frm.doc && frm.doc.customer, price_list: frm && frm.doc && frm.doc.selling_price_list,
				scan_once: !!(window.erpnext && erpnext.TransactionController && erpnext.TransactionController.prototype.__isoft_barcode_uom),
				ua: navigator.userAgent, steps: logs[cdn] || [],
			}) },
			freeze: false, async: true,
		});
	}

	// which field the user is typing in (grid inputs carry data-fieldname; the row is the grid row)
	$(document).on("keydown input", ".grid-row input, .grid-row textarea", function (e) {
		const $row = $(this).closest(".grid-row");
		last_input = { cdn: $row.attr("data-name"), field: $(this).attr("data-fieldname"), key: e.key || e.type, t: now() };
		if (last_input.cdn) log(last_input.cdn, "user:" + (e.type === "keydown" ? "key " + e.key : "input"), { field: last_input.field });
	});

	ns.install = function () {
		if (ns.installed) return;
		ns.installed = true;
		const set_value = frappe.model.set_value;
		frappe.model.set_value = function (dt, dn, field, value) {
			if (ITEM_DT.includes(dt)) {
				const out = set_value.apply(this, arguments);
				log(dn, "set_value", { field: typeof field === "object" ? JSON.stringify(field).slice(0, 160) : field + "=" + value, at: where() });
				return out;
			}
			return set_value.apply(this, arguments);
		};
		const call = frappe.call;
		frappe.call = function (opts) {
			const m = opts && (opts.method || "");
			if (opts && /get_item_details|apply_pricing_rule|apply_price_list|get_conversion_factor|get_item_price/.test(m)) {
				const short = m.split(".").pop();
				const rows = opts.child ? [opts.child.name]
					: ((opts.args && opts.args.args && opts.args.args.items) || []).map((i) => i.child_docname).filter(Boolean);
				rows.forEach((cdn) => log(cdn, "call " + short, { at: where() }));
				const cb = opts.callback;
				opts.callback = function (r) {
					const msg = r && r.message;
					rows.forEach((cdn) => {
						let reply = null;
						if (msg && opts.child) reply = { plr: msg.price_list_rate, rate: msg.rate, disc: msg.discount_percentage, da: msg.discount_amount, cf: msg.conversion_factor, uom: msg.uom };
						else if (Array.isArray(msg)) { const x = msg.find((i) => i.child_docname === cdn || i.name === cdn); reply = x ? JSON.stringify(x).slice(0, 200) : "no entry"; }
						else if (msg && msg.children) { const x = msg.children.find((i) => i.child_docname === cdn || i.name === cdn); reply = x ? JSON.stringify(x).slice(0, 200) : "no entry"; }
						log(cdn, "reply " + short, { reply: reply });
					});
					return cb && cb.apply(this, arguments);
				};
			}
			return call.apply(this, arguments);
		};
	};

	function watch_form(frm) {
		if (!frm || !frm.script_manager || frm.script_manager.__isoft_trace) return;
		frm.script_manager.__isoft_trace = true;
		const trigger = frm.script_manager.trigger.bind(frm.script_manager);
		frm.script_manager.trigger = function (event, cdt, cdn) {
			if (ITEM_DT.includes(cdt)) log(cdn, "event " + event);
			const out = trigger.apply(this, arguments);
			if (ITEM_DT.includes(cdt) && out && out.then) out.then(() => log(cdn, "event " + event + " done"));
			return out;
		};
	}

	DOCTYPES.forEach((dt) => frappe.ui.form.on(dt, {
		setup: function (frm) { ns.install(); watch_form(frm); },
		onload: function (frm) { ns.install(); watch_form(frm); },
		refresh: function (frm) { ns.install(); watch_form(frm); },
	}));
})(isoft.discount_trace);
