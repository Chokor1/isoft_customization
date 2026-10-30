frappe.ui.form.on('Item Default Rules', {
	setup(frm) {
		// Only leaf records of the row's company: no group accounts, warehouses or cost centres.
		const by_company = (extra) => (doc, cdt, cdn) => {
			const row = locals[cdt][cdn] || {};
			const filters = Object.assign({ is_group: 0 }, extra || {});
			if (row.company) filters.company = row.company;
			return { filters };
		};
		frm.set_query('income_account', 'rules', by_company({ root_type: 'Income' }));
		frm.set_query('expense_account', 'rules', by_company({ root_type: 'Expense' }));
		frm.set_query('default_warehouse', 'rules', by_company());
		frm.set_query('selling_cost_center', 'rules', by_company());
		frm.set_query('item_group', 'rules', () => ({ filters: { is_group: 0 } }));
	},
	refresh(frm) {
		if (!frm.doc.enabled) return;
		frm.add_custom_button(__('Apply to existing items'), () => {
			frappe.call({ method: 'isoft_customization.item_default_rules.apply_to_existing_items', args: { dry_run: 1 }, freeze: true }).then(r => {
				const n = (r.message || {}).would_update || 0;
				if (!n) { frappe.msgprint(__('No item needs a change: every matching item already has its defaults.')); return; }
				frappe.confirm(__('{0} item(s) have an empty default that a rule would fill. Fill them now?', [n]), () => {
					frappe.call({ method: 'isoft_customization.item_default_rules.apply_to_existing_items', args: { dry_run: 0 }, freeze: true })
						.then(r2 => frappe.msgprint(__('{0} item(s) updated.', [(r2.message || {}).updated || 0])));
				});
			});
		});
	}
});
