frappe.provide("erpnext.accounts");

erpnext.accounts.InvoiceOutstandingReconciliationController = frappe.ui.form.Controller.extend({
	onload: function () {
		const default_company = frappe.defaults.get_default('company');
		this.frm.set_value('company', default_company);
		this.frm.set_value('party_type', '');
		this.frm.set_value('party', '');
		this.frm.set_value('receivable_payable_account', '');
		this.frm.set_query('receivable_payable_account', () => {
			return {
				filters: {
					"company": this.frm.doc.company,
					"is_group": 0,
					"account_type": frappe.boot.party_account_types[this.frm.doc.party_type]
				}
			};
		});
	},

	refresh: function () {
		this.frm.disable_save();
		this.frm.set_df_property('invoices', 'cannot_add_rows', true);
		if (this.frm.doc.receivable_payable_account) {
			this.frm.add_custom_button(__('Get Outstanding Invoices'), () =>
				this.frm.trigger("get_outstanding_invoices")
			);
			this.frm.change_custom_button_type('Get Outstanding Invoices', null, 'primary');
		}

		if (this.frm.doc.invoices.length) {
			this.frm.add_custom_button(__('Reconcile'), () =>
				this.frm.trigger("reconcile")
			);
			this.frm.change_custom_button_type('Reconcile', null, 'primary');
			this.frm.change_custom_button_type('Get Outstanding Invoices', null, 'default');
		}
	},

	before_submit: function () {

		this.frm.trigger("remove_unchecked_invoices");

	},

	company: function () {
		this.frm.set_value('party', '');
		this.frm.set_value('receivable_payable_account', '');
	},

	party_type: function () {
		this.frm.set_value('party', '');
	},

	party: function () {
		this.frm.set_value('receivable_payable_account', '');
		this.frm.trigger("clear_child_tables");

		if (!this.frm.doc.receivable_payable_account && this.frm.doc.party_type && this.frm.doc.party) {
			return frappe.call({
				method: "erpnext.accounts.party.get_party_account",
				args: {
					company: this.frm.doc.company,
					party_type: this.frm.doc.party_type,
					party: this.frm.doc.party
				},
				callback: (r) => {
					if (!r.exc && r.message) {
						this.frm.set_value("receivable_payable_account", r.message);
					}
					this.frm.refresh();
				}
			});
		}

		this.frm.trigger("clear_child_tables");
	},

	receivable_payable_account: function () {
		this.frm.trigger("clear_child_tables");
		this.frm.refresh();
	},

	clear_child_tables: function () {
		this.frm.clear_table("invoices");
		this.frm.refresh_fields();
	},

	get_outstanding_invoices: function () {
		return this.frm.call({
			doc: this.frm.doc,
			method: 'get_invoice_entries',
			callback: () => {
				if (!(this.frm.doc.invoices.length)) {
					frappe.throw({ message: __("No Outstanding Invoices found for this party") });
				}
				this.frm.refresh();
			}
		});
	},

	remove_unchecked_invoices: function () {
		let rows_to_remove = [];
		this.frm.doc.invoices.forEach((invoice, idx) => {
			if (!invoice.select) { 
				rows_to_remove.push(idx);
			}
		});

		rows_to_remove.reverse().forEach((idx) => {
			this.frm.doc.invoices.splice(idx, 1);
		});

		this.frm.refresh_fields();

		frappe.msgprint(__('Unchecked invoices have been removed.'));
	},


	reconcile: function () {
		return this.frm.call({
			doc: this.frm.doc,
			method: 'reconcile',
			callback: (response) => {
				if (response.message) {
					frappe.show_alert({
						message: __('Journal Entry <a href="/app/journal-entry/{0}" target="_blank">{0}</a> created successfully.', [response.message]),
						indicator: 'green',
						timeout: 5
					});
				} else {
					frappe.msgprint(__('No journal entries were created.'));
				}

				this.frm.clear_table("invoices");
				this.frm.refresh();
			},
			error: (error) => {
				frappe.msgprint(__('An error occurred while reconciling.'));
			}
		});
	}
});
$.extend(cur_frm.cscript, new erpnext.accounts.InvoiceOutstandingReconciliationController({ frm: cur_frm }));
