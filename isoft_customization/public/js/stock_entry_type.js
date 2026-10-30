// Stock Entry Type: the Default Difference Account table (stock_entry_type_accounts.py)
// offers only leaf accounts of the row's company.
frappe.ui.form.on('Stock Entry Type', {
	setup(frm) {
		frm.set_query('expense_account', 'default_accounts', (doc, cdt, cdn) => {
			const row = locals[cdt][cdn] || {};
			const filters = { is_group: 0 };
			if (row.company) filters.company = row.company;
			return { filters };
		});
	}
});
