# Invoice Payment Notification - Quick Start Guide

## Quick Setup (5 Minutes)

### Step 1: Access the DocType
1. Login to ERPNext
2. Go to: **Home > Accounting > Settings > Invoice Payment Notification**
3. Click **New**

### Step 2: Basic Configuration
Fill in these required fields:

**Basic Settings:**
- **Notification Name**: e.g., "Invoice or Payment Receipt"
- **Company**: Select your company
- **Enabled**: ✓ Check this box

**Document Settings:**
- **Document Type**: Choose "Payment Entry" or "Sales Invoice" based on when you want to send

**Email Message:**
- **Subject**: 
  ```
  Payment Receipt for {{ customer.customer_name }}
  ```
- **Body**: 
  ```html
  Dear {{ customer.customer_name }},

  Thank you for your payment. Please find attached your invoice(s) and account statement.

  Payment Reference: {{ payment_entry.name }}
  Amount: {{ payment_entry.paid_amount }}

  Best regards,
  {{ doc.company }}
  ```

### Step 3: Select Customers

**Option A: Fetch by Group**
1. **Select Customers By**: Choose "Customer Group"
2. **Collection Name**: Select a customer group (e.g., "All Customer Groups")
3. Click **Fetch Customers** button
4. Customers will be auto-populated in the table below

**Option B: Manual Selection**
1. **Select Customers By**: Choose "Specific Customers"
2. In the **Customers** table, click **Add Row**
3. Select customer manually
4. Email will auto-fill from customer record

### Step 4: Configure Attachments

**Invoice Settings:**
- **Attach Invoice Print**: ✓ Check to include invoice PDF
- **Print Format**: Leave blank for Standard, or select custom format
- **Letter Head**: Select your company letter head (optional)

**Ledger Settings:**
- **Include Customer Ledger**: ✓ Check to include ledger statement
- **Ledger From Date**: Defaults to 90 days ago (auto-filled)
- **Ledger To Date**: Defaults to today (auto-filled)
- **Include Ageing Summary**: ✓ Check if you want ageing details

### Step 5: Email Settings (Optional)

- **CC To**: Add additional CC emails (comma-separated)
- **BCC To**: Add BCC emails (comma-separated)
- **Sender**: Leave blank to use default email account

### Step 6: Save

Click **Save** to create the notification.

## Testing Your Configuration

### Method 1: Test with Specific Document
1. Open your saved Invoice Payment Notification
2. Click **Send Test Email** button
3. Select a recent document based on **Document Type**
4. Click **Send Email**
5. Check your email inbox

### Method 2: Test with Real Submission
1. Create a new Payment Entry or Sales Invoice for a customer in your list
2. Submit the document
3. Email should be automatically queued
4. Check: **Home > Email Queue** to see the queued email

## Common Use Cases

### Use Case 1: Send to All Payment Entries
```
- Customer Collection: Customer Group
- Collection Name: All Customer Groups
- Document Type: Payment Entry
- Attach Invoice Print: ✓
- Include Ledger: ✓
```

### Use Case 2: Send to Specific Territory Only
```
- Customer Collection: Territory
- Collection Name: United States
- Document Type: Sales Invoice
- Include Ledger: ✓
- Include Ageing: ✓
```

### Use Case 3: Quarterly Statements (Manual)
```
- Customer Collection: Specific Customers
- Customers: [Add manually]
- Document Type: Sales Invoice
- Include Ledger: ✓
- Include Ageing: ✓
```

## Available Jinja Variables

Use these in your Subject and Body templates:

### Document Variables
- `{{ doc.name }}` - Notification name
- `{{ doc.company }}` - Company name

### Customer Variables
- `{{ customer.name }}` - Customer ID
- `{{ customer.customer_name }}` - Customer display name
- `{{ customer.email_id }}` - Customer email
- `{{ customer.territory }}` - Customer territory
- `{{ customer.customer_group }}` - Customer group

### Payment Entry Variables
- `{{ payment_entry.name }}` - Payment entry ID
- `{{ payment_entry.paid_amount }}` - Amount paid
- `{{ payment_entry.posting_date }}` - Payment date
- `{{ payment_entry.reference_no }}` - Reference number
- `{{ payment_entry.reference_date }}` - Reference date

### Sales Invoice Variables
- `{{ sales_invoice.name }}` - Sales invoice ID
- `{{ sales_invoice.posting_date }}` - Invoice date
- `{{ sales_invoice.grand_total }}` - Invoice total
- `{{ sales_invoice.outstanding_amount }}` - Outstanding amount

