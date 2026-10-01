"""ISOFT branding defaults for a site that has this app.

Frappe falls back to its own favicon, and ERPNext's `website_context` hook to
ERPNext's, whenever Website Settings has none. This puts the ISOFT icon in that
slot instead, for the desk, the login page and the website alike. An icon chosen
in Website Settings still wins.
"""
import frappe

FAVICON = "/assets/isoft_customization/images/isoft-favicon.ico"


def update_website_context(context):
	favicon = frappe.db.get_single_value("Website Settings", "favicon")
	if favicon and favicon != "attach_files:":
		return None
	return {"favicon": FAVICON}
