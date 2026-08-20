// Copyright (c) 2025, Frappe Technologies and contributors
// For license information, please see license.txt

// Global helper functions
function show_progress(frm, message, percentage, type = 'info') {
	// Determine colors based on type
	let bg_color = '#f8f9fa';
	let progress_color = '#007bff';
	
	if (type === 'error') {
		bg_color = '#f8d7da';
		progress_color = '#dc3545';
	} else if (type === 'success') {
		bg_color = '#d4edda';
		progress_color = '#28a745';
	}
	
	// Create progress HTML for the field
	let progress_html = '';
	
	if (percentage < 100) {
		// Show progress bar during upload
		progress_html = `
			<div style="margin: 10px 0; padding: 10px; background: ${bg_color}; border-radius: 5px;">
				<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-size: 12px; color: #666;">
					<span>${message || 'Processing...'}</span>
					<span>${Math.round(percentage)}%</span>
				</div>
				<div style="background: #e9ecef; border-radius: 8px; overflow: hidden; height: 12px;">
					<div style="background: ${progress_color}; height: 100%; width: ${percentage}%; transition: width 0.3s ease;"></div>
				</div>
			</div>
		`;
	} else {
		// Show completion message
		progress_html = `
			<div style="margin: 10px 0; padding: 10px; background: ${bg_color}; border-radius: 5px; color: #155724;">
				<strong>✅ Upload Complete!</strong> ${message}
			</div>
		`;
	}
	
	// Update the progress field
	try {
		frm.set_df_property('progress', 'options', progress_html);
		frm.refresh_field('progress');
	} catch (e) {
		console.error('Error updating progress field:', e);
	}
}

function start_progress_monitoring(frm) {
	// Clear any existing interval
	if (frm.progress_interval) {
		clearInterval(frm.progress_interval);
	}

	// Start progress monitoring
	frm.progress_interval = setInterval(function() {
		frm.call({
			method: 'get_progress',
			callback: function(progress_r) {
				if (progress_r.message && progress_r.message.progress !== undefined) {
					var progress_data = progress_r.message;
					
					// Create message with current/total
					let message = '';
					if (progress_data.current && progress_data.total) {
						message = `${progress_data.current} / ${progress_data.total} items`;
					} else {
						message = progress_data.message || 'Processing...';
					}
					
					// Update progress display
					show_progress(
						frm,
						message,
						progress_data.progress,
						progress_data.progress >= 100 ? 'success' : 'info'
					);
					
					// Check if completed
					if (progress_data.progress >= 100) {
						clearInterval(frm.progress_interval);
						frm.progress_interval = null;
					}
				} else {
					// No progress data available
					show_progress(frm, 'No active job found', 0, 'info');
				}
			}
		});
	}, 2000); // Check every 2 seconds
}

