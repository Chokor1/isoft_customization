# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_url


class ItemOperationsSummary(Document):
	def validate(self):
		if self.item_code:
			item = frappe.get_doc("Item", self.item_code)
			self.item_name = item.item_name
			self.stock_uom = item.stock_uom
			self.item_group = item.item_group

	@frappe.whitelist()
	def generate_operations_summary(self):
		"""Generate comprehensive operations summary for the item"""
		if not self.item_code:
			frappe.throw(_("Please select an Item Code first"))
		
		# Get item details
		item = frappe.get_doc("Item", self.item_code)
		
		# Fetch all related documents
		sales_invoices = self.get_sales_invoices()
		quotations = self.get_quotations()
		delivery_notes = self.get_delivery_notes()
		purchase_receipts = self.get_purchase_receipts()
		purchase_invoices = self.get_purchase_invoices()
		item_resumptions_replaced = self.get_item_resumptions_as_original()
		item_resumptions_replacement = self.get_item_resumptions_as_replacement()
		
		# Generate HTML
		html = self.build_summary_html(
			item,
			sales_invoices,
			quotations,
			delivery_notes,
			purchase_receipts,
			purchase_invoices,
			item_resumptions_replaced,
			item_resumptions_replacement
		)
		
		return html

	def get_sales_invoices(self):
		"""Get all Sales Invoices containing this item"""
		return frappe.db.sql("""
			SELECT DISTINCT
				si.name,
				si.posting_date,
				si.customer,
				si.grand_total,
				si.status,
				sii.qty,
				sii.rate,
				sii.amount
			FROM `tabSales Invoice` si
			INNER JOIN `tabSales Invoice Item` sii ON sii.parent = si.name
			WHERE sii.item_code = %(item_code)s
				AND si.docstatus < 2
			ORDER BY si.posting_date DESC
			LIMIT 100
		""", {"item_code": self.item_code}, as_dict=True)

	def get_quotations(self):
		"""Get all Quotations containing this item"""
		return frappe.db.sql("""
			SELECT DISTINCT
				q.name,
				q.transaction_date,
				q.party_name,
				q.grand_total,
				q.status,
				qi.qty,
				qi.rate,
				qi.amount
			FROM `tabQuotation` q
			INNER JOIN `tabQuotation Item` qi ON qi.parent = q.name
			WHERE qi.item_code = %(item_code)s
				AND q.docstatus < 2
			ORDER BY q.transaction_date DESC
			LIMIT 100
		""", {"item_code": self.item_code}, as_dict=True)

	def get_delivery_notes(self):
		"""Get all Delivery Notes containing this item"""
		return frappe.db.sql("""
			SELECT DISTINCT
				dn.name,
				dn.posting_date,
				dn.customer,
				dn.grand_total,
				dn.status,
				dni.qty,
				dni.rate,
				dni.amount
			FROM `tabDelivery Note` dn
			INNER JOIN `tabDelivery Note Item` dni ON dni.parent = dn.name
			WHERE dni.item_code = %(item_code)s
				AND dn.docstatus < 2
			ORDER BY dn.posting_date DESC
			LIMIT 100
		""", {"item_code": self.item_code}, as_dict=True)

	def get_purchase_receipts(self):
		"""Get all Purchase Receipts containing this item"""
		return frappe.db.sql("""
			SELECT DISTINCT
				pr.name,
				pr.posting_date,
				pr.supplier,
				pr.grand_total,
				pr.status,
				pri.qty,
				pri.rate,
				pri.amount
			FROM `tabPurchase Receipt` pr
			INNER JOIN `tabPurchase Receipt Item` pri ON pri.parent = pr.name
			WHERE pri.item_code = %(item_code)s
				AND pr.docstatus < 2
			ORDER BY pr.posting_date DESC
			LIMIT 100
		""", {"item_code": self.item_code}, as_dict=True)

	def get_purchase_invoices(self):
		"""Get all Purchase Invoices containing this item"""
		return frappe.db.sql("""
			SELECT DISTINCT
				pi.name,
				pi.posting_date,
				pi.supplier,
				pi.grand_total,
				pi.status,
				pii.qty,
				pii.rate,
				pii.amount
			FROM `tabPurchase Invoice` pi
			INNER JOIN `tabPurchase Invoice Item` pii ON pii.parent = pi.name
			WHERE pii.item_code = %(item_code)s
				AND pi.docstatus < 2
			ORDER BY pi.posting_date DESC
			LIMIT 100
		""", {"item_code": self.item_code}, as_dict=True)

	def get_item_resumptions_as_original(self):
		"""Get Item Resumption records where this item was the ORIGINAL item (being replaced)"""
		return frappe.db.sql("""
			SELECT DISTINCT
				ir.name,
				ir.customer,
				ir.posting_date,
				ir.positive_invoice,
				ir.negative_invoice,
				irni.item_code as replacement_item,
				irni.item_name as replacement_item_name,
				ir.journal_entry
			FROM `tabItem Resumption` ir
			INNER JOIN `tabItem Resumption Positive Item` irpi ON irpi.parent = ir.name
			LEFT JOIN `tabItem Resumption Negative Item` irni ON irni.parent = ir.name
			WHERE irpi.item_code = %(item_code)s
				AND ir.docstatus < 2
			ORDER BY ir.posting_date DESC
			LIMIT 50
		""", {"item_code": self.item_code}, as_dict=True)

	def get_item_resumptions_as_replacement(self):
		"""Get Item Resumption records where this item was the REPLACEMENT item (new item)"""
		return frappe.db.sql("""
			SELECT DISTINCT
				ir.name,
				ir.customer,
				ir.posting_date,
				ir.positive_invoice,
				ir.negative_invoice,
				irpi.item_code as original_item,
				irpi.item_name as original_item_name,
				ir.journal_entry
			FROM `tabItem Resumption` ir
			INNER JOIN `tabItem Resumption Negative Item` irni ON irni.parent = ir.name
			LEFT JOIN `tabItem Resumption Positive Item` irpi ON irpi.parent = ir.name
			WHERE irni.item_code = %(item_code)s
				AND ir.docstatus < 2
			ORDER BY ir.posting_date DESC
			LIMIT 50
		""", {"item_code": self.item_code}, as_dict=True)

	def build_summary_html(self, item, sales_invoices, quotations, delivery_notes, 
							purchase_receipts, purchase_invoices, 
							item_resumptions_replaced, item_resumptions_replacement):
		"""Build the HTML summary"""
		
		base_url = get_url()
		
		html = f"""
		<style>
			.ops-summary {{
				font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
				padding: 20px;
				background: #f5f7fa;
			}}
			.ops-header {{
				background: linear-gradient(135deg, #5b7c99 0%, #4a6fa5 100%);
				color: white;
				padding: 15px 20px;
				border-radius: 8px;
				margin-bottom: 20px;
				box-shadow: 0 2px 8px rgba(75, 111, 165, 0.12);
			}}
			.ops-header h2 {{
				margin: 0 0 8px 0;
				font-size: 20px;
				font-weight: 600;
			}}
			.ops-header p {{
				margin: 3px 0;
				opacity: 0.95;
				font-size: 13px;
			}}
			.ops-section {{
				background: white;
				border: 1px solid #e1e8ed;
				border-radius: 10px;
				padding: 20px;
				margin-bottom: 20px;
				box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
			}}
			.ops-section h3 {{
				color: #4a6fa5;
				margin-top: 0;
				padding-bottom: 12px;
				border-bottom: 3px solid #6c8aae;
				font-size: 20px;
				font-weight: 600;
			}}
			.ops-table {{
				width: 100%;
				border-collapse: collapse;
				margin-top: 15px;
			}}
			.ops-table th {{
				background: linear-gradient(to bottom, #e8eef3, #d4dfe9);
				padding: 12px;
				text-align: left;
				font-weight: 600;
				border-bottom: 2px solid #6c8aae;
				color: #3d5a80;
				font-size: 13px;
				text-transform: uppercase;
				letter-spacing: 0.5px;
			}}
			.ops-table td {{
				padding: 10px 12px;
				border-bottom: 1px solid #f0f4f8;
				font-size: 14px;
				color: #2c3e50;
			}}
			.ops-table tr:hover {{
				background: #f4f7fb;
				transition: all 0.2s ease;
			}}
			.ops-link {{
				color: #4a6fa5;
				text-decoration: none;
				font-weight: 500;
				transition: color 0.2s ease;
			}}
			.ops-link:hover {{
				color: #3d5a80;
				text-decoration: underline;
			}}
			.ops-badge {{
				padding: 4px 10px;
				border-radius: 12px;
				font-size: 11px;
				font-weight: 600;
				display: inline-block;
			}}
			.badge-success {{ background: #d4edda; color: #155724; }}
			.badge-warning {{ background: #fff3cd; color: #856404; }}
			.badge-danger {{ background: #f8d7da; color: #721c24; }}
			.badge-info {{ background: #d1ecf1; color: #0c5460; }}
			.alert-box {{
				background: #fff8e1;
				border-left: 4px solid #ffa726;
				border-radius: 6px;
				padding: 12px 15px;
				margin: 12px 0;
				font-size: 14px;
			}}
			.alert-box.replacement {{
				background: #e8f5e9;
				border-left-color: #66bb6a;
			}}
		</style>
		
		<div class="ops-summary">
			<div class="ops-header">
				<h2>{item.item_code} - {item.item_name}</h2>
				<p><strong>Item Group:</strong> {item.item_group} | <strong>UOM:</strong> {item.stock_uom} | <strong>Description:</strong> {item.description or 'N/A'}</p>
			</div>
		"""
		
		# Sales Invoices Section - only show if data exists
		if sales_invoices:
			html += self.build_document_section_with_links(
				"Sales Invoices",
				sales_invoices,
				["Document", "Date", "Customer", "Qty", "Rate", "Amount", "Total", "Status"],
				"Sales Invoice",
				lambda d: [
					("link", "/app/sales-invoice/" + d.name, d.name),
					("text", d.posting_date),
					("link", "/app/customer/" + d.customer, d.customer),
					("text", flt(d.qty, 2)),
					("text", flt(d.rate, 2)),
					("text", flt(d.amount, 2)),
					("text", flt(d.grand_total, 2)),
					("text", d.status)
				]
			)
		
		# Quotations Section - only show if data exists
		if quotations:
			html += self.build_document_section_with_links(
				"Quotations",
				quotations,
				["Document", "Date", "Party", "Qty", "Rate", "Amount", "Total", "Status"],
				"Quotation",
				lambda d: [
					("link", "/app/quotation/" + d.name, d.name),
					("text", d.transaction_date),
					("link", "/app/customer/" + d.party_name, d.party_name) if d.party_name else ("text", "N/A"),
					("text", flt(d.qty, 2)),
					("text", flt(d.rate, 2)),
					("text", flt(d.amount, 2)),
					("text", flt(d.grand_total, 2)),
					("text", d.status)
				]
			)
		
		# Delivery Notes Section - only show if data exists
		if delivery_notes:
			html += self.build_document_section_with_links(
				"Delivery Notes",
				delivery_notes,
				["Document", "Date", "Customer", "Qty", "Rate", "Amount", "Total", "Status"],
				"Delivery Note",
				lambda d: [
					("link", "/app/delivery-note/" + d.name, d.name),
					("text", d.posting_date),
					("link", "/app/customer/" + d.customer, d.customer),
					("text", flt(d.qty, 2)),
					("text", flt(d.rate, 2)),
					("text", flt(d.amount, 2)),
					("text", flt(d.grand_total, 2)),
					("text", d.status)
				]
			)
		
		# Purchase Receipts Section - only show if data exists
		if purchase_receipts:
			html += self.build_document_section_with_links(
				"Purchase Receipts",
				purchase_receipts,
				["Document", "Date", "Supplier", "Qty", "Rate", "Amount", "Total", "Status"],
				"Purchase Receipt",
				lambda d: [
					("link", "/app/purchase-receipt/" + d.name, d.name),
					("text", d.posting_date),
					("link", "/app/supplier/" + d.supplier, d.supplier),
					("text", flt(d.qty, 2)),
					("text", flt(d.rate, 2)),
					("text", flt(d.amount, 2)),
					("text", flt(d.grand_total, 2)),
					("text", d.status)
				]
			)
		
		# Purchase Invoices Section - only show if data exists
		if purchase_invoices:
			html += self.build_document_section_with_links(
				"Purchase Invoices",
				purchase_invoices,
				["Document", "Date", "Supplier", "Qty", "Rate", "Amount", "Total", "Status"],
				"Purchase Invoice",
				lambda d: [
					("link", "/app/purchase-invoice/" + d.name, d.name),
					("text", d.posting_date),
					("link", "/app/supplier/" + d.supplier, d.supplier),
					("text", flt(d.qty, 2)),
					("text", flt(d.rate, 2)),
					("text", flt(d.amount, 2)),
					("text", flt(d.grand_total, 2)),
					("text", d.status)
				]
			)
		
		# Item Resumptions - Item Was Replaced
		if item_resumptions_replaced:
			html += f"""
			<div class="ops-section">
				<h3>🔄 Item Replacement History - This Item Was REPLACED</h3>
				<div class="alert-box">
					<strong>Note:</strong> The following records show where this item was the <strong>ORIGINAL item</strong> that was replaced with a new item.
				</div>
				<table class="ops-table">
					<thead>
						<tr>
							<th>Document</th>
							<th>Date</th>
							<th>Customer</th>
							<th>Original Invoice</th>
							<th>Return Invoice</th>
							<th>Replaced With</th>
							<th>Journal Entry</th>
						</tr>
					</thead>
					<tbody>
			"""
			for d in item_resumptions_replaced:
				replacement_item_html = f"<a href='/app/item/{d.replacement_item}' class='ops-link' target='_blank'><strong>{d.replacement_item}</strong></a> - {d.replacement_item_name or ''}" if d.replacement_item else "N/A"
				html += f"""
					<tr>
						<td><a href="/app/item-resumption/{d.name}" class="ops-link" target="_blank">{d.name}</a></td>
						<td>{d.posting_date}</td>
						<td><a href="/app/customer/{d.customer}" class="ops-link" target="_blank">{d.customer}</a></td>
						<td><a href="/app/sales-invoice/{d.positive_invoice}" class="ops-link" target="_blank">{d.positive_invoice}</a></td>
						<td><a href="/app/sales-invoice/{d.negative_invoice}" class="ops-link" target="_blank">{d.negative_invoice}</a></td>
						<td>{replacement_item_html}</td>
						<td>{"<a href='/app/journal-entry/" + d.journal_entry + "' class='ops-link' target='_blank'>" + d.journal_entry + "</a>" if d.journal_entry else "N/A"}</td>
					</tr>
				"""
			html += """
					</tbody>
				</table>
			</div>
			"""
		
		# Item Resumptions - Item Was Used as Replacement
		if item_resumptions_replacement:
			html += f"""
			<div class="ops-section">
				<h3>✨ Item Replacement History - This Item Was Used as REPLACEMENT</h3>
				<div class="alert-box replacement">
					<strong>Note:</strong> The following records show where this item was the <strong>NEW/REPLACEMENT item</strong> used to replace an old item.
				</div>
				<table class="ops-table">
					<thead>
						<tr>
							<th>Document</th>
							<th>Date</th>
							<th>Customer</th>
							<th>Original Invoice</th>
							<th>Return Invoice</th>
							<th>Replaced Item</th>
							<th>Journal Entry</th>
						</tr>
					</thead>
					<tbody>
			"""
			for d in item_resumptions_replacement:
				original_item_html = f"<a href='/app/item/{d.original_item}' class='ops-link' target='_blank'><strong>{d.original_item}</strong></a> - {d.original_item_name or ''}" if d.original_item else "N/A"
				html += f"""
					<tr>
						<td><a href="/app/item-resumption/{d.name}" class="ops-link" target="_blank">{d.name}</a></td>
						<td>{d.posting_date}</td>
						<td><a href="/app/customer/{d.customer}" class="ops-link" target="_blank">{d.customer}</a></td>
						<td><a href="/app/sales-invoice/{d.positive_invoice}" class="ops-link" target="_blank">{d.positive_invoice}</a></td>
						<td><a href="/app/sales-invoice/{d.negative_invoice}" class="ops-link" target="_blank">{d.negative_invoice}</a></td>
						<td>{original_item_html}</td>
						<td>{"<a href='/app/journal-entry/" + d.journal_entry + "' class='ops-link' target='_blank'>" + d.journal_entry + "</a>" if d.journal_entry else "N/A"}</td>
					</tr>
				"""
			html += """
					</tbody>
				</table>
			</div>
			"""
		
		html += "</div>"
		
		return html

	def build_document_section_with_links(self, title, data, headers, doctype, row_builder):
		"""Build a document section with table and links - only called if data exists"""
		html = f"""
		<div class="ops-section">
			<h3>{title} ({len(data)})</h3>
			<table class="ops-table"><thead><tr>
		"""
		
		for header in headers:
			html += f'<th>{header}</th>'
		html += '</tr></thead><tbody>'
		
		for d in data:
			row_data = row_builder(d)
			html += '<tr>'
			# Process each cell based on type (link or text)
			for cell in row_data:
				if isinstance(cell, tuple):
					cell_type, *cell_info = cell
					if cell_type == "link":
						url, text = cell_info
						html += f'<td><a href="{url}" class="ops-link" target="_blank">{text}</a></td>'
					else:
						html += f'<td>{cell_info[0]}</td>'
				else:
					html += f'<td>{cell}</td>'
			html += '</tr>'
		
		html += '</tbody></table></div>'
		return html

	@frappe.whitelist()
	def export_as_pdf(self):
		"""Generate PDF of the operations summary"""
		if not self.item_code:
			frappe.throw(_("Please select an Item Code first"))
		
		# Generate HTML first
		html = self.generate_operations_summary()
		
		# Use frappe's PDF generation
		from frappe.utils.pdf import get_pdf
		
		pdf = get_pdf(html, {
			"page-size": "A4",
			"orientation": "Landscape",
			"margin-top": "0.5in",
			"margin-right": "0.5in",
			"margin-bottom": "0.5in",
			"margin-left": "0.5in"
		})
		
		# Return the PDF as base64 for download
		frappe.local.response.filename = f"Item_Operations_Summary_{self.item_code}.pdf"
		frappe.local.response.filecontent = pdf
		frappe.local.response.type = "download"


