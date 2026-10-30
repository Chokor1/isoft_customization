// Default Difference Account per Stock Entry Type (see stock_entry_type_accounts.py).
//
// Mirrors the before_validate hook on the form. ERPNext fills a row's Difference
// Account asynchronously after the item is chosen (get_item_details -> set_value),
// which fires the row's expense_account trigger: that is where the swap happens,
// so it always runs after ERPNext, never before. The type's account and the
// company defaults it replaces are loaded once per type + company.

frappe.provide('isoft.stock_entry_type_accounts');

(function (ns) {
	function load(frm, then) {
		if (frm.doc.docstatus !== 0 || !frm.doc.stock_entry_type || !frm.doc.company) return;
		const key = frm.doc.stock_entry_type + '|' + frm.doc.company;
		if (frm.__seta && frm.__seta.key === key) { then && then(frm.__seta); return; }
		frappe.call({
			method: 'isoft_customization.stock_entry_type_accounts.get_form_defaults',
			args: { stock_entry_type: frm.doc.stock_entry_type, company: frm.doc.company },
			callback: function (r) {
				frm.__seta = Object.assign({ key: key }, r.message || {});
				then && then(frm.__seta);
			}
		});
	}

	function should_swap(cfg, value) {
		return cfg && cfg.account && (!value || (cfg.company_defaults || []).includes(value)) && value !== cfg.account;
	}

	ns.apply_all = function (frm) {
		load(frm, function (cfg) {
			let changed = false;
			(frm.doc.items || []).forEach(function (row) {
				if (should_swap(cfg, row.expense_account)) { row.expense_account = cfg.account; changed = true; }
			});
			if (changed) frm.refresh_field('items');
		});
	};

	frappe.ui.form.on('Stock Entry', {
		stock_entry_type: function (frm) { frm.__seta = null; ns.apply_all(frm); },
		company: function (frm) { frm.__seta = null; ns.apply_all(frm); },
		refresh: function (frm) { if (frm.doc.__islocal) ns.apply_all(frm); },
		items_add: function (frm) { ns.apply_all(frm); }
	});
	frappe.ui.form.on('Stock Entry Detail', {
		expense_account: function (frm, cdt, cdn) {
			const row = locals[cdt][cdn];
			load(frm, function (cfg) {
				if (should_swap(cfg, row.expense_account)) frappe.model.set_value(cdt, cdn, 'expense_account', cfg.account);
			});
		}
	});
})(isoft.stock_entry_type_accounts);
