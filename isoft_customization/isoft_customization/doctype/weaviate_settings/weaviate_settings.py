# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
import requests
from frappe.model.document import Document
from frappe import _
import json
import base64
from io import BytesIO
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from datetime import datetime

class WeaviateSettings(Document):
	def validate(self):
		"""Validate embedding URL when enabled and run a test"""
		if self.enabled:
			self.validate_embedding_url()
			# Run a small test to ensure the service is working
			self.test_embedding_service()
	
	def embed(self, text):
		"""Generate embeddings for the given text"""
		if not self.enabled or not self.flagembedding__url:
			frappe.throw(_("Weaviate is not enabled or embedding URL is not configured."))
		
		try:
			# Ensure text is a list for the new API
			if isinstance(text, str):
				sentences = [text]
			elif isinstance(text, list):
				sentences = text
			else:
				frappe.throw(_("Text must be a string or list of strings."))
			
			response = requests.post(
				self.flagembedding__url,
				json={"sentences": sentences},
				timeout=30  # Longer timeout for actual embedding requests
			)
			
			if response.ok:
				result = response.json()
				if "embeddings" in result:
					return result["embeddings"]
				else:
					frappe.throw(_("Invalid response format. Expected 'embeddings' field in response."))
			else:
				frappe.throw(_("Embedding API error: {0}").format(response.text))
				
		except requests.exceptions.Timeout:
			frappe.throw(_("Timeout connecting to embedding service. Please try again."))
		except requests.exceptions.ConnectionError:
			frappe.throw(_("Connection error. Please check if the embedding service is running."))
		except requests.exceptions.RequestException as e:
			frappe.throw(_("Request error: {0}").format(str(e)))
		except ValueError as e:
			frappe.throw(_("Invalid JSON response from embedding service: {0}").format(str(e)))
		except Exception as e:
			frappe.throw(_("Unexpected error generating embeddings: {0}").format(str(e)))
	
	def validate_embedding_url(self):
		"""Validate the embedding URL by making a test request"""
		if not self.flagembedding__url:
			frappe.throw(_("Embedding URL is required when Weaviate is enabled."))
		
		try:
			# Test embedding with a simple text
			embeddings = self.embed("TEST")
			
			if embeddings and len(embeddings) > 0:
				frappe.msgprint(_("✅ Embedding URL validation successful!"), indicator="green")
			else:
				frappe.throw(_("No embeddings returned from the API."))
				
		except Exception as e:
			frappe.throw(_("Embedding validation failed: {0}").format(str(e)))
	
	def test_embedding_service(self):
		"""Test the embedding service with a simple request"""
		if not self.enabled:
			frappe.throw(_("Weaviate must be enabled to test the embedding service."))
		
		try:
			# Test with a simple sentence
			test_text = "This is a test sentence for embedding generation."
			embeddings = self.embed(test_text)
			
			if embeddings and len(embeddings) > 0:
				frappe.msgprint(
					_("✅ Embedding test successful! Generated {0} embeddings.").format(len(embeddings)),
					indicator="green"
				)
				return True
			else:
				frappe.throw(_("No embeddings returned from the test."))
				
		except Exception as e:
			frappe.msgprint(
				_("❌ Embedding test failed: {0}").format(str(e)),
				indicator="red"
			)
			return False



	def _reload_all_items_to_weaviate_background(self):
		"""Background job to reload all items to Weaviate"""
		try:
			# Step 1: Discover available endpoints
			available_endpoints = self._discover_api_endpoints()
			
			# Determine which endpoint to use
			use_store_endpoint = '/store_product' not in available_endpoints
			if use_store_endpoint:
				frappe.msgprint(_("📋 Using /store endpoint (products will be stored as documents)"), indicator="blue")
			else:
				frappe.msgprint(_("📋 Using /store_product endpoint"), indicator="blue")
			
			# Step 2: Automatically delete all existing products
			frappe.msgprint(_("🗑️ Automatically clearing all existing products..."), indicator="blue")
			self._delete_all_existing_products()
			
			# Step 3: Get enabled items from ERPNext
			items = self._get_enabled_items()
			if not items:
				frappe.msgprint(_("ℹ️ No enabled items found in ERPNext."), indicator="yellow")
				self._update_progress(100, 0, "No items to upload")
				return
			
			total_items = len(items)
			frappe.msgprint(_("📊 Found {0} enabled items to upload").format(total_items), indicator="blue")
			
			# Step 4: Test upload with first item
			frappe.msgprint(_("🧪 Testing upload with first item..."), indicator="blue")
			test_item = items[0]
			test_result = self._upload_item_to_weaviate(test_item, use_store_endpoint)
			
			if not test_result:
				frappe.throw(_("❌ Test upload failed: {0}").format(test_result))
			
			frappe.msgprint(_("✅ Test upload successful! Proceeding with bulk upload..."), indicator="green")
			
			# Step 5: Upload all items
			success_count = 0
			error_count = 0
			error_details = []
			
			for i, item in enumerate(items):
				try:
					result = self._upload_item_to_weaviate(item, use_store_endpoint)
					if result:
						success_count += 1
					else:
						error_count += 1
						error_details.append(f"Item {item.get('item_code', 'Unknown')}: Upload failed")
					
					# Update progress
					progress = int(((i + 1) / total_items) * 100)
					self._update_progress(progress, total_items, f"Uploaded {i + 1}/{total_items}")
					
				except Exception as e:
					error_count += 1
					error_msg = f"Item {item.get('item_code', 'Unknown')}: {str(e)}"
					error_details.append(error_msg)
					frappe.log_error(error_msg, "Weaviate Item Upload Error")
					
					# Update progress even on error
					progress = int(((success_count + error_count) / total_items) * 100)
					self._update_progress(progress, total_items, f"Error on item {item.get('item_code', 'Unknown')}")
					
					# Stop after 5 errors to avoid flooding
					if error_count >= 5:
						frappe.msgprint(_("⚠️ Stopping upload after 5 errors. Check logs for details."), indicator="red")
						break
			
			# Step 6: Show final results
			final_message = ""
			if error_count == 0:
				final_message = _("🎉 Successfully uploaded all {0} items to Weaviate!").format(success_count)
				self._update_progress(100, total_items, "Completed successfully!")
			else:
				error_summary = "\n".join(error_details[:3])  # Show first 3 errors
				if len(error_details) > 3:
					error_summary += f"\n... and {len(error_details) - 3} more errors"
				
				final_message = _("⚠️ Upload completed with {0} successful and {1} failed uploads.\n\nError details:\n{2}").format(
					success_count, error_count, error_summary
				)
				self._update_progress(100, total_items, f"Completed with {error_count} errors")
			
			frappe.msgprint(final_message, indicator="green" if error_count == 0 else "orange")
				
		except Exception as e:
			frappe.log_error(f"Weaviate reload failed: {str(e)}", "Weaviate Reload Error")
			frappe.throw(_("Failed to reload items to Weaviate: {0}").format(str(e)))

	def _clear_all_products_from_weaviate(self, use_store_endpoint=False):
		"""Clear all products from Weaviate"""
		try:
			# Get the base URL from the embedding URL
			base_url = self.flagembedding__url.replace('/embed', '')
			
			if use_store_endpoint:
				# Using /store endpoint, so clear documents with product category
				frappe.msgprint(_("🗑️ Clearing existing product documents..."), indicator="blue")
				
				# Get all documents and filter for product category
				response = requests.get(f"{base_url}/list?limit=1000", timeout=30)
				
				if response.ok:
					result = response.json()
					documents = result.get('documents', [])
					
					# Filter for product documents
					product_docs = [doc for doc in documents if doc.get('category') == 'product']
					
					if product_docs:
						frappe.msgprint(_("🗑️ Deleting {0} existing product documents...").format(len(product_docs)), indicator="blue")
						
						for doc in product_docs:
							document_id = doc.get('document_id')
							if document_id:
								delete_response = requests.delete(f"{base_url}/delete/{document_id}", timeout=10)
								if not delete_response.ok:
									frappe.log_error(
										f"Failed to delete document {document_id}: {delete_response.text}",
										"Weaviate Delete Error"
									)
					else:
						frappe.msgprint(_("ℹ️ No existing product documents found to clear"), indicator="blue")
				else:
					frappe.msgprint(_("⚠️ Could not fetch existing documents: {0}").format(response.text), indicator="yellow")
			else:
				# Using /store_product endpoint, so clear products
				response = requests.get(f"{base_url}/list_products?limit=1000", timeout=30)
				
				if response.ok:
					result = response.json()
					products = result.get('products', [])
					
					if products:
						frappe.msgprint(_("🗑️ Deleting {0} existing products...").format(len(products)), indicator="blue")
						
						for product in products:
							item_code = product.get('item_code')
							if item_code:
								delete_response = requests.delete(f"{base_url}/delete_product/{item_code}", timeout=10)
								if not delete_response.ok:
									frappe.log_error(
										f"Failed to delete product {item_code}: {delete_response.text}",
										"Weaviate Delete Error"
									)
					else:
						frappe.msgprint(_("ℹ️ No existing products found to clear"), indicator="blue")
				else:
					frappe.msgprint(_("⚠️ Could not fetch existing products: {0}").format(response.text), indicator="yellow")
			
			frappe.msgprint(_("✅ Cleared all products from Weaviate"), indicator="green")
			
		except Exception as e:
			frappe.throw(_("Failed to clear products from Weaviate: {0}").format(str(e)))

	def _get_enabled_items(self):
		"""Get all enabled items from ERPNext"""
		try:
			# Get items where disabled = 0 (enabled items only)
			items = frappe.get_all(
				'Item',
				filters={'disabled': 0},
				fields=['item_code', 'item_name', 'brand', 'item_group', 'description'],
				limit=10000  # Increased limit for production use
			)
			
			# Upload all enabled items - no filtering
			filtered_items = items
			
			return filtered_items
			
		except Exception as e:
			frappe.throw(_("Failed to fetch items from ERPNext: {0}").format(str(e)))

	def _delete_all_existing_products(self):
		"""Delete all existing products from Weaviate using the delete_all_product_documents function"""
		try:
			# Import the function to avoid circular imports
			from isoft_customization.isoft_customization.doctype.weaviate_settings.weaviate_settings import delete_all_product_documents
			
			# Call the delete function
			result = delete_all_product_documents()
			
			# Log the result
			frappe.logger().info(f"Auto-delete result: {result}")
			
		except Exception as e:
			frappe.log_error(f"Auto-delete failed: {str(e)}", "Weaviate Auto-Delete Error")
			# Don't throw error, just log it and continue
			frappe.msgprint(_("⚠️ Auto-delete failed, but continuing with upload: {0}").format(str(e)), indicator="yellow")

	def _upload_item_to_weaviate(self, item, use_store_endpoint=False):
		"""Upload a single item to Weaviate"""
		try:
			# Get the base URL from the embedding URL
			base_url = self.flagembedding__url.replace('/embed', '')
			
			# Choose endpoint based on availability
			if use_store_endpoint:
				# Use /store endpoint (document format)
				upload_url = f"{base_url}/store"
				endpoint_type = "document"
				
				# Prepare data for /store endpoint (document format)
				content = f"Item Code: {item.get('item_code', '')}\n"
				content += f"Item Name: {item.get('item_name', '')}\n"
				content += f"Brand: {item.get('brand', '')}\n"
				content += f"Item Group: {item.get('item_group', '')}\n"
				content += f"Description: {item.get('description', '')}"
				
				item_data = {
					'content': content,
					'document_id': f"item_{item.get('item_code', '')}",
					'category': 'product',
					'metadata': {
						'source': 'ERPNext',
						'type': 'product',
						'item_code': str(item.get('item_code', '')),
						'item_name': str(item.get('item_name', '')),
						'brand': str(item.get('brand', '')),
						'item_group': str(item.get('item_group', '')),
						'description': str(item.get('description', '')),
						'uploaded_at': frappe.utils.now()
					}
				}
			else:
				# Use /store_product endpoint (product format)
				upload_url = f"{base_url}/store_product"
				endpoint_type = "product"
				
				# Prepare data for /store_product endpoint
				item_data = {
					'item_code': str(item.get('item_code', '')),
					'item_name': str(item.get('item_name', '')),
					'brand': str(item.get('brand', '')),
					'item_group': str(item.get('item_group', '')),
					'description': str(item.get('description', '')),
					'metadata': {
						'source': 'ERPNext',
						'uploaded_at': frappe.utils.now()
					}
				}
			
			# Debug: Show the upload URL
			frappe.msgprint(_("📤 Upload URL: {0} (Type: {1})").format(upload_url, endpoint_type), indicator="blue")
			
			# Log the request for debugging
			frappe.logger().debug(f"Uploading item {item.get('item_code')} to {upload_url} as {endpoint_type}")
			
			# Upload to Weaviate
			response = requests.post(
				upload_url,
				json=item_data,
				timeout=30,
				headers={'Content-Type': 'application/json'}
			)
			
			# Log response for debugging
			frappe.logger().debug(f"Response status: {response.status_code}, Response: {response.text}")
			
			if not response.ok:
				raise Exception(f"HTTP {response.status_code}: {response.text}")
			
			try:
				result = response.json()
				if 'error' in result:
					raise Exception(result['error'])
				elif 'message' in result:
					# Success case
					return True
				else:
					# Unknown response format
					frappe.logger().warning(f"Unexpected response format: {result}")
					return True  # Assume success if no error
					
			except ValueError as e:
				raise Exception(f"Invalid JSON response: {response.text}")
				
		except Exception as e:
			# Log the full error for debugging
			frappe.logger().error(f"Upload failed for item {item.get('item_code', 'Unknown')}: {str(e)}")
			raise Exception(f"Failed to upload item {item.get('item_code', 'Unknown')}: {str(e)}")

	def _test_api_connectivity(self):
		"""Test if the API is accessible and responding"""
		try:
			# Get the base URL from the embedding URL
			base_url = self.flagembedding__url.replace('/embed', '')
			
			# Debug: Show the URLs being used
			frappe.msgprint(_("🔍 Testing URLs:"), indicator="blue")
			frappe.msgprint(_("Embedding URL: {0}").format(self.flagembedding__url), indicator="blue")
			frappe.msgprint(_("Base URL: {0}").format(base_url), indicator="blue")
			
			# Test health endpoint first
			health_url = f"{base_url}/health"
			frappe.msgprint(_("Health URL: {0}").format(health_url), indicator="blue")
			health_response = requests.get(health_url, timeout=10)
			
			if health_response.ok:
				frappe.msgprint(_("✅ API health check passed"), indicator="green")
				return True
			
			# If health endpoint fails, try embedding endpoint
			frappe.msgprint(_("Health check failed, trying embedding endpoint..."), indicator="yellow")
			test_response = requests.post(
				self.flagembedding__url,
				json={"sentences": ["test"]},
				timeout=10
			)
			
			if test_response.ok:
				frappe.msgprint(_("✅ API connectivity test passed"), indicator="green")
				return True
			else:
				frappe.msgprint(_("❌ API connectivity test failed: {0}").format(test_response.text), indicator="red")
				return False
				
		except Exception as e:
			frappe.msgprint(_("❌ API connectivity test failed: {0}").format(str(e)), indicator="red")
			return False

	def _update_progress(self, progress, total, message):
		"""Update progress for background job"""
		try:
			# Store progress in cache for frontend access
			cache_key = f"weaviate_progress_{self.name}"
			progress_data = {
				'progress': progress,
				'total': total,
				'current': int((progress / 100) * total) if total > 0 else 0,
				'message': message,
				'timestamp': frappe.utils.now()
			}
			frappe.cache().set_value(cache_key, progress_data, expires_in_sec=3600)
			
			# Log progress for debugging
			frappe.logger().info(f"Weaviate Progress: {progress}% - {message}")
			
		except Exception as e:
			frappe.logger().error(f"Failed to update progress: {str(e)}")



	def _discover_api_endpoints(self):
		"""Discover available API endpoints"""
		try:
			base_url = self.flagembedding__url.replace('/embed', '')
			
			# Test common endpoints
			endpoints_to_test = [
				'/health',
				'/store_product',
				'/store',
				'/list_products',
				'/init'
			]
			
			frappe.msgprint(_("🔍 Testing available endpoints:"), indicator="blue")
			
			available_endpoints = []
			for endpoint in endpoints_to_test:
				try:
					url = f"{base_url}{endpoint}"
					if endpoint in ['/store_product', '/store']:
						# POST endpoints
						response = requests.post(url, json={}, timeout=5)
					else:
						# GET endpoints
						response = requests.get(url, timeout=5)
					
					if response.status_code != 404:
						available_endpoints.append(endpoint)
						frappe.msgprint(_("✅ {0} - Status: {1}").format(endpoint, response.status_code), indicator="green")
					else:
						frappe.msgprint(_("❌ {0} - Not Found").format(endpoint), indicator="red")
						
				except Exception as e:
					frappe.msgprint(_("❌ {0} - Error: {1}").format(endpoint, str(e)), indicator="red")
			
			return available_endpoints
			
		except Exception as e:
			frappe.msgprint(_("❌ Endpoint discovery failed: {0}").format(str(e)), indicator="red")
			return []




