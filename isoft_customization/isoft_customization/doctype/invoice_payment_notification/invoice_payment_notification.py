# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import io
import re
import frappe
from PyPDF2 import PdfFileReader, PdfFileWriter
from email.utils import formataddr
from frappe import _
from frappe.desk.reportview import get_match_cond
from frappe.model.document import Document
from frappe.utils import add_days, flt, format_date, getdate, nowdate, today, validate_email_address
from frappe.utils.jinja import validate_template
from frappe.utils.pdf import get_pdf
from frappe.utils.safe_exec import get_safe_globals
from frappe.www.printview import get_print_style

from erpnext import get_company_currency
from erpnext.accounts.party import get_party_account_currency
from erpnext.accounts.report.general_ledger.general_ledger import execute as get_soa
from erpnext.accounts.report.accounts_receivable_summary.accounts_receivable_summary import execute as get_ageing


class InvoicePaymentNotification(Document):
	def _split_emails(self, value):
		"""Split comma/semicolon/newline-separated emails into a clean list."""
		if not value:
			return []
		parts = re.split(r"[,\n;]+", value)
		return [email.strip() for email in parts if email.strip()]

	def _get_owner_email(self, doc):
		"""Return owner email for the reference document if available."""
		if not doc or not getattr(doc, "owner", None):
			return None
		return frappe.db.get_value("User", doc.owner, "email") or None

	def _get_account_manager_email(self, customer):
		"""Return the account manager's email for the given customer."""
		if not self.cc_account_manager:
			return None
		account_manager = frappe.db.get_value("Customer", customer, "account_manager")
		if not account_manager:
			return None
		return frappe.db.get_value("User", account_manager, "email") or None

	def _dedupe_emails(self, recipients, cc, bcc):
		"""De-duplicate emails across recipients, cc, and bcc."""
		def unique(seq):
			seen = set()
			out = []
			for item in seq:
				key = item.strip().lower()
				if key and key not in seen:
					seen.add(key)
					out.append(item.strip())
			return out

		recipients = unique(recipients)
		cc = [email for email in unique(cc) if email.strip().lower() not in {e.lower() for e in recipients}]
		bcc = [
			email
			for email in unique(bcc)
			if email.strip().lower() not in {e.lower() for e in recipients + cc}
		]
		return recipients, cc, bcc

	def validate(self):
		"""Validate the notification settings"""
		self.set_reference_doctype()

		if not self.subject:
			self.subject = "Payment Receipt for {{ customer.customer_name }}"
		if not self.body:
			self.body = "Dear {{ customer.customer_name }},<br><br>Thank you for your payment. Please find attached your invoice(s) and account statement."

		# Validate Jinja templates
		validate_template(self.subject)
		validate_template(self.body)
		if self.email_signature:
			validate_template(self.email_signature)

		self.validate_condition()

		# Validate customer filters
		if self.customer_collection and self.customer_collection != "Specific Customers" and not self.collection_name:
			frappe.throw(_("Please select a Collection Name for the selected Customer filter."))
		if self.customer_collection == "Specific Customers" and not self.customers:
			frappe.throw(_("Please select customers."))

		# Set default ledger dates if include_ledger is checked
		if self.include_ledger:
			self.ledger_from_date = self.get_ledger_from_date()

	@frappe.whitelist()
	def fetch_customers_for_collection(self):
		"""Fetch customers based on the collection criteria"""
		if not self.customer_collection or self.customer_collection == "Specific Customers":
			frappe.throw(_("Customer filter is not set for dynamic collection."))

		customer_list = self.get_customers_for_collection()
		self.customers = []

		for customer in customer_list:
			email_id = customer.email_id or self.get_customer_email(customer.name)
			if not email_id:
				continue

			self.append("customers", {
				"customer": customer.name,
				"customer_name": customer.customer_name,
				"billing_email": email_id
			})

		frappe.msgprint(_("Fetched {0} customers").format(len(self.customers)))

	def set_reference_doctype(self):
		"""Ensure reference doctype is set for backward compatibility."""
		if self.reference_doctype:
			return
		self.reference_doctype = "Payment Entry"

	def validate_condition(self):
		if not self.condition:
			return

		reference_doctype = self.reference_doctype or "Payment Entry"
		temp_doc = frappe.new_doc(reference_doctype)
		try:
			frappe.safe_eval(self.condition, None, self.get_condition_context(temp_doc))
		except Exception:
			frappe.throw(_("The Condition '{0}' is invalid").format(self.condition))

	def get_condition_context(self, reference_doc):
		return {
			"doc": reference_doc,
			"nowdate": nowdate,
			"frappe": frappe._dict(utils=get_safe_globals().get("frappe").get("utils")),
		}

	def get_template_context(self, reference_doc, customer_doc, invoices):
		"""Match Notification context: doc is the triggering document."""
		return {
			"doc": reference_doc,
			"notification": self,
			"customer": customer_doc,
			"payment_entry": reference_doc if reference_doc.doctype == "Payment Entry" else None,
			"sales_invoice": reference_doc if reference_doc.doctype == "Sales Invoice" else None,
			"reference_doc": reference_doc,
			"invoices": invoices,
			"nowdate": nowdate,
			"frappe": frappe._dict(utils=get_safe_globals().get("frappe").get("utils")),
		}

	def get_customers_to_send(self):
		"""Get list of customers to send emails to"""
		customers = []
		if self.customer_collection == "Specific Customers":
			for row in self.customers:
				billing_email = row.billing_email or self.get_customer_email(row.customer)
				if not billing_email:
					continue
				customers.append({
					"name": row.customer,
					"email": billing_email
				})
			return customers

		for customer in self.get_customers_for_collection():
			email_id = customer.email_id or self.get_customer_email(customer.name)
			if not email_id:
				continue
			customers.append({
				"name": customer.name,
				"email": email_id
			})

		return customers

	def get_customers_for_collection(self):
		"""Return customers matching current collection (dynamic)."""
		if self.customer_collection == "Customer Group":
			return self.get_customers_for_tree_filter("customer_group", "Customer Group")
		if self.customer_collection == "Territory":
			return self.get_customers_for_tree_filter("territory", "Territory")

		filters = {"disabled": 0}
		customer_names = None

		if self.customer_collection == "Sales Partner":
			filters["default_sales_partner"] = self.collection_name
		elif self.customer_collection == "Sales Person":
			customer_names = self.get_customer_names_for_sales_person()
		elif not self.customer_collection:
			pass
		else:
			return []

		if customer_names is not None:
			if not customer_names:
				return []
			filters["name"] = ["in", customer_names]

		return frappe.get_all("Customer", filters=filters, fields=["name", "customer_name", "email_id"])

	def get_tree_names(self, doctype, name):
		"""Return list of tree node names including children."""
		if not name:
			return []
		node = frappe.get_doc(doctype, name)
		return [
			d.name
			for d in frappe.get_list(
				doctype,
				filters=[["lft", ">=", node.lft], ["rgt", "<=", node.rgt]],
				fields=["name"],
				order_by="lft asc, rgt desc",
			)
		]

	def get_customers_for_tree_filter(self, fieldname, doctype):
		"""Return customers for tree-based filters (includes children)."""
		names = self.get_tree_names(doctype, self.collection_name)
		if not names:
			return []
		return frappe.get_all(
			"Customer",
			filters=[["disabled", "=", 0], [fieldname, "in", names]],
			fields=["name", "customer_name", "email_id"],
		)

	def get_customer_names_for_sales_person(self):
		"""Get customers linked to a sales person through Sales Team."""
		if not self.collection_name:
			return []
		sales_team_customers = frappe.get_all(
			"Sales Team",
			filters={"sales_person": self.collection_name, "parenttype": "Customer"},
			fields=["parent"],
			distinct=True
		)
		return [d.parent for d in sales_team_customers]

	def customer_matches_filters(self, customer):
		"""Check if a customer matches the current filter settings."""
		if self.customer_collection == "Specific Customers":
			return any(row.customer == customer for row in self.customers)

		if not self.customer_collection:
			return True

		customer_info = frappe.db.get_value(
			"Customer",
			customer,
			["customer_group", "territory", "default_sales_partner"],
			as_dict=True
		)
		if not customer_info:
			return False

		if self.customer_collection == "Customer Group":
			return customer_info.customer_group in self.get_tree_names("Customer Group", self.collection_name)
		if self.customer_collection == "Territory":
			return customer_info.territory in self.get_tree_names("Territory", self.collection_name)
		if self.customer_collection == "Sales Partner":
			return customer_info.default_sales_partner == self.collection_name
		if self.customer_collection == "Sales Person":
			return frappe.db.exists(
				"Sales Team",
				{"parenttype": "Customer", "parent": customer, "sales_person": self.collection_name}
			)

		return False

	def get_customer_email(self, customer):
		"""Get customer email, optionally from linked contact."""
		email_id = frappe.db.get_value("Customer", customer, "email_id")
		if email_id:
			return email_id
		if self.allow_contact_email:
			return self.get_linked_contact_email(customer)
		return None

	def get_linked_contact_email(self, customer):
		"""Return contact email via dynamic links (prefers primary, then billing)."""
		linked_email = frappe.db.sql(
			"""
			SELECT
				email.email_id
			FROM
				`tabContact Email` AS email
			JOIN
				`tabDynamic Link` AS link
			ON
				email.parent=link.parent
			JOIN
				`tabContact` AS contact
			ON
				contact.name=link.parent
			WHERE
				link.link_doctype='Customer'
				and link.link_name=%s
				{mcond}
			ORDER BY
				contact.is_primary_contact DESC,
				contact.is_billing_contact DESC,
				contact.modified DESC
			""".format(
				mcond=get_match_cond("Contact")
			),
			customer,
		)
		if not linked_email or linked_email[0][0] is None:
			return None
		return linked_email[0][0]

	def get_ledger_from_date(self):
		"""Resolve ledger from date based on settings."""
		mode = self.ledger_from_date_mode or "Start of Current Month"
		current_date = getdate(today())
		if mode == "Custom Date":
			if self.ledger_from_date:
				return getdate(self.ledger_from_date)
			return getdate(add_days(today(), -90))
		if mode == "Start of Current Year":
			return current_date.replace(month=1, day=1)
		if mode == "Current Date":
			return current_date
		# Start of Current Month (default)
		return current_date.replace(day=1)

	def remove_trailing_blank_page(self, pdf_content):
		"""Remove an extra blank last page from generated PDFs (wkhtmltopdf)."""
		try:
			reader = PdfFileReader(io.BytesIO(pdf_content), overwriteWarnings=False)
			total_pages = reader.getNumPages()
			if total_pages <= 1:
				return pdf_content

			last_page = reader.getPage(total_pages - 1)
			text = (last_page.extract_text() or "").strip()
			resources = last_page.get("/Resources") or {}
			xobject = resources.get("/XObject") or {}

			if text or xobject:
				return pdf_content

			writer = PdfFileWriter()
			for page_index in range(total_pages - 1):
				writer.addPage(reader.getPage(page_index))

			output = io.BytesIO()
			writer.write(output)
			return output.getvalue()
		except Exception:
			return pdf_content

	def get_sender_address(self):
		"""Resolve sender to a valid email address."""
		if not self.sender:
			return None

		try:
			validated_sender = validate_email_address(self.sender)
			if validated_sender:
				return validated_sender
		except Exception:
			pass

		email_id = frappe.db.get_value("Email Account", self.sender, "email_id")
		if email_id:
			return email_id

		return None

	def get_paid_invoices(self, customer, payment_entry=None):
		"""Get paid invoices for a customer, optionally filtered by payment entry"""
		filters = {
			"docstatus": 1,
			"customer": customer,
			"company": self.company
		}

		# If payment entry is provided, get only invoices paid in that payment
		if payment_entry:
			payment_doc = frappe.get_doc("Payment Entry", payment_entry)
			invoice_list = []
			for ref in payment_doc.references:
				if ref.reference_doctype == "Sales Invoice":
					invoice_list.append(ref.reference_name)
			
			if invoice_list:
				filters["name"] = ["in", invoice_list]
			else:
				return []

		invoices = frappe.get_all(
			"Sales Invoice",
			filters=filters,
			fields=["name", "posting_date", "grand_total", "outstanding_amount", "status"],
			order_by="posting_date desc"
		)

		return invoices

	def get_customer_ledger_pdf(self, customer):
		"""Generate customer statement PDF similar to Process Statement of Accounts"""
		if not self.include_ledger:
			return None

		template_path = (
			"erpnext/accounts/doctype/process_statement_of_accounts/process_statement_of_accounts.html"
		)
		base_template_path = "frappe/www/printview.html"

		customer_doc = frappe.get_doc("Customer", customer)
		presentation_currency = (
			get_party_account_currency("Customer", customer, self.company)
			or get_company_currency(self.company)
		)
		letter_head = None
		if self.letter_head:
			from frappe.www.printview import get_letter_head

			letter_head = get_letter_head(frappe.get_doc("Letter Head", self.letter_head), 0)

		filters = frappe._dict(
			{
				"from_date": getdate(self.get_ledger_from_date()),
				"to_date": getdate(today()),
				"company": self.company,
				"party_type": "Customer",
				"party": [customer],
				"party_name": [customer_doc.customer_name],
				"presentation_currency": presentation_currency,
				"group_by": self.ledger_group_by or "Group by Voucher (Consolidated)",
				"currency": presentation_currency,
				"show_opening_entries": 0,
				"include_default_book_entries": 0,
				"tax_id": customer_doc.tax_id if customer_doc.tax_id else None,
			}
		)

		# Get ledger data
		try:
			col, res = get_soa(filters)
		except Exception as e:
			frappe.log_error(f"Error fetching ledger for {customer}: {str(e)}")
			return None

		# Get ageing data if required
		ageing_data = None
		if self.include_ageing:
			ageing_filters = frappe._dict(
				{
					"company": self.company,
					"report_date": getdate(today()),
					"ageing_based_on": self.ageing_based_on or "Due Date",
					"range1": 30,
					"range2": 60,
					"range3": 90,
					"range4": 120,
					"customer": customer,
				}
			)
			try:
				ageing_col, ageing_res = get_ageing(ageing_filters)
				ageing_data = ageing_res[0] if ageing_res else None
			except Exception:
				pass
		# Suppress the ledger only when the customer's actual closing balance is
		# zero. Previously this tested `len(res) <= 3`, which used "no transactions
		# in the [ledger_from_date, today] window" as a proxy for "zero balance".
		# That wrongly skipped customers who carry a real (often negative/credit)
		# balance but simply had no postings inside the window.
		if not self.include_zero_balance_ledger:
			if not res or flt(self.get_ledger_closing_balance(res), 2) == 0:
				return None

		html = frappe.render_template(
			template_path,
			{
				"filters": filters,
				"data": res,
				"ageing": ageing_data if (self.include_ageing and ageing_data) else None,
				"letter_head": letter_head,
				"terms_and_conditions": None,
			},
		)
		html = frappe.render_template(
			base_template_path,
			{"body": html, "css": get_print_style(), "title": f"Statement For {customer}"},
		)

		return get_pdf(html, {"orientation": self.orientation or "Portrait"})

	def get_ledger_closing_balance(self, res):
		"""Return the net closing balance (debit - credit) from GL report rows.

		The General Ledger report always ends with a "Closing (Opening + Total)"
		row whose balance already includes the opening balance, so it reflects the
		customer's true balance as of `to_date` even when there were no postings
		inside the report window.
		"""
		for row in reversed(res):
			if row and (row.get("debit") is not None or row.get("credit") is not None):
				return flt(row.get("debit")) - flt(row.get("credit"))
		return 0.0

	def get_ledger_html(self, customer, columns, data, ageing_data=None):
		"""Generate HTML for ledger statement"""
		from frappe.www.printview import get_letter_head

		letter_head = ""
		if self.letter_head:
			letter_head = get_letter_head(frappe.get_doc("Letter Head", self.letter_head), 0) or ""

		# Build the HTML
		html = f"""
		<html>
		<head>
			<style>
				{get_print_style()}
				table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
				th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
				th {{ background-color: #f2f2f2; }}
				.header {{ text-align: center; margin-bottom: 20px; }}
				.ageing-summary {{ margin: 20px 0; }}
			</style>
		</head>
		<body>
			{letter_head}
			<div class="header">
				<h2>Customer Ledger Statement</h2>
				<p>Customer: {customer}</p>
		<p>Period: {format_date(self.get_ledger_from_date())} to {format_date(today())}</p>
			</div>
		"""

		# Add ageing summary if available
		if ageing_data and self.include_ageing:
			html += """
			<div class="ageing-summary">
				<h3>Ageing Summary</h3>
				<table>
					<tr>
						<th>Current</th>
						<th>30-60</th>
						<th>60-90</th>
						<th>90-120</th>
						<th>120+</th>
					</tr>
					<tr>
			"""
			# Add ageing data (simplified - adjust based on actual column structure)
			html += "</tr></table></div>"

		# Add ledger table
		html += "<h3>Transaction Details</h3><table><tr>"
		
		# Add column headers
		for col in columns:
			html += f"<th>{col.get('label', '')}</th>"
		html += "</tr>"

		# Add data rows
		for row in data:
			html += "<tr>"
			for col in columns:
				fieldname = col.get('fieldname')
				value = row.get(fieldname, '')
				html += f"<td>{value}</td>"
			html += "</tr>"

		html += "</table></body></html>"
		return html

	def send_notification_for_payment(self, payment_entry_name):
		"""Send notification emails for a specific payment entry"""
		payment_entry = frappe.get_doc("Payment Entry", payment_entry_name)
		
		# Get customer from payment entry
		if payment_entry.party_type != "Customer":
			return

		if self.condition and not frappe.safe_eval(
			self.condition, None, self.get_condition_context(payment_entry)
		):
			return

		customer = payment_entry.party

		if not self.customer_matches_filters(customer):
			return

		billing_email = None
		if self.customer_collection == "Specific Customers":
			for row in self.customers:
				if row.customer == customer:
					billing_email = row.billing_email or self.get_customer_email(customer)
					break
		else:
			billing_email = self.get_customer_email(customer)

		if not billing_email:
			frappe.logger("invoice_payment_notification").info(
				f"No email found for customer {customer}; skipping notification."
			)
			return

		# Get paid invoices from this payment
		invoices = self.get_paid_invoices(customer, payment_entry_name)

		# Prepare attachments
		attachments = []

		# Attach Payment Entry print
		try:
			print_format = self.print_format or "Standard"
			payment_pdf_content = frappe.get_print(
				"Payment Entry",
				payment_entry.name,
				print_format=print_format,
				as_pdf=True,
				pdf_options={"orientation": "Portrait"},
			)
			payment_pdf_content = self.remove_trailing_blank_page(payment_pdf_content)
			attachments.append({
				"fname": f"{payment_entry.name}.pdf",
				"fcontent": payment_pdf_content,
				"content_type": "application/pdf",
			})
		except Exception as e:
			frappe.log_error(
				f"Error attaching payment entry {payment_entry.name}: {str(e)}",
				"Invoice Payment Notification"
			)

		# Attach ledger statement
		if self.include_ledger:
			try:
				ledger_pdf = self.get_customer_ledger_pdf(customer)
				if ledger_pdf:
					attachments.append({
						"fname": f"{customer}_Statement.pdf",
						"fcontent": ledger_pdf,
						"content_type": "application/pdf",
					})
			except Exception as e:
				frappe.log_error(
					f"Error generating ledger for {customer}: {str(e)}",
					"Invoice Payment Notification"
				)

		# Prepare email context
		customer_doc = frappe.get_doc("Customer", customer)
		context = self.get_template_context(payment_entry, customer_doc, invoices)

		# Render subject and body
		subject = frappe.render_template(self.subject, context)
		message = frappe.render_template(self.body, context)
		if self.email_signature:
			message = f"{message}<br><br>{frappe.render_template(self.email_signature, context)}"

		# Prepare recipients
		recipients = [billing_email] if billing_email else []
		cc = self._split_emails(self.cc_to)
		bcc = self._split_emails(self.bcc_to)
		if self.cc_document_owner:
			owner_email = self._get_owner_email(payment_entry)
			if owner_email:
				cc.append(owner_email)

		am_email = self._get_account_manager_email(customer)
		if am_email:
			if self.cc_account_manager == "CC":
				cc.append(am_email)
			elif self.cc_account_manager == "BCC":
				bcc.append(am_email)

		recipients, cc, bcc = self._dedupe_emails(recipients, cc, bcc)

		if not recipients:
			return

		# Send email
		try:
			frappe.enqueue(
				queue="short",
				method=frappe.sendmail,
				recipients=recipients,
				sender=self.get_sender_address(),
				cc=cc,
				bcc=bcc,
				subject=subject,
				message=message,
				attachments=attachments,
				reference_doctype="Payment Entry",
				reference_name=payment_entry_name,
				expose_recipients="header",
				now=False
			)
			
			
		except Exception as e:
			frappe.log_error(
				f"Error sending email to {customer}: {str(e)}",
				"Invoice Payment Notification"
			)

	def send_notification_for_sales_invoice(self, sales_invoice_name):
		"""Send notification emails for a specific sales invoice"""
		sales_invoice = frappe.get_doc("Sales Invoice", sales_invoice_name)

		if self.condition and not frappe.safe_eval(
			self.condition, None, self.get_condition_context(sales_invoice)
		):
			return

		customer = sales_invoice.customer

		if not self.customer_matches_filters(customer):
			return

		billing_email = None
		if self.customer_collection == "Specific Customers":
			for row in self.customers:
				if row.customer == customer:
					billing_email = row.billing_email or self.get_customer_email(customer)
					break
		else:
			billing_email = self.get_customer_email(customer)

		if not billing_email:
			frappe.logger("invoice_payment_notification").info(
				f"No email found for customer {customer}; skipping notification."
			)
			return

		attachments = []

		try:
			print_format = self.print_format or "Standard"
			invoice_pdf_content = frappe.get_print(
				"Sales Invoice",
				sales_invoice.name,
				print_format=print_format,
				as_pdf=True,
				pdf_options={"orientation": "Portrait"},
			)
			invoice_pdf_content = self.remove_trailing_blank_page(invoice_pdf_content)
			attachments.append({
				"fname": f"{sales_invoice.name}.pdf",
				"fcontent": invoice_pdf_content,
				"content_type": "application/pdf",
			})
		except Exception as e:
			frappe.log_error(
				f"Error attaching invoice {sales_invoice.name}: {str(e)}",
				"Invoice Payment Notification"
			)

		if self.include_ledger:
			try:
				ledger_pdf = self.get_customer_ledger_pdf(customer)
				if ledger_pdf:
					attachments.append({
						"fname": f"{customer}_Statement.pdf",
						"fcontent": ledger_pdf,
						"content_type": "application/pdf",
					})
			except Exception as e:
				frappe.log_error(
					f"Error generating ledger for {customer}: {str(e)}",
					"Invoice Payment Notification"
				)

		customer_doc = frappe.get_doc("Customer", customer)
		context = self.get_template_context(sales_invoice, customer_doc, [sales_invoice])

		subject = frappe.render_template(self.subject, context)
		message = frappe.render_template(self.body, context)
		if self.email_signature:
			message = f"{message}<br><br>{frappe.render_template(self.email_signature, context)}"

		recipients = [billing_email] if billing_email else []
		cc = self._split_emails(self.cc_to)
		bcc = self._split_emails(self.bcc_to)
		if self.cc_document_owner:
			owner_email = self._get_owner_email(sales_invoice)
			if owner_email:
				cc.append(owner_email)

		am_email = self._get_account_manager_email(customer)
		if am_email:
			if self.cc_account_manager == "CC":
				cc.append(am_email)
			elif self.cc_account_manager == "BCC":
				bcc.append(am_email)

		recipients, cc, bcc = self._dedupe_emails(recipients, cc, bcc)

		if not recipients:
			return

		try:
			frappe.enqueue(
				queue="short",
				method=frappe.sendmail,
				recipients=recipients,
				sender=self.get_sender_address(),
				cc=cc,
				bcc=bcc,
				subject=subject,
				message=message,
				attachments=attachments,
				reference_doctype="Sales Invoice",
				reference_name=sales_invoice_name,
				expose_recipients="header",
				now=False
			)


		except Exception as e:
			frappe.log_error(
				f"Error sending email to {customer}: {str(e)}",
				"Invoice Payment Notification"
			)