@frappe.whitelist()
def generate_pdf(item_code=None):
	"""Standalone method to generate PDF for an item"""
	if not item_code:
		frappe.throw(_("Item Code is required"))
	
	# Get or create the single doctype instance
	doc = frappe.get_single("Item Operations Summary")
	doc.item_code = item_code
	
	# Validate and get item details
	if not frappe.db.exists("Item", item_code):
		frappe.throw(_("Item {0} does not exist").format(item_code))
	
	item = frappe.get_doc("Item", item_code)
	
	# Fetch all related documents
	sales_invoices = doc.get_sales_invoices()
	quotations = doc.get_quotations()
	delivery_notes = doc.get_delivery_notes()
	purchase_receipts = doc.get_purchase_receipts()
	purchase_invoices = doc.get_purchase_invoices()
	item_resumptions_replaced = doc.get_item_resumptions_as_original()
	item_resumptions_replacement = doc.get_item_resumptions_as_replacement()
	
	# Generate HTML for PDF (simpler version)
	html = build_pdf_html(
		item,
		sales_invoices,
		quotations,
		delivery_notes,
		purchase_receipts,
		purchase_invoices,
		item_resumptions_replaced,
		item_resumptions_replacement
	)
	
	# Use frappe's PDF generation with better options
	from frappe.utils.pdf import get_pdf
	
	try:
		pdf = get_pdf(html, {
			"page-size": "A4",
			"orientation": "Landscape",
			"margin-top": "15mm",
			"margin-right": "15mm",
			"margin-bottom": "15mm",
			"margin-left": "15mm",
			"encoding": "UTF-8",
			"no-outline": None,
			"print-media-type": None
		})
		
		# Return the PDF for download
		frappe.local.response.filename = f"Item_Operations_Summary_{item_code}.pdf"
		frappe.local.response.filecontent = pdf
		frappe.local.response.type = "download"
	except Exception as e:
		frappe.throw(_("Error generating PDF: {0}").format(str(e)))


