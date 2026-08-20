import frappe
from frappe.utils.pdf import get_pdf
import json
from frappe.model.document import Document
from collections import defaultdict
import math

class SalesAndPurchaseTaxSummaryExportTool(Document):
    pass

@frappe.whitelist()
def generate_tax_summary_pdf(from_date, to_date):
    try:
        doc = frappe.get_doc("Sales And Purchase Tax Summary Export Tool")

        def get_totals_and_taxes(doctype_invoice, doctype_taxes, is_return_flag):
            # Get totals summary
            totals = frappe.db.sql(f"""
                SELECT
                    IFNULL(SUM(total),0) as total_before_discount,
                    IFNULL(SUM(discount_amount),0) as total_discount,
                    IFNULL(SUM(net_total),0) as net_total,
                    IFNULL(SUM(total_taxes_and_charges),0) as total_taxes_and_charges,
                    IFNULL(SUM(grand_total),0) as grand_total
                FROM `{doctype_invoice}`
                WHERE posting_date BETWEEN %s AND %s
                AND docstatus = 1
                AND is_return = %s
            """, (from_date, to_date, is_return_flag), as_dict=1)[0]

            # Aggregate taxes from item_wise_tax_detail JSON field
            tax_summary = defaultdict(lambda: {"amount": 0.0})

            tax_rows = frappe.db.sql(f"""
        SELECT item_wise_tax_detail
        FROM `{doctype_taxes}`
        WHERE parent IN (
            SELECT name FROM `{doctype_invoice}`
            WHERE posting_date BETWEEN %s AND %s
            AND docstatus = 1
            AND is_return = %s
        )
    """, (from_date, to_date, is_return_flag))

            for (tax_detail_json,) in tax_rows:
                if not tax_detail_json:
                    continue
                try:
                    tax_detail = json.loads(tax_detail_json)
                except (json.JSONDecodeError, TypeError):
                    continue
                
                for _, tax_info in tax_detail.items():
                    try:
                        # Handle different possible formats of tax_info
                        if isinstance(tax_info, (list, tuple)) and len(tax_info) >= 2:
                            percent, amount = tax_info[0], tax_info[1]
                        elif isinstance(tax_info, dict):
                            percent = tax_info.get('tax_rate', tax_info.get('percent', 0))
                            amount = tax_info.get('tax_amount', tax_info.get('amount', 0))
                        else:
                            continue
                            
                        # Validate and convert values
                        percent = float(percent) if percent is not None else 0.0
                        amount = float(amount) if amount is not None else 0.0
                        
                        # Round percentage to 2 decimal places to avoid floating point precision issues
                        rounded_percent = round(percent, 2)
                        entry = tax_summary[rounded_percent]
                        entry["amount"] += amount
                        
                    except (ValueError, TypeError):
                        continue

            # Convert to list and sort by percentage
            taxes_list = [
                {"percent": percent, "amount": vals["amount"]}
                for percent, vals in sorted(tax_summary.items())
            ]

            return totals, taxes_list

        summary = {}

        # Sales Invoice (normal sales, is_return=0)
        totals, taxes = get_totals_and_taxes(
            "tabSales Invoice",
            "tabSales Taxes and Charges",
            0
        )
        summary["sales_invoice"] = {
            "totals": totals,
            "taxes": taxes
        }

        # Credit Note (sales returns, is_return=1)
        totals, taxes = get_totals_and_taxes(
            "tabSales Invoice",
            "tabSales Taxes and Charges",
            1
        )
        summary["credit_note"] = {
            "totals": totals,
            "taxes": taxes
        }

        # Purchase Invoice (normal purchases, is_return=0)
        totals, taxes = get_totals_and_taxes(
            "tabPurchase Invoice",
            "tabPurchase Taxes and Charges",
            0
        )
        summary["purchase_invoice"] = {
            "totals": totals,
            "taxes": taxes
        }

        # Debit Note (purchase returns, is_return=1)
        totals, taxes = get_totals_and_taxes(
            "tabPurchase Invoice",
            "tabPurchase Taxes and Charges",
            1
        )
        summary["debit_note"] = {
            "totals": totals,
            "taxes": taxes
        }

        # Save JSON summary into the result field
        doc.result = json.dumps(summary, indent=4)
        doc.save(ignore_permissions=True)

        html = frappe.get_print(
            doctype=doc.doctype,
            name=doc.name,
            print_format="Sales and Purchase Tax Summary",
            doc=doc,
            no_letterhead=False
        )

        pdf = get_pdf(html)

        file_name = f"Tax-Summary-{from_date}-to-{to_date}.pdf"
        file = frappe.get_doc({
            "doctype": "File",
            "file_name": file_name,
            "content": pdf,
            "is_private": 0
        })
        file.save(ignore_permissions=True)

        return file.file_url
        
    except Exception as e:
        frappe.log_error(f"Error generating tax summary: {str(e)}", "Tax Summary Generation Error")
        frappe.throw(f"Failed to generate tax summary: {str(e)}")




