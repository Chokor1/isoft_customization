// List view "Print" for selected rows: POST the selection instead of GET.
//
// Core (frappe/list/bulk_operations.js) opens
// /api/method/frappe.utils.print_format.download_multi_pdf?name=[...] with every
// selected name in the URL. gunicorn caps the request line at 4094 bytes by
// default, so ~140 Payment Entries already answer "Request Line is too large".
// The same whitelisted method accepts POST, so this posts the selection with
// open_url_post (as the app's Excel export does): no URL limit, nothing to
// configure per server. The dialog is core's, reproduced.
//
// BulkOperations is module-private in v13 (a local in get_actions_menu_items), so
// the Print menu item itself is swapped after core builds the menu.

frappe.provide('isoft.bulk_print');

(function (ns) {
	const METHOD = '/api/method/frappe.utils.print_format.download_multi_pdf';

	function letterhead_options() {
		const options = [__('No Letterhead')];
		frappe.call({
			method: 'frappe.client.get_list',
			args: { doctype: 'Letter Head', fields: ['name', 'is_default'], limit_page_length: 0 },
			async: false,
			callback: function (r) { (r.message || []).forEach(function (lh) { options.push(lh.name); }); }
		});
		return options;
	}

	ns.print = function (doctype, docs) {
		const print_settings = frappe.model.get_doc(':Print Settings', 'Print Settings');
		const allow_draft = cint(print_settings.allow_print_for_draft);
		const allow_cancelled = cint(print_settings.allow_print_for_cancelled);
		const is_submittable = frappe.model.is_submittable(doctype);

		const valid_docs = docs.filter(function (doc) {
			return !is_submittable || doc.docstatus === 1 ||
				(allow_cancelled && doc.docstatus == 2) ||
				(allow_draft && doc.docstatus == 0) ||
				frappe.user.has_role('Administrator');
		}).map(function (doc) { return doc.name; });

		if (valid_docs.length < docs.length) { frappe.msgprint(__('You selected Draft or Cancelled documents')); return; }
		if (!valid_docs.length) { frappe.msgprint(__('Select atleast 1 record for printing')); return; }

		const dialog = new frappe.ui.Dialog({
			title: __('Print Documents'),
			fields: [
				{ fieldtype: 'Select', label: __('Letter Head'), fieldname: 'letter_sel', default: __('No Letterhead'), options: letterhead_options() },
				{ fieldtype: 'Select', label: __('Print Format'), fieldname: 'print_sel', options: frappe.meta.get_print_formats(doctype) },
				{ fieldtype: 'Select', label: __('Page Size'), fieldname: 'page_size', options: frappe.meta.get_print_sizes(), default: print_settings.pdf_page_size },
				{ fieldtype: 'Float', label: __('Page Height (in mm)'), fieldname: 'page_height', depends_on: 'eval:doc.page_size == "Custom"', default: print_settings.pdf_page_height },
				{ fieldtype: 'Float', label: __('Page Width (in mm)'), fieldname: 'page_width', depends_on: 'eval:doc.page_size == "Custom"', default: print_settings.pdf_page_width }
			]
		});

		dialog.set_primary_action(__('Print'), function (args) {
			if (!args) return;
			const default_print_format = frappe.get_meta(doctype).default_print_format;
			const with_letterhead = args.letter_sel == __('No Letterhead') ? 0 : 1;
			const print_format = args.print_sel ? args.print_sel : default_print_format;
			let pdf_options;
			if (args.page_size === 'Custom') {
				if (args.page_height === 0 || args.page_width === 0) frappe.throw(__('Page height and width cannot be zero'));
				pdf_options = JSON.stringify({ 'page-height': args.page_height, 'page-width': args.page_width });
			} else {
				pdf_options = JSON.stringify({ 'page-size': args.page_size });
			}
			open_url_post(METHOD, {
				doctype: doctype,
				name: JSON.stringify(valid_docs),
				format: print_format || '',
				no_letterhead: with_letterhead ? '0' : '1',
				letterhead: args.letter_sel || '',
				options: pdf_options
			}, true);
			dialog.hide();
		});
		dialog.show();
	};

	function patch() {
		const ListView = frappe.views && frappe.views.ListView;
		if (!ListView || ListView.prototype.__isoft_bulk_print) return;
		const original = ListView.prototype.get_actions_menu_items;
		ListView.prototype.get_actions_menu_items = function () {
			const items = original.apply(this, arguments) || [];
			const me = this;
			const label = __('Print', null, 'Button in list view actions menu');
			items.forEach(function (item) {
				if (item.standard && item.label === label) {
					item.action = function () { ns.print(me.doctype, me.get_checked_items()); };
				}
			});
			return items;
		};
		ListView.prototype.__isoft_bulk_print = true;
	}
	patch();
	$(document).on('app_ready', patch);
})(isoft.bulk_print);
