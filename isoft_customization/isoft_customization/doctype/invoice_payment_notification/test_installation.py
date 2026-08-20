#!/usr/bin/env python3
"""
Test script to verify Invoice Payment Notification installation
Run this from bench console: bench --site [your-site] console
Then: exec(open('apps/erpnext/erpnext/accounts/doctype/invoice_payment_notification/test_installation.py').read())
"""

import frappe

def test_installation():
	"""Test if the DocType is properly installed"""
	
	print("\n" + "="*60)
	print("Invoice Payment Notification - Installation Test")
	print("="*60 + "\n")
	
	# Test 1: Check if DocType exists
	print("Test 1: Checking if DocType exists...")
	try:
		doctype = frappe.get_doc("DocType", "Invoice Payment Notification")
		print("✓ Invoice Payment Notification DocType found")
	except Exception as e:
		print(f"✗ Error: {str(e)}")
		return False
	
	# Test 2: Check if child DocType exists
	print("\nTest 2: Checking if child DocType exists...")
	try:
		child_doctype = frappe.get_doc("DocType", "Post Payment Invoice Customer")
		print("✓ Post Payment Invoice Customer DocType found")
	except Exception as e:
		print(f"✗ Error: {str(e)}")
		return False
	
	# Test 3: Check fields
	print("\nTest 3: Checking key fields...")
	required_fields = [
		"notification_name", "company", "enabled", "reference_doctype",
		"subject", "body", "customers", "print_format",
		"include_ledger", "cc_to", "bcc_to"
	]
	
	doctype_fields = [f.fieldname for f in doctype.fields]
	missing_fields = []
	
	for field in required_fields:
		if field in doctype_fields:
			print(f"  ✓ {field}")
		else:
			print(f"  ✗ {field} - MISSING")
			missing_fields.append(field)
	
	if missing_fields:
		print(f"\n✗ Missing fields: {', '.join(missing_fields)}")
		return False
	
	# Test 4: Check permissions
	print("\nTest 4: Checking permissions...")
	try:
		perms = frappe.get_all(
			"Custom DocPerm",
			filters={"parent": "Invoice Payment Notification"},
			fields=["role", "read", "write", "create"]
		)
		if perms:
			print(f"✓ Found {len(perms)} permission rules")
			for perm in perms:
				print(f"  - {perm.role}: R:{perm.read} W:{perm.write} C:{perm.create}")
		else:
			print("! No custom permissions found (using standard permissions)")
	except Exception as e:
		print(f"! Warning: {str(e)}")
	
	# Test 5: Check if module/hook exists
	print("\nTest 5: Checking hooks...")
	try:
		from erpnext.hooks import doc_events
		payment_entry_hooks = doc_events.get("Payment Entry", {})
		on_submit_hooks = payment_entry_hooks.get("on_submit", [])
		
		hook_found = False
		for hook in on_submit_hooks:
			if "invoice_payment_notification" in hook:
				print(f"✓ Hook found: {hook}")
				hook_found = True
				break
		
		if not hook_found:
			print("✗ Hook not found in Payment Entry on_submit")
			return False
	except Exception as e:
		print(f"✗ Error checking hooks: {str(e)}")
		return False
	
	# Test 6: Try to create a test document (without saving)
	print("\nTest 6: Testing document creation...")
	try:
		test_doc = frappe.new_doc("Invoice Payment Notification")
		test_doc.notification_name = "Test Notification"
		test_doc.company = frappe.defaults.get_defaults().get("company") or "Test Company"
		test_doc.enabled = 0  # Disabled for testing
		test_doc.subject = "Test Subject"
		test_doc.body = "Test Body"
		
		# Run validation without saving
		test_doc.validate()
		print("✓ Document creation and validation successful")
	except Exception as e:
		print(f"✗ Error: {str(e)}")
		return False
	
	# Test 7: Check if key methods exist
	print("\nTest 7: Checking key methods...")
	try:
		from erpnext.accounts.doctype.invoice_payment_notification.invoice_payment_notification import (
			InvoicePaymentNotification,
			send_manual_notification,
			trigger_notification_on_payment_submit
		)
		
		# Check if class has required methods
		required_methods = [
			"validate",
			"fetch_customers_for_collection",
			"get_customers_to_send",
			"get_paid_invoices",
			"send_notification_for_payment"
		]
		
		for method in required_methods:
			if hasattr(InvoicePaymentNotification, method):
				print(f"  ✓ {method}")
			else:
				print(f"  ✗ {method} - MISSING")
				return False
		
		print("✓ All required methods found")
	except Exception as e:
		print(f"✗ Error: {str(e)}")
		return False
	
	# Summary
	print("\n" + "="*60)
	print("Installation Test: PASSED ✓")
	print("="*60)
	print("\nNext Steps:")
	print("1. Go to: Home > Accounting > Settings > Invoice Payment Notification")
	print("2. Create a new notification")
	print("3. Test with a Payment Entry")
	print("\nFor detailed usage instructions, see:")
	print("  - USAGE_GUIDE.md (Quick start)")
	print("  - README.md (Comprehensive documentation)")
	print("\n")
	
	return True

if __name__ == "__main__":
	# If running from console
	test_installation()
