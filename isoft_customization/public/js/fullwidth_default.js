// Full-width Desk by default, without editing the framework.
//
// Frappe stores the preference in localStorage.container_fullwidth and treats an
// absent key as "not full width". The fork changed that default by flipping two
// literals in frappe/ui/toolbar/toolbar.js:
//
//     JSON.parse(localStorage.container_fullwidth || 'false')   ->   || 'true'
//
// Seeding the key when it is absent is exactly equivalent: both call sites then
// read a real 'true' instead of falling back. A user who turns full width off
// writes 'false', the key is no longer absent, and nothing here touches it again --
// so the choice sticks, just as it did with the core change.
//
// The re-apply below covers load order. app_include_js may run after the toolbar has
// already read the (then absent) key, in which case the body would keep Frappe's
// narrow layout until the next navigation; calling Frappe's own applier once the key
// exists settles it on the first paint.

(function () {
	try {
		if (localStorage.getItem('container_fullwidth') === null) {
			localStorage.setItem('container_fullwidth', 'true');
		}
	} catch (e) {
		// Private browsing or a full quota — leave Frappe's default alone.
		return;
	}

	function apply() {
		try {
			if (frappe.ui && frappe.ui.toolbar && frappe.ui.toolbar.set_fullwidth_if_enabled) {
				frappe.ui.toolbar.set_fullwidth_if_enabled();
			} else if (window.$ && document.body) {
				$(document.body).toggleClass(
					'full-width',
					JSON.parse(localStorage.getItem('container_fullwidth') || 'false')
				);
			}
		} catch (e) {
			// Never let a layout preference break desk startup.
		}
	}

	apply();
	if (window.$) $(document).ready(apply);
})();
