# Invoice Payment Notification

## Overview

The **Invoice Payment Notification** DocType allows you to automatically send emails to customers after Sales Invoice or Payment Entry submission. The email can include:
- Sales Invoice PDF(s) with customizable print format
- Customer Ledger Statement
- Ageing Summary (optional)

This combines the functionality of both the Notification system and Process Statement of Accounts, designed for invoice or payment communications.

## Key Features

### 1. Flexible Customer Filtering
- Select customers by:
  - Customer Group
  - Territory
  - Sales Partner
  - Sales Person
  - Specific Customers (manual selection)
- Fetch customers automatically based on criteria
- Option to require primary contact email

### 2. Document Type
- **Payment Entry**: Trigger on payment submission
- **Sales Invoice**: Trigger on invoice submission

### 3. Ledger Settings
- Include customer ledger statement
- Customize ledger date range
- Group transactions by voucher or consolidated
- Include ageing summary
- Choose ageing based on Due Date or Posting Date

### 4. Print Settings
- Attach invoice print (enable/disable)
- Select custom print format for Sales Invoice
- Choose orientation (Portrait/Landscape)
- Select letter head

### 5. Email Settings
- Custom sender email account
- CC recipients (comma-separated)
- BCC recipients (comma-separated)
- Send system notification (desktop notification)

### 6. Dynamic Email Content
Use Jinja templates for dynamic subject and body:
- `{{ doc }}` - The notification document
- `{{ customer }}` - Customer object
- `{{ payment_entry }}` - Payment Entry that triggered the email
- `{{ sales_invoice }}` - Sales Invoice that triggered the email
- `{{ reference_doc }}` - Trigger document (Payment Entry or Sales Invoice)
- `{{ invoices }}` - List of invoices included

### 7. Conditions (Optional)
Add a condition expression (like Notification) to control when emails are sent:
- Example: `doc.status == "Paid"`
- `doc` refers to the trigger document (Payment Entry or Sales Invoice)

#### Example Subject:
```
Payment Receipt for {{ customer.customer_name }}
```

#### Example Body:
```html
Dear {{ customer.customer_name }},

Thank you for your payment. Please find attached your invoice(s) and account statement.

Payment Reference: {{ payment_entry.name }}
Amount: {{ payment_entry.paid_amount }}

Best regards,
{{ doc.company }}
```

## Setup Instructions

### 1. Install the DocType
After adding the files, run:
```bash
bench migrate
```

### 2. Create a New Notification
1. Go to: **Accounting > Setup > Invoice Payment Notification > New**
2. Fill in the required fields:
   - **Notification Name**: Give it a descriptive name
   - **Company**: Select the company
   - **Enabled**: Check to activate

### 3. Configure Customer Filters
1. Select **Customer Collection** method (e.g., Customer Group)
2. Select the specific **Collection Name** (e.g., "All Customer Groups")
3. Click **Fetch Customers** to populate the customer list
4. Alternatively, select "Specific Customers" and add manually

### 4. Configure Email Settings
1. Set the email **Subject** and **Body** using Jinja templates
2. Add CC/BCC recipients if needed
3. Select sender email account (optional)

### 5. Configure Print and Ledger Settings
1. **Attach Invoice Print**: Enable to attach invoice PDFs
2. **Print Format**: Select custom print format or leave blank for Standard
3. **Include Ledger**: Enable to attach customer ledger statement
4. **Ledger Date Range**: Set the date range for ledger (defaults to last 90 days)
5. **Include Ageing**: Enable to show ageing summary in ledger

### 6. Select Document Type
1. **Payment Entry**: Automatically sends when payment is submitted
2. **Sales Invoice**: Automatically sends when sales invoice is submitted

## Usage

### Automatic Trigger
Once configured with Document Type:
1. Create and submit a Payment Entry or Sales Invoice for a customer
2. If the customer matches the notification criteria, an email is automatically queued
3. The email will be sent in the background with all attachments

