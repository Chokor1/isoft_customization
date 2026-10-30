frappe.ui.form.on('Item Default Rules', {
	refresh(frm) {
		if (!frm.doc.enabled) return;
		frm.add_custom_button(__('Apply to existing items'), () => {
			frappe.call({ method: 'isoft_customization.item_default_rules.apply_to_existing_items', args: { dry_run: 1 }, freeze: true }).then(r => {
				const n = (r.message || {}).would_update || 0;
				if (!n) { frappe.msgprint(__('No item needs a change: every matching item already has its defaults.')); return; }
				frappe.confirm(__('{0} item(s) have an empty default that a rule would fill. Fill them now?', [n]), () => {
					frappe.call({ method: 'isoft_customization.item_default_rules.apply_to_existing_items', args: { dry_run: 0 }, freeze: true })
						.then(r2 => frappe.msgprint(__('{0} item(s) updated.', [(r2.message || {}).updated || 0])));
				});
			});
		});
	}
});