### Reference Document (Generic)
- `{{ reference_doc }}` - Trigger document (Payment Entry or Sales Invoice)

### Invoice Variables
- `{{ invoices }}` - List of invoices
- `{{ invoices|length }}` - Number of invoices

### Example: Show Invoice List in Email
```html
Dear {{ customer.customer_name }},

Thank you for your payment of {{ payment_entry.paid_amount }}.

Invoices paid:
{% for invoice in invoices %}
- {{ invoice.name }} dated {{ invoice.posting_date }}: {{ invoice.grand_total }}
{% endfor %}

Best regards,
{{ doc.company }}
```

## Troubleshooting

### Email Not Sent
**Problem**: Email not queued after submission
**Solutions**:
1. Check that notification is **Enabled** ✓
2. Verify customer is in the customer list
3. Verify customer has a valid email address
4. Check **Error Log** for errors

### Customer Not in List
**Problem**: Customer not appearing after "Fetch Customers"
**Solutions**:
1. Verify customer belongs to selected group/territory
2. If "Send To Primary Contact" is checked, ensure customer has email
3. Check customer is active (not disabled)

### Attachment Missing
**Problem**: Email sent but attachments not included
**Solutions**:
1. Check **Attach Invoice Print** is enabled ✓
2. Verify **Print Settings** > **Allow Print for Draft** is enabled if needed
3. Check print format exists and is accessible
4. Check **Error Log** for attachment errors

### Wrong Customers Receiving Emails
**Problem**: Emails going to wrong customers
**Solutions**:
1. Review customer list in the **Customers** table
2. Check collection filters (Customer Group, Territory, etc.)
3. Clear and re-fetch customers if needed

## Advanced Tips

### Tip 1: Multiple Notification Rules
Create separate notifications for different scenarios:
- "Payment Entry - VIP Customers" with special template
- "Sales Invoice - International" with different ledger range
- "Sales Invoice - Local" with ageing summary

### Tip 2: Custom Print Formats
1. Create custom print format for Sales Invoice
2. Select it in the notification
3. All attached invoices will use this format

### Tip 3: Email Tracking
Monitor email status:
1. Go to: **Home > Email Queue**
2. Filter by reference: "Payment Entry" or "Sales Invoice"
3. Check status: Sent / Not Sent / Error

### Tip 5: Professional Email Templates
Include:
- Company logo in letter head
- Professional email signature
- Contact information
- Payment instructions for next time
- Customer service contact

## Performance Considerations

### For Large Customer Lists
- Start with smaller customer groups first
- Test with 5-10 customers before rolling out to all
- Monitor Email Queue for performance
- Consider batch sending for 100+ customers

### For Multiple Invoices
- System automatically attaches all invoices linked to the payment entry
- Ledger statement provides consolidated view

### Email Queue Management
- Emails are queued, not sent immediately
- Background workers process the queue
- Check queue status regularly: **Home > Email Queue**
- Failed emails can be retried from Email Queue

## Security & Privacy

### Best Practices
1. **Test thoroughly** before enabling for all customers
2. **Verify email addresses** to avoid sending to wrong recipients
3. **Review attachments** to ensure correct information
4. **Use BCC** for internal copies, not CC
5. **Limit access** to this DocType to authorized users only

### Permissions
Only these roles can create/edit:
- Accounts Manager
- Accounts User

## Next Steps

After setup:
1. ✓ Test with a few customers first
2. ✓ Review email templates for professionalism
3. ✓ Configure custom print formats if needed
4. ✓ Train accounts team on usage
5. ✓ Monitor Email Queue for first few days
6. ✓ Gather customer feedback
7. ✓ Adjust templates based on feedback

## Getting Help

If you encounter issues:
1. Check this guide first
2. Review the main README.md file
3. Check Error Log: **Home > Error Log**
4. Check Email Queue: **Home > Email Queue**
5. Consult your ERPNext administrator
6. Post on Frappe/ERPNext forums

---

**Quick Reference Card**

| Setting | Purpose | Required |
|---------|---------|----------|
| Notification Name | Identifier | ✓ Yes |
| Company | Company filter | ✓ Yes |
| Enabled | Activate/Deactivate | ✓ Yes |
| Document Type | Which document triggers | ✓ Yes |
| Subject | Email subject line | ✓ Yes |
| Body | Email message | ✓ Yes |
| Customer Collection | How to select customers | Optional |
| Attach Invoice Print | Include invoice PDF | Optional |
| Include Ledger | Include statement | Optional |
| Print Format | Custom format | Optional |
| CC To | Additional recipients | Optional |

---

Need more help? Check the comprehensive README.md file in the same directory.
