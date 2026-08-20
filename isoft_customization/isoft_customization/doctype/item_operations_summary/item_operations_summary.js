// Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Item Operations Summary', {
	refresh: function(frm) {
		// Add primary action buttons
		frm.page.set_primary_action(__('Generate Summary'), function() {
			frm.trigger('generate_summary');
		});

		frm.page.set_secondary_action(__('Export as PDF'), function() {
			frm.trigger('export_pdf');
		});

		// Auto-generate summary when item_code is selected
		if (frm.doc.item_code) {
			setTimeout(() => {
				frm.trigger('generate_summary');
			}, 300);
		}
	},

	item_code: function(frm) {
		if (frm.doc.item_code) {
			// Fetch item details
			frappe.db.get_value('Item', frm.doc.item_code, ['item_name', 'stock_uom', 'item_group'], (r) => {
				if (r) {
					frm.set_value('item_name', r.item_name);
					frm.set_value('stock_uom', r.stock_uom);
					frm.set_value('item_group', r.item_group);
					
					// Save the form
					frm.save().then(() => {
						// Auto-generate summary after save
						setTimeout(() => {
							frm.trigger('generate_summary');
						}, 300);
					});
				}
			});
		} else {
			frm.set_value('item_name', '');
			frm.set_value('stock_uom', '');
			frm.set_value('item_group', '');
			frm.fields_dict.operations_summary_html.$wrapper.html('');
		}
	},

	generate_summary: function(frm) {
		if (!frm.doc.item_code) {
			frappe.msgprint(__('Please select an Item Code first'));
			return;
		}

		frappe.dom.freeze(__('Generating operations summary...'));

		frappe.call({
			method: 'generate_operations_summary',
			doc: frm.doc,
			callback: function(r) {
				frappe.dom.unfreeze();
				if (r.message) {
					// Display the HTML in the HTML field
					frm.fields_dict.operations_summary_html.$wrapper.html(r.message);
					frappe.show_alert({
						message: __('Operations summary generated successfully'),
						indicator: 'green'
					}, 3);
				}
			},
			error: function() {
				frappe.dom.unfreeze();
			}
		});
	},

	export_pdf: function(frm) {
		if (!frm.doc.item_code) {
			frappe.msgprint(__('Please select an Item Code first'));
			return;
		}

		frappe.dom.freeze(__('Generating PDF...'));

		// Use direct URL call for PDF download
		let method_path = 'isoft_customization.isoft_customization.doctype.item_operations_summary.item_operations_summary.generate_pdf';
		
		window.open(
			`/api/method/${method_path}?item_code=${encodeURIComponent(frm.doc.item_code)}`,
			'_blank'
		);

		setTimeout(() => {
			frappe.dom.unfreeze();
			frappe.show_alert({
				message: __('PDF download started'),
				indicator: 'green'
			}, 3);
		}, 500);
	}
});