@frappe.whitelist()
def test_delete_document(document_id):
	"""Test delete a specific document from Weaviate by document_id"""
	# Get the Weaviate Settings document
	weaviate_settings = frappe.get_doc("Weaviate Settings")
	
	if not weaviate_settings.enabled:
		frappe.throw(_("Weaviate must be enabled to delete documents."))
	
	if not weaviate_settings.flagembedding__url:
		frappe.throw(_("Embedding URL is required when Weaviate is enabled."))
	
	if not document_id:
		frappe.throw(_("Document ID is required."))
	
	try:
		# Get the base URL from the embedding URL
		base_url = weaviate_settings.flagembedding__url.replace('/embed', '')
		
		# First check if Weaviate is accessible
		health_response = requests.get(f"{base_url}/health", timeout=10)
		
		if not health_response.ok:
			frappe.throw(_("❌ Cannot connect to embedding service. Please check if the service is running."))
		
		health_data = health_response.json()
		weaviate_status = health_data.get('weaviate', 'unknown')
		
		if weaviate_status != 'connected':
			frappe.throw(_("❌ Weaviate is not connected. Status: {0}").format(weaviate_status))
		

		
		# Use query parameter approach to handle special characters
		import urllib.parse
		delete_url = f"{base_url}/delete_document?document_id={urllib.parse.quote(document_id, safe='')}"
		delete_response = requests.delete(delete_url, timeout=30)
		
		if delete_response.ok:
			frappe.msgprint(_("✅ Successfully deleted document '{0}' from Weaviate!").format(document_id), indicator="green")
			return _("✅ Document '{0}' deleted successfully!").format(document_id)
		else:
			frappe.throw(_("❌ Delete failed with status {0}: {1}").format(delete_response.status_code, delete_response.text))
			
	except requests.exceptions.ConnectionError:
		frappe.throw(_("❌ Cannot connect to embedding service. Please check if the service is running."))
	except requests.exceptions.Timeout:
		frappe.throw(_("❌ Connection timeout. Please try again."))
	except Exception as e:
		frappe.log_error(f"Weaviate delete failed: {str(e)}", "Weaviate Delete Error")
		frappe.throw(_("Failed to delete document from Weaviate: {0}").format(str(e)))


