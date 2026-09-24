from __future__ import unicode_literals

app_name = "isoft_customization"
app_title = "ISOFT Customization"
app_publisher = "Isoft"
app_description = "ISOFT customizations for Frappe / ERPNext"
app_icon = "octicon octicon-file-spreadsheet"
app_color = "green"
app_email = "abbasschokor225@gmail.com"
app_license = "MIT"

# adds the "Excel" button to every child table grid in the desk
app_include_js = [
	"/assets/isoft_customization/js/grid_excel.js",
	# Adds the "Include Barcode" filter to five ERPNext stock reports. Must load
	# before any report script, which app_include_js does.
	"/assets/isoft_customization/js/report_barcode_filter.js",
	# Full-width Desk by default: seeds localStorage.container_fullwidth when it
	# is absent, which is what flipping the two literals in toolbar.js did.
	"/assets/isoft_customization/js/fullwidth_default.js",
	# Company-wise naming series: rebuilds the naming_series dropdown from the
	# Isoft Naming Series Settings map shipped in boot. Inert while disabled.
	"/assets/isoft_customization/js/company_naming_series.js",
	# Louder navbar bell: gold pulsing halo, ring shake and an unread-count badge
	# layered over core's tiny red dot. Pairs with css/notification_attention.css.
	"/assets/isoft_customization/js/notification_attention.js",
	# Reason prompts before cancelling selling documents and submitting credit
	# notes, per the Document Reasons checkboxes on Selling Settings.
	"/assets/isoft_customization/js/document_reasons.js",
]

app_include_css = [
	"/assets/isoft_customization/css/notification_attention.css",
]

# bulk "Stop" action in the Material Request list view
doctype_list_js = {"Material Request": "public/js/material_request_list.js"}


# Payment notifications, moved here from ERPNext core. The DocType and both triggers
# were sitting in erpnext/accounts; nothing about them is ERPNext. Frappe merges
# doc_events across apps, so these stack with ERPNext's own on_submit handlers
# rather than replacing them.
doc_events = {
	# Company-wise naming series. before_naming runs inside set_new_name, before
	# the series counter is consumed, so a disallowed series is rejected without
	# burning a number. No-op unless Isoft Naming Series Settings is enabled.
	"*": {
		"before_naming": "isoft_customization.isoft_customization.doctype.isoft_naming_series_settings.isoft_naming_series_settings.apply_company_naming_series",
	},
	"Sales Invoice": {
		"on_submit": "isoft_customization.isoft_customization.doctype.invoice_payment_notification.invoice_payment_notification.trigger_notification_on_sales_invoice_submit",
		# Mandatory reasons, per Selling Settings. See document_reasons.py.
		# Batch ownership check runs first so a bad batch fails before docstatus is
		# written (and before anyone is asked for a reason). See batch_integrity.py.
		"before_submit": [
			"isoft_customization.batch_integrity.validate_batch_belongs_to_item",
			"isoft_customization.document_reasons.validate_credit_note_reason",
		],
		# saft_xml auto-submits non-POS invoices from before_save, which skips
		# before_submit; this re-runs the batch check right before that write.
		"before_save": "isoft_customization.batch_integrity.validate_batch_on_auto_submit",
		"before_cancel": "isoft_customization.document_reasons.validate_cancel_reason",
	},
	"Quotation": {
		"before_cancel": "isoft_customization.document_reasons.validate_cancel_reason",
	},
	"Sales Order": {
		"before_cancel": "isoft_customization.document_reasons.validate_cancel_reason",
	},
	"Delivery Note": {
		"before_submit": "isoft_customization.batch_integrity.validate_batch_belongs_to_item",
		"before_cancel": "isoft_customization.document_reasons.validate_cancel_reason",
	},
	"Payment Entry": {
		"on_submit": "isoft_customization.isoft_customization.doctype.invoice_payment_notification.invoice_payment_notification.trigger_notification_on_payment_submit",
	},
	# Batch <-> Item integrity. See batch_integrity.py.
	# Guard 1: Batch.item cannot be re-pointed once the ledger has stock under it.
	"Batch": {
		"validate": "isoft_customization.batch_integrity.prevent_item_reassignment",
	},
	# Guard 2: every batch-bearing row must be owned by its item, checked before
	# docstatus is written. Sales Invoice and Delivery Note are wired above.
	"Purchase Receipt": {
		"before_submit": "isoft_customization.batch_integrity.validate_batch_belongs_to_item",
	},
	"Purchase Invoice": {
		"before_submit": "isoft_customization.batch_integrity.validate_batch_belongs_to_item",
	},
	"Stock Entry": {
		"before_submit": "isoft_customization.batch_integrity.validate_batch_belongs_to_item",
	},
	"Stock Reconciliation": {
		"before_submit": "isoft_customization.batch_integrity.validate_batch_belongs_to_item",
	},
}


# Create > Quotation on Sales Order, moved out of ERPNext's own sales_order.js, and
# Get Items From > Quotation on the Quotation form.
# Frappe merges doctype_js across apps, so these stack with ERPNext's rather than
# replacing them.
doctype_js = {
	"Sales Order": "public/js/sales_order.js",
	"Quotation": "public/js/quotation.js",
	"Purchase Invoice": "public/js/purchase_invoice.js",
}

# Large documents submit / cancel from the long queue instead of inside the HTTP
# request, which the web tier kills after 120 s. See background_submit.py.
# Threshold: site_config `background_submit_min_rows` (default 200, 0 = off).
override_doctype_class = {
	"Purchase Invoice": "isoft_customization.overrides.purchase_invoice.IsoftPurchaseInvoice",
}


# Ships the company-wise naming series map to the desk (see company_naming_series.js).
boot_session = "isoft_customization.isoft_customization.doctype.isoft_naming_series_settings.isoft_naming_series_settings.boot_session"


# Seed the Portuguese overrides as Translation records. The CSV in translations/ is
# the source of truth; this only guarantees it beats erpnext's catalogue, which
# sorts after this app in sites/apps.txt. See translations_override.py.
after_migrate = [
	"isoft_customization.translations_override.sync_translations",
	# Selling Settings "Document Reasons" switches and the reason fields they fill.
	"isoft_customization.document_reasons.setup_custom_fields",
]
