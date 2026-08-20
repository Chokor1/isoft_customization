// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Invoice Payment Notification', {
	set_print_format_query: function(frm) {
		const doc_type = frm.doc.reference_doctype || 'Payment Entry';
		frm.set_query('print_format', function() {
			return {
				filters: {
					'doc_type': doc_type
				}
			};
		});
	},

	refresh: function(frm) {
		// Add custom buttons
		if (!frm.doc.__islocal) {
			// Send Manual Email button
			frm.add_custom_button(__('Send Test Email'), function() {
				if (frm.is_dirty()) {
					frappe.throw(__("Please save before sending test email"));
				}
				if (!frm.doc.reference_doctype) {
					frappe.throw(__("Please select Document Type first"));
				}

				const reference_doctype = frm.doc.reference_doctype || 'Payment Entry';
				const link_label = reference_doctype === 'Sales Invoice' ? __('Sales Invoice') : __('Payment Entry');
				const query_filters = reference_doctype === 'Sales Invoice'
					? {
						'docstatus': 1,
						'company': frm.doc.company
					}
					: {
						'docstatus': 1,
						'party_type': 'Customer',
						'company': frm.doc.company
					};

				frappe.prompt([
					{
						fieldname: 'reference_name',
						fieldtype: 'Link',
						label: link_label,
						reqd: 1,
						options: reference_doctype,
						get_query: function() {
							return {
								filters: query_filters
							};
						}
					}
				], function(values) {
				frappe.call({
					method: 'erpnext.accounts.doctype.invoice_payment_notification.invoice_payment_notification.send_manual_notification',
						args: {
							'docname': frm.doc.name,
							'reference_doctype': reference_doctype,
							'reference_name': values.reference_name
						},
						callback: function(r) {
							if (r.message) {
								frappe.show_alert({
									message: __('Email queued successfully'),
									indicator: 'green'
								});
							}
						}
					});
				}, __('Select {0}', [link_label]), __('Send Email'));
			});

		}

		// Set query for print format based on selected document type
		frm.events.set_print_format_query(frm);

		// Set query for customer collection
		frm.set_query('collection_name', function() {
			if (frm.doc.customer_collection === 'Customer Group') {
				return { doctype: 'Customer Group' };
			} else if (frm.doc.customer_collection === 'Territory') {
				return { doctype: 'Territory' };
			} else if (frm.doc.customer_collection === 'Sales Partner') {
				return { doctype: 'Sales Partner' };
			} else if (frm.doc.customer_collection === 'Sales Person') {
				return { doctype: 'Sales Person' };
			}
		});
	},

	customer_collection: function(frm) {
		frm.set_value('collection_name', '');
		frm.set_value('customers', []);
	},

	reference_doctype: function(frm) {
		frm.set_value('print_format', '');
		frm.events.set_print_format_query(frm);
	},

	include_ledger: function(frm) {
		if (frm.doc.include_ledger && !frm.doc.ledger_from_date_mode) {
			frm.set_value('ledger_from_date_mode', 'Start of Current Month');
		}
		frm.events.set_ledger_from_date(frm);
	},
	
	ledger_from_date_mode: function(frm) {
		frm.events.set_ledger_from_date(frm);
	},

	set_ledger_from_date: function(frm) {
		if (!frm.doc.include_ledger) {
			return;
		}
		const today = frappe.datetime.get_today();
		if (frm.doc.ledger_from_date_mode === 'Custom Date') {
			return;
		}
		if (frm.doc.ledger_from_date_mode === 'Start of Current Month') {
			frm.set_value('ledger_from_date', frappe.datetime.month_start(today));
		} else if (frm.doc.ledger_from_date_mode === 'Start of Current Year') {
			const year_start = frappe.datetime.year_start(today);
			frm.set_value('ledger_from_date', year_start);
		} else if (frm.doc.ledger_from_date_mode === 'Current Date') {
			frm.set_value('ledger_from_date', today);
		}
	},

	onload: function(frm) {
		// Set default values for new documents
		if (frm.doc.__islocal) {
			frm.set_value('subject', 'Payment Receipt for {{ customer.customer_name }}');
			frm.set_value('body', 'Dear {{ customer.customer_name }},<br><br>Thank you for your payment. Please find attached your invoice(s) and account statement.<br><br>Payment Reference: {{ payment_entry.name }}<br>Amount: {{ payment_entry.paid_amount }}');
			
			// Set default ledger dates
			if (frm.doc.include_ledger) {
				if (!frm.doc.ledger_from_date_mode) {
					frm.set_value('ledger_from_date_mode', 'Start of Current Month');
				}
				frm.events.set_ledger_from_date(frm);
			}
		}
	}
});

// Child table script
frappe.ui.form.on('Post Payment Invoice Customer', {
	customer: function(frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		if (row.customer) {
			frappe.call({
				method: 'frappe.client.get_value',
				args: {
					doctype: 'Customer',
					filters: { name: row.customer },
					fieldname: ['customer_name', 'email_id']
				},
				callback: function(r) {
					if (r.message) {
						frappe.model.set_value(cdt, cdn, 'customer_name', r.message.customer_name);
						frappe.model.set_value(cdt, cdn, 'billing_email', r.message.email_id);
					}
				}
			});
		}
	}
});