@frappe.whitelist()
def delete_all_product_documents():
	"""Delete all documents with category 'product' from Weaviate"""
	import urllib.parse
	
	# Get the Weaviate Settings document
	weaviate_settings = frappe.get_doc("Weaviate Settings")
	
	if not weaviate_settings.enabled:
		frappe.throw(_("Weaviate must be enabled to delete documents."))
	
	if not weaviate_settings.flagembedding__url:
		frappe.throw(_("Embedding URL is required when Weaviate is enabled."))
	
	try:
		# Get the base URL from the embedding URL
		base_url = weaviate_settings.flagembedding__url.replace('/embed', '')
		
		# First check if Weaviate is accessible
		health_response = requests.get(f"{base_url}/health", timeout=10)
		
		if not health_response.ok:
			frappe.throw(_("❌ Cannot connect to embedding service. Please check if the service is running."))
		
		health_data = health_response.json()
		weaviate_status = health_data.get('weaviate', 'unknown')
		
		if weaviate_status != 'connected':
			frappe.throw(_("❌ Weaviate is not connected. Status: {0}").format(weaviate_status))
		
		# Try to get products from Product class first
		products_to_delete = []
		documents_to_delete = []
		
		try:
			products_response = requests.get(f"{base_url}/list_products?limit=5000", timeout=30)
			if products_response.ok:
				products_data = products_response.json()
				all_products = products_data.get('products', [])
				
				if all_products:
					products_to_delete = all_products
		except Exception as e:
			pass
		
		# If no products found in Product class, try Document class
		if not products_to_delete:
			try:
				documents_response = requests.get(f"{base_url}/list?limit=5000", timeout=30)
				if documents_response.ok:
					documents_data = documents_response.json()
					all_documents = documents_data.get('documents', [])
					
					# Filter for documents with category 'product'
					documents_to_delete = [doc for doc in all_documents if doc.get('category') == 'product']
			except Exception as e:
				pass
		
		# Combine counts for display
		total_items = len(products_to_delete) + len(documents_to_delete)
		
		if total_items == 0:
			frappe.msgprint(_("ℹ️ No product documents found to delete."), indicator="yellow")
			return _("ℹ️ No product documents found to delete.")
		
		frappe.msgprint(_("🗑️ Found {0} items to delete...").format(total_items), indicator="blue")
		
		# Delete items from both classes
		success_count = 0
		error_count = 0
		error_details = []
		
		# Delete products from Product class
		for i, product in enumerate(products_to_delete):
			try:
				item_code = product.get('item_code')
				if item_code:
					# Use query parameter approach to handle special characters
					delete_url = f"{base_url}/delete_product_by_query?item_code={urllib.parse.quote(item_code, safe='')}"
					
					delete_response = requests.delete(delete_url, timeout=10)
					
					if delete_response.ok:
						success_count += 1
					else:
						error_count += 1
						error_msg = f"Product {item_code}: {delete_response.text}"
						error_details.append(error_msg)
						frappe.log_error(
							f"Failed to delete product {item_code}: {delete_response.text}",
							"Weaviate Delete Error"
						)
				else:
					error_count += 1
					error_details.append(f"Product {i + 1}: No item_code found")
					
			except Exception as e:
				error_count += 1
				error_msg = f"Product {product.get('item_code', f'#{i + 1}')}: {str(e)}"
				error_details.append(error_msg)
				frappe.log_error(error_msg, "Weaviate Delete Error")
		
		# Delete documents from Document class
		for i, doc in enumerate(documents_to_delete):
			try:
				document_id = doc.get('document_id')
				if document_id:
					# Use document deletion endpoint
					delete_url = f"{base_url}/delete_document?document_id={urllib.parse.quote(document_id, safe='')}"
					
					delete_response = requests.delete(delete_url, timeout=10)
					
					if delete_response.ok:
						success_count += 1
					else:
						error_count += 1
						error_msg = f"Document {document_id}: {delete_response.text}"
						error_details.append(error_msg)
						frappe.log_error(
							f"Failed to delete document {document_id}: {delete_response.text}",
							"Weaviate Delete Error"
						)
				else:
					error_count += 1
					error_details.append(f"Document {i + 1}: No document_id found")
					
			except Exception as e:
				error_count += 1
				error_msg = f"Document {doc.get('document_id', f'#{i + 1}')}: {str(e)}"
				error_details.append(error_msg)
				frappe.log_error(error_msg, "Weaviate Delete Error")
		
		# Show final results
		if error_count == 0:
			final_message = _("✅ Successfully deleted all {0} product documents from Weaviate!").format(success_count)
			frappe.msgprint(final_message, indicator="green")
		else:
			error_summary = "\n".join(error_details[:5])  # Show first 5 errors
			if len(error_details) > 5:
				error_summary += f"\n... and {len(error_details) - 5} more errors"
			
			final_message = _("⚠️ Deletion completed with {0} successful and {1} failed deletions.\n\nError details:\n{2}").format(
				success_count, error_count, error_summary
			)
			frappe.msgprint(final_message, indicator="orange")
		
		return final_message
		
	except requests.exceptions.ConnectionError:
		frappe.throw(_("❌ Cannot connect to embedding service. Please check if the service is running."))
	except requests.exceptions.Timeout:
		frappe.throw(_("❌ Connection timeout. Please try again."))
	except Exception as e:
		frappe.log_error(f"Weaviate bulk delete failed: {str(e)}", "Weaviate Bulk Delete Error")
		frappe.throw(_("Failed to delete product documents from Weaviate: {0}").format(str(e)))