@frappe.whitelist()
def send_manual_notification(docname, reference_name=None, reference_doctype=None, payment_entry=None):
	"""Manually trigger notification for testing or manual sending"""
	doc = frappe.get_doc("Invoice Payment Notification", docname)
	
	if not doc.enabled:
		frappe.throw(_("This notification is disabled"))

	if payment_entry:
		reference_doctype = "Payment Entry"
		reference_name = payment_entry

	if reference_doctype and reference_name:
		if reference_doctype == "Sales Invoice":
			doc.send_notification_for_sales_invoice(reference_name)
		else:
			doc.send_notification_for_payment(reference_name)
	else:
		# Send to all customers in the list
		customers = doc.get_customers_to_send()
		for customer in customers:
			if (doc.reference_doctype or "Payment Entry") == "Sales Invoice":
				latest_invoice = frappe.get_all(
					"Sales Invoice",
					filters={
						"customer": customer["name"],
						"docstatus": 1,
						"company": doc.company
					},
					fields=["name"],
					order_by="posting_date desc",
					limit=1
				)

				if latest_invoice:
					doc.send_notification_for_sales_invoice(latest_invoice[0].name)
			else:
				# Get the latest payment for this customer
				latest_payment = frappe.get_all(
					"Payment Entry",
					filters={
						"party_type": "Customer",
						"party": customer["name"],
						"docstatus": 1,
						"company": doc.company
					},
					fields=["name"],
					order_by="posting_date desc",
					limit=1
				)
				
				if latest_payment:
					doc.send_notification_for_payment(latest_payment[0].name)

	return True


