// Get Items From > Quotation on the Quotation form.
//
// ERPNext offers only the Opportunity as a source. This adds existing quotations
// as a second one: the dialog takes several at a time, and ticking "Select Child
// Table Items" narrows the pick down to individual item rows.
//
// Layered on with doctype_js, which Frappe merges across apps, so this stacks with
// ERPNext's own quotation.js -- the button joins the group core created rather than
// replacing anything. The mapper behind it is isoft_customization/quotation.py.

frappe.ui.form.on('Quotation', {
	refresh: function (frm) {
		if (frm.doc.docstatus !== 0) return;

		frm.add_custom_button(__('Quotation'), function () {
			erpnext.utils.map_current_doc({
				method: 'isoft_customization.quotation.make_quotation',
				source_doctype: 'Quotation',
				target: frm,
				date_field: 'transaction_date',
				setters: [
					{
						label: __('Party'),
						fieldname: 'party_name',
						fieldtype: 'Link',
						options: frm.doc.quotation_to || 'Customer',
						default: frm.doc.party_name || undefined
					}
				],
				get_query_filters: {
					docstatus: ['<', 2],
					company: frm.doc.company,
					name: ['!=', frm.doc.name]
				},
				allow_child_item_selection: true,
				child_fieldname: 'items',
				child_columns: ['item_code', 'qty', 'rate']
			});
		}, __('Get Items From'), 'btn-default');
	}
});