@frappe.whitelist()
def semantic_search_products(query, limit=10):
	"""Search for products using semantic similarity"""
	# Get the Weaviate Settings document
	weaviate_settings = frappe.get_doc("Weaviate Settings")
	
	if not weaviate_settings.enabled:
		frappe.throw(_("Weaviate must be enabled to perform semantic search."))
	
	if not weaviate_settings.flagembedding__url:
		frappe.throw(_("Embedding URL is required when Weaviate is enabled."))
	
	if not query:
		frappe.throw(_("Search query is required."))
	
	try:
		# Get the base URL from the embedding URL
		base_url = weaviate_settings.flagembedding__url.replace('/embed', '')
		
		# First check if Weaviate is accessible
		health_response = requests.get(f"{base_url}/health", timeout=10)
		
		if not health_response.ok:
			frappe.throw(_("❌ Cannot connect to embedding service. Please check if the service is running."))
		
		health_data = health_response.json()
		weaviate_status = health_data.get('weaviate', 'unknown')
		
		if weaviate_status != 'connected':
			frappe.throw(_("❌ Weaviate is not connected. Status: {0}").format(weaviate_status))
		
		# Perform semantic search using the filter_products endpoint
		search_data = {
			"query": query,
			"limit": int(limit)
		}
		
		search_response = requests.post(f"{base_url}/filter_products", json=search_data, timeout=30)
		
		if not search_response.ok:
			frappe.throw(_("❌ Search failed: {0}").format(search_response.text))
		
		search_result = search_response.json()
		products = search_result.get('products', [])
		

		
		# Keep all results - let the user decide what's relevant
		# The issue is with search quality, not filtering
		
		# If no products found, try searching documents with category 'product'
		if not products:
			frappe.msgprint(_("ℹ️ No products found in Product class, searching in Document class..."), indicator="blue")
			
			# Search documents with category filter
			doc_search_data = {
				"query": query,
				"limit": int(limit),
				"category": "product"
			}
			
			doc_search_response = requests.post(f"{base_url}/search", json=doc_search_data, timeout=30)
			
			if doc_search_response.ok:
				doc_result = doc_search_response.json()
				documents = doc_result.get('documents', [])
				
				# Convert documents to product format
				products = []
				for doc in documents:
					metadata = doc.get('metadata', {})
					products.append({
						"item_code": metadata.get('item_code', ''),
						"item_name": metadata.get('item_name', ''),
						"brand": metadata.get('brand', ''),
						"item_group": metadata.get('item_group', ''),
						"description": metadata.get('description', ''),
						"created_at": doc.get('created_at', ''),
						"score": doc.get('score', 0)
					})
				
				# Keep all results - let the user decide what's relevant
		
		frappe.msgprint(_("🔍 Found {0} products matching '{1}'").format(len(products), query), indicator="green")
		
		return {
			"products": products,
			"query": query,
			"count": len(products)
		}
		
	except requests.exceptions.ConnectionError:
		frappe.throw(_("❌ Cannot connect to embedding service. Please check if the service is running."))
	except requests.exceptions.Timeout:
		frappe.throw(_("❌ Connection timeout. Please try again."))
	except Exception as e:
		frappe.log_error(f"Semantic search failed: {str(e)}", "Weaviate Search Error")
		frappe.throw(_("Failed to perform semantic search: {0}").format(str(e)))


