// Sales discount limits, form side (server: isoft_customization/discount_limits.py).
//
// When the user's limit for a kind of item is 0%, the discount fields of those
// lines are read-only so the save never has to be refused. Limits come from
// get_form_limits once per form load (and again when the owner changes); the
// stock/service kind of each line is resolved from the item codes on the form.
//
// Per-row locking uses v13's per-row docfield copies
// (frappe.meta.get_docfield(child_dt, fieldname, cdn)); when BOTH kinds are at
// 0% the grid-level docfields are locked too, so a row typed before the item
// code is known is covered as well.

frappe.provide('isoft.discount_limits');

(function (ns) {
	const DOCTYPES = ['Quotation', 'Sales Order', 'Delivery Note', 'Sales Invoice'];
	const FIELDS = ['discount_percentage', 'discount_amount'];
	const TOL = 0.005;

	function child_dt(frm) { return frm.doc.doctype + ' Item'; }

	function exempt(frm, limits) {
		return (limits.skip_pos && cint(frm.doc.is_pos)) || (limits.skip_returns && cint(frm.doc.is_return));
	}

	function set_row_lock(frm, row, lock) {
		FIELDS.forEach(function (f) {
			const df = frappe.meta.get_docfield(child_dt(frm), f, row.name);
			if (df && !!df.read_only !== !!lock) {
				df.read_only = lock ? 1 : 0;
				const grid_row = frm.fields_dict.items && frm.fields_dict.items.grid.grid_rows_by_docname[row.name];
				if (grid_row) grid_row.refresh_field(f);
			}
		});
	}

	function set_grid_lock(frm, lock) {
		const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
		if (!grid) return;
		FIELDS.forEach(function (f) {
			const df = frappe.meta.get_docfield(child_dt(frm), f);
			if (df && !!df.read_only !== !!lock) grid.update_docfield_property(f, 'read_only', lock ? 1 : 0);
		});
	}

	ns.apply = function (frm) {
		const limits = frm.__isoft_discount_limits;
		if (!limits || !limits.applies || exempt(frm, limits)) { set_grid_lock(frm, false); (frm.doc.items || []).forEach(function (r) { set_row_lock(frm, r, false); }); return; }
		const stock_zero = flt(limits.max_stock) <= TOL, service_zero = flt(limits.max_service) <= TOL;
		set_grid_lock(frm, stock_zero && service_zero);
		(frm.doc.items || []).forEach(function (r) {
			let lock = false;
			if (r.item_code && r.item_code in limits.stock_items) {
				lock = limits.stock_items[r.item_code] ? stock_zero : service_zero;
			} else {
				lock = stock_zero && service_zero;
			}
			set_row_lock(frm, r, lock);
		});
	};

	// Loads limits (and the stock flags of any item codes not seen yet), then applies.
	ns.refresh = function (frm) {
		if (frm.doc.docstatus !== 0) return;
		const known = (frm.__isoft_discount_limits && frm.__isoft_discount_limits.stock_items) || {};
		const codes = (frm.doc.items || []).map(function (r) { return r.item_code; }).filter(function (c) { return c && !(c in known); });
		const key = (frm.doc.owner || '') + '|' + frm.doc.doctype;
		if (frm.__isoft_discount_limits && frm.__isoft_discount_limits_key === key && !codes.length) { ns.apply(frm); return; }
		frappe.call({
			method: 'isoft_customization.discount_limits.get_form_limits',
			args: { doctype: frm.doc.doctype, owner: frm.doc.__islocal ? null : frm.doc.owner, item_codes: codes },
			callback: function (r) {
				const data = r.message || { applies: false };
				data.stock_items = Object.assign({}, known, data.stock_items || {});
				frm.__isoft_discount_limits = data;
				frm.__isoft_discount_limits_key = key;
				ns.apply(frm);
			}
		});
	};

	DOCTYPES.forEach(function (dt) {
		const handlers = { refresh: ns.refresh, is_pos: ns.apply, is_return: ns.apply, items_add: function (frm) { ns.refresh(frm); } };
		frappe.ui.form.on(dt, handlers);
		frappe.ui.form.on(dt + ' Item', { item_code: function (frm) { ns.refresh(frm); } });
	});
})(isoft.discount_limits);
