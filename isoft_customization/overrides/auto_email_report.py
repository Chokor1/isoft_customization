"""Auto Email Report with a CC field (isoft_customization.auto_email_report_cc)."""
import frappe
from frappe.email.doctype.auto_email_report.auto_email_report import AutoEmailReport

from isoft_customization.auto_email_report_cc import FIELD, clean_cc


class IsoftAutoEmailReport(AutoEmailReport):
	def validate(self):
		super(IsoftAutoEmailReport, self).validate()
		if self.meta.has_field(FIELD):
			self.set(FIELD, "\n".join(clean_cc(self.get(FIELD))))

	def send(self):
		cc = clean_cc(self.get(FIELD)) if self.meta.has_field(FIELD) else []
		if not cc:
			return super(IsoftAutoEmailReport, self).send()
		# frappe's send() builds the mail itself; hand it the Cc on the way out
		sendmail = frappe.sendmail

		def sendmail_with_cc(*args, **kwargs):
			kwargs.setdefault("cc", cc)
			return sendmail(*args, **kwargs)

		frappe.sendmail = sendmail_with_cc
		try:
			return super(IsoftAutoEmailReport, self).send()
		finally:
			frappe.sendmail = sendmail