@frappe.whitelist()
def reload_all_items_to_weaviate():
	"""Reload all items to Weaviate - delete old and upload new where enabled = 1"""
	# Get the Weaviate Settings document
	weaviate_settings = frappe.get_doc("Weaviate Settings")
	
	if not weaviate_settings.enabled:
		frappe.throw(_("Weaviate must be enabled to reload items."))
	
	if not weaviate_settings.flagembedding__url:
		frappe.throw(_("Embedding URL is required when Weaviate is enabled."))
	
	# Start background job
	frappe.enqueue(
		method=weaviate_settings._reload_all_items_to_weaviate_background,
		queue='long',
		timeout=3600,  # 1 hour timeout
		job_name=f"weaviate_reload_{weaviate_settings.name}",
		now=False
	)
	
	frappe.msgprint(
		_("🔄 Background job started! Check the progress in the background jobs section."),
		indicator="blue"
	)


@frappe.whitelist()
def get_progress():
	"""Get current progress for frontend"""
	try:
		# Get the Weaviate Settings document
		weaviate_settings = frappe.get_doc("Weaviate Settings")
		cache_key = f"weaviate_progress_{weaviate_settings.name}"
		progress_data = frappe.cache().get_value(cache_key)
		
		if progress_data:
			return {
				'progress': progress_data.get('progress', 0),
				'total': progress_data.get('total', 0),
				'current': progress_data.get('current', 0),
				'message': progress_data.get('message', ''),
				'timestamp': progress_data.get('timestamp', ''),
				'status': 'running'
			}
		else:
			return {
				'progress': 0,
				'total': 0,
				'current': 0,
				'message': 'No progress data available',
				'timestamp': '',
				'status': 'not_started'
			}
			
	except Exception as e:
		frappe.logger().error(f"Failed to get progress: {str(e)}")
		return {
			'progress': 0,
			'total': 0,
			'current': 0,
			'message': f'Error: {str(e)}',
			'timestamp': '',
			'status': 'error'
		}


