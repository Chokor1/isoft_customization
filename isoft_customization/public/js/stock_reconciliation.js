// Stock Reconciliation > Fetch Items from Warehouse, with Brand and Item Group filters
// (see stock_reco_fetch.py).
//
// ERPNext's button calls frm.events.get_items(frm). frm.events keeps the LAST handler
// registered for an event, and this file loads after ERPNext's form script, so the
// dialog below replaces ERPNext's. Same fields and behaviour, plus Brand and Item Group.

frappe.ui.form.on('Stock Reconciliation', {
	get_items: function (frm) {
		const fields = [
			{
				label: __('Warehouse'),
				fieldname: 'warehouse',
				fieldtype: 'Link',
				options: 'Warehouse',
				reqd: 1,
				get_query: function () {
					return { filters: { company: frm.doc.company } };
				},
			},
			{
				label: __('Item Code'),
				fieldname: 'item_code',
				fieldtype: 'Link',
				options: 'Item',
				get_query: function () {
					return { filters: { disabled: 0 } };
				},
			},
			{
				label: __('Brand'),
				fieldname: 'brand',
				fieldtype: 'Link',
				options: 'Brand',
			},
			{
				label: __('Item Group'),
				fieldname: 'item_group',
				fieldtype: 'Link',
				options: 'Item Group',
				description: __('Includes its sub-groups'),
			},
			{
				label: __('Ignore Empty Stock'),
				fieldname: 'ignore_empty_stock',
				fieldtype: 'Check',
			},
		];

		frappe.prompt(fields, function (data) {
			frappe.call({
				method: 'isoft_customization.stock_reco_fetch.get_items',
				args: {
					warehouse: data.warehouse,
					posting_date: frm.doc.posting_date,
					posting_time: frm.doc.posting_time,
					company: frm.doc.company,
					item_code: data.item_code,
					ignore_empty_stock: data.ignore_empty_stock,
					brand: data.brand,
					item_group: data.item_group,
				},
				freeze: true,
				callback: function (r) {
					if (r.exc) return;
					if (!r.message || !r.message.length) {
						frappe.msgprint(__('No items found'));
						return;
					}

					frm.clear_table('items');
					r.message.forEach(function (row) {
						const item = frm.add_child('items');
						$.extend(item, row);
						item.qty = item.qty || 0;
						item.valuation_rate = item.valuation_rate || 0;
					});
					frm.refresh_field('items');
				},
			});
		}, __('Get Items'), __('Update'));
	},
});
