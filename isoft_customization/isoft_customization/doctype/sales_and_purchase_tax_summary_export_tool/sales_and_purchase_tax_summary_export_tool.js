// Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Sales And Purchase Tax Summary Export Tool', {
	refresh: function (frm) {
		frm.disable_save();
		frm.add_custom_button(__('Export Taxes Summary as PDF'), function () {
			if (!frm.doc.from_date || !frm.doc.to_date) {
				frappe.msgprint(__('Please set both From Date and To Date.'));
				return;
			}
			
			// Show loading message
			frappe.show_alert(__('Generating tax summary...'), 3);
			
			frm.save()
			frappe.call({
				method: 'isoft_customization.isoft_customization.doctype.sales_and_purchase_tax_summary_export_tool.sales_and_purchase_tax_summary_export_tool.generate_tax_summary_pdf',
				args: {
					from_date: frm.doc.from_date,
					to_date: frm.doc.to_date,
				},
				callback: function (r) {
					if (r.message) {
						const pdf_url = r.message;
						console.log('PDF URL:', pdf_url);
						
						// Show success message
						frappe.show_alert(__('Tax summary generated successfully!'), 3);
						
						// Open PDF in a new tab
						const win = window.open(pdf_url, '_blank');
						if (win) {
							win.focus();
						} else {
							// Fallback if popup is blocked
							frappe.msgprint({
								title: __('PDF Generated'),
								message: __('Tax summary PDF has been generated. <a href="' + pdf_url + '" target="_blank">Click here to download</a>'),
								indicator: 'green'
							});
						}
					} else {
						frappe.msgprint({
							title: __('Error'),
							message: __('Failed to generate tax summary. Please try again.'),
							indicator: 'red'
						});
					}
				},
				error: function(r) {
					frappe.msgprint({
						title: __('Error'),
						message: __('Failed to generate tax summary: ' + (r.exc || 'Unknown error')),
						indicator: 'red'
					});
				}
			});
		});
	}
});
