"""The Quotation's note follows it onto the Sales Invoice / Sales Order made from it.

The Quotation keeps its note in `note` (printed by the proforma formats); Sales Order and
Sales Invoice keep theirs in `posa_notes` ("Additional Notes", printed by the invoice
formats). The mapper only copies fields with the same name, so the note was dropped.
Hooked on set_missing_values, which the mapper runs on the new document; a note already
there (typed, or carried from a Sales Order) is never overwritten.
"""
import frappe


def copy_quotation_note(doc, method=None, *args, **kwargs):
	if doc.docstatus != 0 or not doc.meta.has_field("posa_notes") or (doc.get("posa_notes") or "").strip():
		return
	quotations = []
	for row in doc.get("items") or []:
		name = row.get("prevdoc_docname")
		if name and name not in quotations and frappe.db.exists("Quotation", name):
			quotations.append(name)
	notes = [n.strip() for n in (frappe.db.get_value("Quotation", q, "note") for q in quotations) if (n or "").strip()]
	if notes:
		doc.posa_notes = "\n\n".join(dict.fromkeys(notes))