function download_excel_file(base64_data, filename) {
	// Convert base64 to blob
	const byteCharacters = atob(base64_data);
	const byteNumbers = new Array(byteCharacters.length);
	for (let i = 0; i < byteCharacters.length; i++) {
		byteNumbers[i] = byteCharacters.charCodeAt(i);
	}
	const byteArray = new Uint8Array(byteNumbers);
	const blob = new Blob([byteArray], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
	
	// Create download link
	const link = document.createElement('a');
	link.href = URL.createObjectURL(blob);
	link.download = filename;
	link.click();
}

function show_search_results(products, query) {
	// Create a modal to display search results
	let modal = document.createElement('div');
	modal.style.cssText = `
		position: fixed;
		top: 0;
		left: 0;
		width: 100%;
		height: 100%;
		background: rgba(0,0,0,0.5);
		z-index: 9999;
		display: flex;
		justify-content: center;
		align-items: center;
	`;
	
	let content = document.createElement('div');
	content.style.cssText = `
		background: white;
		padding: 20px;
		border-radius: 8px;
		max-width: 800px;
		max-height: 80vh;
		overflow-y: auto;
		box-shadow: 0 4px 20px rgba(0,0,0,0.3);
	`;
	
	let html = `
		<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
			<h3 style="margin: 0; color: #333;">🔍 Semantic Search Results</h3>
			<button onclick="this.closest('.search-modal').remove()" style="background: #dc3545; color: white; border: none; padding: 8px 12px; border-radius: 4px; cursor: pointer;">✕</button>
		</div>
		<p style="margin-bottom: 15px; color: #666;"><strong>Query:</strong> "${query}"</p>
		<p style="margin-bottom: 20px; color: #666;"><strong>Found:</strong> ${products.length} products</p>
	`;
	
	if (products.length > 0) {
		html += '<div style="display: grid; gap: 15px;">';
		products.forEach((product, index) => {
			let scoreText = '';
			if (product.score !== undefined && product.score !== null) {
				scoreText = `Score: ${product.score.toFixed(3)}`;
			}
			html += `
				<div style="border: 1px solid #e0e0e0; border-radius: 6px; padding: 15px; background: #f8f9fa;">
					<div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 8px;">
						<h4 style="margin: 0; color: #007bff;">${product.item_name || 'N/A'}</h4>
						<span style="font-size: 12px; color: #666; font-weight: bold;">${scoreText}</span>
					</div>
					<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; font-size: 13px;">
						<div><strong>Item Code:</strong> ${product.item_code || 'N/A'}</div>
						<div><strong>Brand:</strong> ${product.brand || 'N/A'}</div>
						<div><strong>Item Group:</strong> ${product.item_group || 'N/A'}</div>
						<div><strong>Created:</strong> ${product.created_at ? new Date(product.created_at).toLocaleDateString() : 'N/A'}</div>
					</div>
					${product.description ? `<div style="margin-top: 8px; font-size: 13px; color: #555;"><strong>Description:</strong> ${product.description}</div>` : ''}
				</div>
			`;
		});
		html += '</div>';
	} else {
		html += '<p style="text-align: center; color: #666; font-style: italic;">No products found matching your query.</p>';
	}
	
	content.innerHTML = html;
	content.className = 'search-modal';
	modal.appendChild(content);
	document.body.appendChild(modal);
	
	// Close modal when clicking outside
	modal.addEventListener('click', function(e) {
		if (e.target === modal) {
			modal.remove();
		}
	});
}

// Form event handler
frappe.ui.form.on('Weaviate Settings', {
	refresh: function(frm) {
		// Add Reload All Items to Weaviate button
		frm.add_custom_button(__('Reload All Items to Weaviate'), function() {
			frm.call({
				method: 'reload_all_items_to_weaviate',
				callback: function(r) {
					if (r.message) {
						frappe.msgprint(r.message);
					}
					// Start progress monitoring
					start_progress_monitoring(frm);
				}
			});
		}, __('Actions'));

		// Add Export Weaviate Items to Excel button
		frm.add_custom_button(__('Export Weaviate Items to Excel'), function() {
			frm.call({
				method: 'export_weaviate_items',
				callback: function(r) {
					if (r.message) {
						download_excel_file(r.message, 'weaviate_items_export.xlsx');
					}
				}
			});
		});

		// Add Test Delete Document button
		frm.add_custom_button(__('Test Delete Document'), function() {
			// Prompt user for document_id
			let document_id = prompt('Enter Document ID to delete (e.g., item_0012-Green):');
			if (document_id && document_id.trim()) {
				frm.call({
					method: 'test_delete_document',
					args: {
						document_id: document_id.trim()
					},
					callback: function(r) {
						if (r.message) {
							frappe.msgprint(r.message);
						}
					}
				});
			} else if (document_id !== null) {
				frappe.msgprint('Please enter a valid Document ID');
			}
		});

		// Add Delete All Product Documents button
		frm.add_custom_button(__('Delete All Product Documents'), function() {
			// Confirm deletion
			if (confirm('Are you sure you want to delete ALL product documents from Weaviate? This action cannot be undone.')) {
				frm.call({
					method: 'delete_all_product_documents',
					callback: function(r) {
						if (r.message) {
							frappe.msgprint(r.message);
						}
					}
				});
			}
		});

		// Add Semantic Search button
		frm.add_custom_button(__('Semantic Search'), function() {
			// Create a dialog for search
			let search_query = prompt('Enter your search query (e.g., "laptop accessories", "apple products", "power adapter"):');
			if (search_query && search_query.trim()) {
				frm.call({
					method: 'semantic_search_products',
					args: {
						query: search_query.trim(),
						limit: 10
					},
					callback: function(r) {
						if (r.message && r.message.products) {
							show_search_results(r.message.products, search_query);
						} else {
							frappe.msgprint('No results found or search failed.');
						}
					}
				});
			}
		});
	}
});