### Manual Trigger
1. Open the Invoice Payment Notification document
2. Click **Send Test Email**
3. Select a Payment Entry or Sales Invoice to test with
4. Click **Send Email**

Alternatively:
1. This will send emails for the latest document of each customer in the list

## Technical Details

### Files Created
- `invoice_payment_notification.json` - DocType definition
- `invoice_payment_notification.py` - Python controller
- `invoice_payment_notification.js` - Client-side controller
- `post_payment_invoice_customer.json` - Child table for customers
- `post_payment_invoice_customer.py` - Child table controller

### Hook Added
In `erpnext/hooks.py`:
```python
"Sales Invoice": {
    "on_submit": [
        ...
        "erpnext.accounts.doctype.invoice_payment_notification.invoice_payment_notification.trigger_notification_on_sales_invoice_submit",
    ],
},
"Payment Entry": {
    "on_submit": [
        ...
        "erpnext.accounts.doctype.invoice_payment_notification.invoice_payment_notification.trigger_notification_on_payment_submit",
    ],
},
```

### Key Functions

#### `validate()`
Validates the notification settings and Jinja templates.

#### `fetch_customers_for_collection()`
Fetches customers based on selected collection criteria.

#### `get_paid_invoices(customer, payment_entry=None)`
Gets paid invoices for a customer, optionally filtered by payment entry.

#### `get_customer_ledger_pdf(customer)`
Generates customer ledger statement as PDF.

#### `send_notification_for_sales_invoice(sales_invoice_name)`
Sends the notification email for a sales invoice.

#### `send_notification_for_payment(payment_entry_name)`
Main function that sends the notification email with all attachments.

#### `trigger_notification_on_payment_submit(payment_entry, method=None)`
Hook function that triggers when Payment Entry is submitted.

#### `trigger_notification_on_sales_invoice_submit(sales_invoice, method=None)`
Hook function that triggers when Sales Invoice is submitted.

## Comparison with Existing Features

### vs. Notification DocType
- **Notification**: Generic, can trigger on any DocType event
- **Invoice Payment Notification**: Designed for invoice or payment submissions with invoice and ledger attachments

### vs. Process Statement of Accounts
- **Process Statement of Accounts**: Sends statements to customers on schedule or manually
- **Invoice Payment Notification**: Automatically triggered by invoice or payment, includes both invoices and statements

## Troubleshooting

### Emails Not Sending
1. Check that the notification is **Enabled**
2. Verify customer has a valid email address
3. Check Error Log for any errors
4. Verify Email Account is configured in ERPNext

### Customers Not Fetched
1. Ensure **Customer Collection** and **Collection Name** are selected
2. Check that customers actually belong to the selected collection
3. If **Send To Primary Contact** is checked, ensure customers have email addresses

### Attachments Missing
1. Verify **Attach Invoice Print** is enabled
2. Check Print Settings allow printing for submitted documents
3. Ensure **Include Ledger** is enabled if you want ledger statements
4. Check that the print format exists and is accessible

## Best Practices

1. **Test First**: Always use "Send Test Email" before enabling automatic triggers
2. **Start Small**: Begin with a single customer group before rolling out to all customers
3. **Clear Subject Lines**: Use descriptive subjects that customers will recognize
4. **Professional Body**: Keep email body professional and include all necessary information
5. **Review Regularly**: Check Email Queue and Error Log regularly for any issues
6. **Customize Print Formats**: Create custom print formats that match your branding

## Future Enhancements

Potential features for future versions:
- Multi-language support for email templates
- Attachment of additional documents
- Schedule-based sending (optional)
- Email analytics and tracking
- Customer preferences for email frequency
- Integration with SMS notifications

## Support

For issues or questions:
1. Check Error Log in ERPNext
2. Review this documentation
3. Check Frappe/ERPNext forums
4. Consult with your ERPNext administrator

---

**Version**: 1.0  
**Created**: February 5, 2026  
**Compatible**: ERPNext v13+
