from frappe.model.document import Document
import frappe
from frappe.utils import flt, nowdate
from erpnext.accounts.utils import get_outstanding_invoices_by_outstanding_amount  # Make sure this exists

class InvoiceOutstandingReconciliation(Document):
    @frappe.whitelist()
    def reconcile(self):
        selected_invoices = [row for row in self.invoices if row.select]

        positives = []
        negatives = []

        for row in selected_invoices:
            amt = flt(row.outstanding_amount)
            if amt > 0:
                positives.append(row)
            elif amt < 0:
                negatives.append(row)

        journal_entries = []

        for pos in positives:
            for neg in negatives:
                if flt(neg.outstanding_amount) == 0:
                    continue

                recon_amount = min(flt(pos.outstanding_amount), abs(flt(neg.outstanding_amount)))

                if recon_amount == 0:
                    continue

                journal_entries.append({
                    "account": self.receivable_payable_account,
                    "party_type": self.party_type,
                    "party": self.party,
                    "reference_type": pos.invoice_type if self.party_type == 'Customer' else neg.invoice_type,
                    "reference_name": pos.invoice_number if self.party_type == 'Customer' else neg.invoice_number,
                    "credit_in_account_currency": recon_amount,
                })
                journal_entries.append({
                    "account": self.receivable_payable_account,
                    "party_type": self.party_type,
                    "party": self.party,
                    "reference_type": neg.invoice_type if self.party_type == 'Customer' else pos.invoice_type,
                    "reference_name": neg.invoice_number if self.party_type == 'Customer' else pos.invoice_number,
                    "debit_in_account_currency": recon_amount,
                })

                pos.outstanding_amount -= recon_amount
                neg.outstanding_amount += recon_amount

                if flt(pos.outstanding_amount) <= 0:
                    break

        if journal_entries:
            je = frappe.new_doc("Journal Entry")
            je.voucher_type = "Journal Entry"
            je.posting_date = nowdate()
            je.company = self.company
            je.is_invoice_outstanding_reconciliation = 1
            je.remark = f"Internal invoice netting for {self.party}"

            for entry in journal_entries:
                je.append("accounts", entry)

            je.insert()
            je.submit()
            
            return je.name
        else:
            return None


    @frappe.whitelist()
    def get_invoice_entries(self):
        condition = " and company = '{0}' ".format(self.company)

        if self.get("cost_center"):
            condition += " and cost_center = '{0}' ".format(self.cost_center)

        non_reconciled_invoices = get_outstanding_invoices_by_outstanding_amount(
            self.party_type, self.party, self.receivable_payable_account, self.company, condition=condition
        )

        self.add_invoice_entries(non_reconciled_invoices)

    def add_invoice_entries(self, non_reconciled_invoices):
        self.set("invoices", [])

        for entry in non_reconciled_invoices:
            inv = self.append("invoices", {})
            inv.invoice_type = entry.get("voucher_type")
            inv.invoice_number = entry.get("voucher_no")
            inv.invoice_date = entry.get("posting_date")
            inv.amount = flt(entry.get("invoice_amount"))
            inv.currency = entry.get("currency")
            inv.outstanding_amount = flt(entry.get("outstanding_amount"))