def build_pdf_html(item, sales_invoices, quotations, delivery_notes,
					purchase_receipts, purchase_invoices,
					item_resumptions_replaced, item_resumptions_replacement):
	"""Build simplified HTML for PDF generation"""
	
	html = f"""
	<!DOCTYPE html>
	<html>
	<head>
		<meta charset="UTF-8">
		<style>
			body {{
				font-family: Arial, sans-serif;
				margin: 0;
				padding: 20px;
				background: white;
			}}
			.ops-header {{
				background: #5b7c99;
				color: white;
				padding: 15px 20px;
				margin-bottom: 20px;
			}}
			.ops-header h2 {{
				margin: 0 0 8px 0;
				font-size: 18px;
			}}
			.ops-header p {{
				margin: 3px 0;
				font-size: 12px;
			}}
			.ops-section {{
				page-break-inside: avoid;
				margin-bottom: 20px;
			}}
			.ops-section h3 {{
				color: #4a6fa5;
				margin: 15px 0 10px 0;
				padding-bottom: 8px;
				border-bottom: 2px solid #6c8aae;
				font-size: 16px;
			}}
			table {{
				width: 100%;
				border-collapse: collapse;
				margin-top: 10px;
				font-size: 11px;
			}}
			th {{
				background: #e8eef3;
				padding: 8px;
				text-align: left;
				font-weight: 600;
				border-bottom: 1px solid #6c8aae;
				color: #3d5a80;
			}}
			td {{
				padding: 6px 8px;
				border-bottom: 1px solid #e0e0e0;
			}}
			tr:nth-child(even) {{
				background: #f9f9f9;
			}}
			.alert-box {{
				background: #fff8e1;
				border-left: 4px solid #ffa726;
				padding: 10px;
				margin: 10px 0;
				font-size: 12px;
			}}
			.alert-box.replacement {{
				background: #e8f5e9;
				border-left-color: #66bb6a;
			}}
		</style>
	</head>
	<body>
		<div class="ops-header">
			<h2>{item.item_code} - {item.item_name}</h2>
			<p><strong>Item Group:</strong> {item.item_group} | <strong>UOM:</strong> {item.stock_uom} | <strong>Description:</strong> {item.description or 'N/A'}</p>
		</div>
	"""
	
	# Add sections only if data exists
	if sales_invoices:
		html += build_pdf_section("Sales Invoices", sales_invoices,
			["Document", "Date", "Customer", "Qty", "Rate", "Amount", "Total", "Status"],
			lambda d: [d.name, d.posting_date, d.customer, flt(d.qty, 2), flt(d.rate, 2), 
					   flt(d.amount, 2), flt(d.grand_total, 2), d.status])
	
	if quotations:
		html += build_pdf_section("Quotations", quotations,
			["Document", "Date", "Party", "Qty", "Rate", "Amount", "Total", "Status"],
			lambda d: [d.name, d.transaction_date, d.party_name, flt(d.qty, 2), flt(d.rate, 2),
					   flt(d.amount, 2), flt(d.grand_total, 2), d.status])
	
	if delivery_notes:
		html += build_pdf_section("Delivery Notes", delivery_notes,
			["Document", "Date", "Customer", "Qty", "Rate", "Amount", "Total", "Status"],
			lambda d: [d.name, d.posting_date, d.customer, flt(d.qty, 2), flt(d.rate, 2),
					   flt(d.amount, 2), flt(d.grand_total, 2), d.status])
	
	if purchase_receipts:
		html += build_pdf_section("Purchase Receipts", purchase_receipts,
			["Document", "Date", "Supplier", "Qty", "Rate", "Amount", "Total", "Status"],
			lambda d: [d.name, d.posting_date, d.supplier, flt(d.qty, 2), flt(d.rate, 2),
					   flt(d.amount, 2), flt(d.grand_total, 2), d.status])
	
	if purchase_invoices:
		html += build_pdf_section("Purchase Invoices", purchase_invoices,
			["Document", "Date", "Supplier", "Qty", "Rate", "Amount", "Total", "Status"],
			lambda d: [d.name, d.posting_date, d.supplier, flt(d.qty, 2), flt(d.rate, 2),
					   flt(d.amount, 2), flt(d.grand_total, 2), d.status])
	
	# Item Resumptions - Replaced (for PDF - plain text, no links)
	if item_resumptions_replaced:
		html += f"""
		<div class="ops-section">
			<h3>Item Replacement History - This Item Was REPLACED ({len(item_resumptions_replaced)})</h3>
			<div class="alert-box">
				<strong>Note:</strong> Records where this item was the ORIGINAL item that was replaced.
			</div>
			<table>
				<thead>
					<tr>
						<th>Document</th>
						<th>Date</th>
						<th>Customer</th>
						<th>Original Invoice</th>
						<th>Return Invoice</th>
						<th>Replaced With</th>
						<th>Journal Entry</th>
					</tr>
				</thead>
				<tbody>
		"""
		for d in item_resumptions_replaced:
			replacement_item = f"<strong>{d.replacement_item or 'N/A'}</strong> - {d.replacement_item_name or ''}"
			html += f"""
				<tr>
					<td>{d.name}</td>
					<td>{d.posting_date}</td>
					<td>{d.customer}</td>
					<td>{d.positive_invoice}</td>
					<td>{d.negative_invoice}</td>
					<td>{replacement_item}</td>
					<td>{d.journal_entry or 'N/A'}</td>
				</tr>
			"""
		html += "</tbody></table></div>"
	
	# Item Resumptions - Replacement (for PDF - plain text, no links)
	if item_resumptions_replacement:
		html += f"""
		<div class="ops-section">
			<h3>Item Replacement History - This Item Was Used as REPLACEMENT ({len(item_resumptions_replacement)})</h3>
			<div class="alert-box replacement">
				<strong>Note:</strong> Records where this item was the NEW/REPLACEMENT item.
			</div>
			<table>
				<thead>
					<tr>
						<th>Document</th>
						<th>Date</th>
						<th>Customer</th>
						<th>Original Invoice</th>
						<th>Return Invoice</th>
						<th>Replaced Item</th>
						<th>Journal Entry</th>
					</tr>
				</thead>
				<tbody>
		"""
		for d in item_resumptions_replacement:
			original_item = f"<strong>{d.original_item or 'N/A'}</strong> - {d.original_item_name or ''}"
			html += f"""
				<tr>
					<td>{d.name}</td>
					<td>{d.posting_date}</td>
					<td>{d.customer}</td>
					<td>{d.positive_invoice}</td>
					<td>{d.negative_invoice}</td>
					<td>{original_item}</td>
					<td>{d.journal_entry or 'N/A'}</td>
				</tr>
			"""
		html += "</tbody></table></div>"
	
	html += "</body></html>"
	return html


def build_pdf_section(title, data, headers, row_builder):
	"""Build a simple section for PDF"""
	html = f"""
	<div class="ops-section">
		<h3>{title} ({len(data)})</h3>
		<table>
			<thead><tr>
	"""
	
	for header in headers:
		html += f"<th>{header}</th>"
	
	html += "</tr></thead><tbody>"
	
	for d in data:
		row_data = row_builder(d)
		html += "<tr>"
		for cell in row_data:
			html += f"<td>{cell}</td>"
		html += "</tr>"
	
	html += "</tbody></table></div>"
	return html

