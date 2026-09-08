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
	},
	"Payment Entry": {
		"on_submit": "isoft_customization.isoft_customization.doctype.invoice_payment_notification.invoice_payment_notification.trigger_notification_on_payment_submit",
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
after_migrate = "isoft_customization.translations_override.sync_translations"