@frappe.whitelist()
def export_weaviate_items():
	"""Export all items from Weaviate to an Excel file."""
	# Get the Weaviate Settings document
	weaviate_settings = frappe.get_doc("Weaviate Settings")
	
	if not weaviate_settings.enabled:
		frappe.throw(_("Weaviate must be enabled to export items."))
	
	if not weaviate_settings.flagembedding__url:
		frappe.throw(_("Embedding URL is required when Weaviate is enabled."))
	
	try:
		# First check if Weaviate is accessible
		base_url = weaviate_settings.flagembedding__url.replace('/embed', '')
		health_response = requests.get(f"{base_url}/health", timeout=10)
		
		if not health_response.ok:
			frappe.throw(_("❌ Cannot connect to embedding service. Please check if the service is running."))
		
		health_data = health_response.json()
		frappe.msgprint(_("🔍 Weaviate Health Status: {0}").format(health_data.get('weaviate', 'unknown')), indicator="blue")
		
		# Check if Weaviate is connected
		weaviate_status = health_data.get('weaviate', 'unknown')
		if weaviate_status != 'connected':
			frappe.throw(_("❌ Weaviate is not connected. Status: {0}\n\n💡 To fix this:\n1. Start Weaviate service (docker run -d -p 8080:8080 semitechnologies/weaviate:latest)\n2. Ensure Weaviate is accessible at http://localhost:8080\n3. Restart the embedding API service").format(weaviate_status))
		
		# Try to get items from different endpoints
		items = []
		
		# First try to get products from Product class
		try:
			products_response = requests.get(f"{base_url}/list_products?limit=5000", timeout=30)
			
			if products_response.ok:
				products_data = products_response.json()
				all_products = products_data.get('products', [])
				
				if all_products:
					# Convert products to document format for consistency
					for product in all_products:
						doc_item = {
							'document_id': f"product_{product.get('item_code', 'unknown')}",
							'content': product.get('searchable_text', ''),
							'category': 'product',
							'created_at': product.get('created_at', ''),
							'metadata': {
								'item_code': product.get('item_code', ''),
								'item_name': product.get('item_name', ''),
								'brand': product.get('brand', ''),
								'item_group': product.get('item_group', ''),
								'description': product.get('description', '')
							}
						}
						items.append(doc_item)
		except Exception as e:
			pass
		
		# If no products found, try documents with category 'product'
		if not items:
			try:
				documents_response = requests.get(f"{base_url}/list?limit=5000", timeout=30)
				
				if documents_response.ok:
					documents_data = documents_response.json()
					all_documents = documents_data.get('documents', [])
					
					# Filter for documents with category 'product'
					product_documents = [doc for doc in all_documents if doc.get('category') == 'product']
					
					if product_documents:
						items.extend(product_documents)
			except Exception as e:
				pass
		
		if not items:
			frappe.msgprint(_("ℹ️ No items found in Weaviate to export."), indicator="yellow")
			return None
		
		# Create Excel workbook
		wb = openpyxl.Workbook()
		ws = wb.active
		ws.title = "Weaviate Product Items"
		
		# Headers for product documents
		headers = [
			_("Document ID"),
			_("Content"),
			_("Category"),
			_("Created At"),
			_("Item Code"),
			_("Item Name"),
			_("Brand"),
			_("Item Group"),
			_("Description"),
			_("Metadata")
		]
		
		# Set column headers
		for col_num, header in enumerate(headers, 1):
			ws.cell(row=1, column=col_num).value = header
			ws.cell(row=1, column=col_num).font = Font(bold=True)
			ws.cell(row=1, column=col_num).alignment = Alignment(horizontal='center')
		
		# Fill data rows
		for row_num, item in enumerate(items, 2):
			col_num = 1
			
			# Document fields
			ws.cell(row=row_num, column=col_num).value = item.get('document_id', ''); col_num += 1
			ws.cell(row=row_num, column=col_num).value = item.get('content', ''); col_num += 1
			ws.cell(row=row_num, column=col_num).value = item.get('category', ''); col_num += 1
			ws.cell(row=row_num, column=col_num).value = item.get('created_at', ''); col_num += 1
			
			# Extract product fields from metadata
			metadata = item.get('metadata', {})
			ws.cell(row=row_num, column=col_num).value = metadata.get('item_code', ''); col_num += 1
			ws.cell(row=row_num, column=col_num).value = metadata.get('item_name', ''); col_num += 1
			ws.cell(row=row_num, column=col_num).value = metadata.get('brand', ''); col_num += 1
			ws.cell(row=row_num, column=col_num).value = metadata.get('item_group', ''); col_num += 1
			ws.cell(row=row_num, column=col_num).value = metadata.get('description', ''); col_num += 1
			ws.cell(row=row_num, column=col_num).value = json.dumps(metadata)
		
		# Auto-size columns
		for col in ws.columns:
			max_length = 0
			for cell in col:
				if cell.value:
					try:
						if isinstance(cell.value, str):
							max_length = max(max_length, len(cell.value))
						else:
							max_length = max(max_length, len(str(cell.value)))
					except:
						pass
			adjusted_width = min(max_length + 2, 50)  # Cap at 50 characters
			ws.column_dimensions[openpyxl.utils.get_column_letter(col[0].column)].width = adjusted_width
		
		# Add header style
		header_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
		for row in ws.iter_rows(min_row=1, max_row=1):
			for cell in row:
				cell.fill = header_fill
		
		# Add data style
		data_fill = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
		for row in ws.iter_rows(min_row=2, max_row=len(items) + 1):
			for cell in row:
				cell.fill = data_fill
		
		# Create a BytesIO object to hold the Excel file
		excel_file = BytesIO()
		wb.save(excel_file)
		excel_file.seek(0)
		
		# Create a base64 encoded string
		base64_encoded_file = base64.b64encode(excel_file.getvalue()).decode('utf-8')
		
		frappe.msgprint(_("✅ Successfully exported {0} items to Excel!").format(len(items)), indicator="green")
		return base64_encoded_file
		
	except requests.exceptions.ConnectionError:
		frappe.throw(_("❌ Cannot connect to embedding service. Please check if the service is running."))
	except requests.exceptions.Timeout:
		frappe.throw(_("❌ Connection timeout. Please try again."))
	except Exception as e:
		frappe.log_error(f"Weaviate export failed: {str(e)}", "Weaviate Export Error")
		frappe.throw(_("Failed to export items from Weaviate: {0}").format(str(e)))
