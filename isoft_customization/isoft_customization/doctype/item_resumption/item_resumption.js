// Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Item Resumption', {
	refresh: function(frm) {
		if (frm.doc.journal_entry) {
			frm.add_custom_button(__('View Journal Entry'), function() {
				frappe.set_route('Form', 'Journal Entry', frm.doc.journal_entry);
			});
		}
	},

	customer: function(frm) {
		if (frm.doc.customer) {
			// Get default receivable account for the customer
			frappe.call({
				method: 'erpnext.accounts.party.get_party_account',
				args: {
					party_type: 'Customer',
					party: frm.doc.customer,
					company: frm.doc.company
				},
				callback: function(r) {
					if (r.message) {
						frm.set_value('receivable_account', r.message);
					}
				}
			});

			// Clear invoice selections and item tables when customer changes
			frm.set_value('positive_invoice', '');
			frm.set_value('negative_invoice', '');
			frm.clear_table('positive_items');
			frm.clear_table('negative_items');
			frm.refresh_fields();
		}
	},

	company: function(frm) {
		if (frm.doc.customer && frm.doc.company) {
			// Get receivable account for the company
			frappe.call({
				method: 'erpnext.accounts.party.get_party_account',
				args: {
					party_type: 'Customer',
					party: frm.doc.customer,
					company: frm.doc.company
				},
				callback: function(r) {
					if (r.message) {
						frm.set_value('receivable_account', r.message);
					}
				}
			});
		}
	},

	positive_invoice: function(frm) {
		if (frm.doc.positive_invoice) {
			// Update outstanding amount for original invoice
			frappe.db.get_value('Sales Invoice', frm.doc.positive_invoice, 'outstanding_amount')
				.then(r => {
					frm.set_value('positive_invoice_outstanding', r.message.outstanding_amount);
				});

			// Load original items (to be replaced)
			load_invoice_items(frm, frm.doc.positive_invoice, 'positive_items');
		} else {
			frm.set_value('positive_invoice_outstanding', 0);
			frm.clear_table('positive_items');
			frm.refresh_field('positive_items');
		}
	},

	negative_invoice: function(frm) {
		if (frm.doc.negative_invoice) {
			// Update outstanding amount for return/credit note
			frappe.db.get_value('Sales Invoice', frm.doc.negative_invoice, 'outstanding_amount')
				.then(r => {
					frm.set_value('negative_invoice_outstanding', r.message.outstanding_amount);
				});

			// Load replacement items
			load_invoice_items(frm, frm.doc.negative_invoice, 'negative_items');
		} else {
			frm.set_value('negative_invoice_outstanding', 0);
			frm.clear_table('negative_items');
			frm.refresh_field('negative_items');
		}
	},

	setup: function(frm) {
		// Filter for original invoice (with old items to be replaced)
		frm.set_query('positive_invoice', function() {
			if (!frm.doc.customer) {
				frappe.msgprint(__('Please select Customer first'));
				return;
			}
			return {
				filters: {
					'customer': frm.doc.customer,
					'company': frm.doc.company,
					'docstatus': 1,
					'outstanding_amount': ['>', 0]
				}
			};
		});

		// Filter for return/credit note (with replacement items)
		frm.set_query('negative_invoice', function() {
			if (!frm.doc.customer) {
				frappe.msgprint(__('Please select Customer first'));
				return;
			}
			return {
				filters: {
					'customer': frm.doc.customer,
					'company': frm.doc.company,
					'docstatus': 1,
					'outstanding_amount': ['<', 0]
				}
			};
		});

		// Filter for receivable account
		frm.set_query('receivable_account', function() {
			return {
				filters: {
					'account_type': 'Receivable',
					'company': frm.doc.company,
					'is_group': 0
				}
			};
		});

		// Filter items in positive_items to only show items from positive invoice
		frm.set_query('item_code', 'positive_items', function(doc, cdt, cdn) {
			if (!doc.positive_invoice) {
				frappe.msgprint(__('Please select Original Invoice first'));
				return;
			}
			return {
				query: 'isoft_customization.isoft_customization.doctype.item_resumption.item_resumption.get_items_from_invoice',
				filters: {
					'invoice_name': doc.positive_invoice
				}
			};
		});

		// Filter items in negative_items to only show items from negative invoice
		frm.set_query('item_code', 'negative_items', function(doc, cdt, cdn) {
			if (!doc.negative_invoice) {
				frappe.msgprint(__('Please select Return/Credit Note first'));
				return;
			}
			return {
				query: 'isoft_customization.isoft_customization.doctype.item_resumption.item_resumption.get_items_from_invoice',
				filters: {
					'invoice_name': doc.negative_invoice
				}
			};
		});
	}
});

function load_invoice_items(frm, invoice_name, item_table) {
	// Load items from invoice for item replacement reference
	if (!invoice_name) return;

	frappe.call({
		method: 'frappe.client.get_list',
		args: {
			doctype: 'Sales Invoice Item',
			filters: {
				parent: invoice_name
			},
			fields: ['item_code', 'item_name', 'description']
		},
		callback: function(r) {
			if (r.message) {
				frm.clear_table(item_table);
				r.message.forEach(function(item) {
					let row = frm.add_child(item_table);
					row.item_code = item.item_code;
					row.item_name = item.item_name;
					row.description = item.description;
				});
				frm.refresh_field(item_table);
			}
		}
	});
}

// Event handler for positive_items child table
frappe.ui.form.on('Item Resumption Positive Item', {
	item_code: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (row.item_code && frm.doc.positive_invoice) {
			// Get item details from the invoice
			frappe.call({
				method: 'frappe.client.get_value',
				args: {
					doctype: 'Sales Invoice Item',
					filters: {
						parent: frm.doc.positive_invoice,
						item_code: row.item_code
					},
					fieldname: ['item_name', 'description']
				},
				callback: function(r) {
					if (r.message) {
						frappe.model.set_value(cdt, cdn, 'item_name', r.message.item_name);
						frappe.model.set_value(cdt, cdn, 'description', r.message.description);
					}
				}
			});
		}
	}
});

// Event handler for negative_items child table
frappe.ui.form.on('Item Resumption Negative Item', {
	item_code: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (row.item_code && frm.doc.negative_invoice) {
			// Get item details from the invoice
			frappe.call({
				method: 'frappe.client.get_value',
				args: {
					doctype: 'Sales Invoice Item',
					filters: {
						parent: frm.doc.negative_invoice,
						item_code: row.item_code
					},
					fieldname: ['item_name', 'description']
				},
				callback: function(r) {
					if (r.message) {
						frappe.model.set_value(cdt, cdn, 'item_name', r.message.item_name);
						frappe.model.set_value(cdt, cdn, 'description', r.message.description);
					}
				}
			});
		}
	}
});