def trigger_notification_on_payment_submit(payment_entry, method=None):
	"""Hook function to trigger notifications when payment entry is submitted"""
	if payment_entry.party_type != "Customer":
		return

	# Get all enabled notifications for this company
	notifications = frappe.get_all(
		"Invoice Payment Notification",
		filters={
			"enabled": 1,
			"company": payment_entry.company,
			"reference_doctype": "Payment Entry"
		},
		fields=["name"]
	)

	for notification in notifications:
		try:
			doc = frappe.get_doc("Invoice Payment Notification", notification.name)
			if (doc.reference_doctype or "Payment Entry") == "Payment Entry":
				doc.send_notification_for_payment(payment_entry.name)
		except Exception as e:
			frappe.log_error(
				f"Error in notification {notification.name}: {str(e)}",
				"Invoice Payment Notification"
			)


def trigger_notification_on_sales_invoice_submit(sales_invoice, method=None):
	"""Hook function to trigger notifications when sales invoice is submitted"""
	if not sales_invoice.customer:
		return

	notifications = frappe.get_all(
		"Invoice Payment Notification",
		filters={
			"enabled": 1,
			"company": sales_invoice.company,
			"reference_doctype": "Sales Invoice"
		},
		fields=["name"]
	)

	for notification in notifications:
		try:
			doc = frappe.get_doc("Invoice Payment Notification", notification.name)
			if (doc.reference_doctype or "Sales Invoice") == "Sales Invoice":
				doc.send_notification_for_sales_invoice(sales_invoice.name)
		except Exception as e:
			frappe.log_error(
				f"Error in notification {notification.name}: {str(e)}",
				"Invoice Payment Notification"
			)
