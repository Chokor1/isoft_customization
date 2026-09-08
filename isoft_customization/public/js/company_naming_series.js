// Company-wise naming series on the desk.
//
// Boot carries isoft_company_naming_series, built by
// isoft_naming_series_settings.boot_session and present only while the
// setting is enabled:
//
//     {doctype: {companies: {company: {series: [...], default: s}}, unassigned: [...]}}
//
// On every form refresh, and whenever Company changes on a new document, the
// naming_series dropdown is rebuilt from that company's list. A series assigned
// to a company is exclusive, so a company with no rows only gets `unassigned`
// (possibly nothing; the server then refuses to name the document).
//
// This coexists with erpnext's naming_series_per_user_override.js, which
// wraps Form.refresh the same way and sets the dropdown to the user's list.
// isoft_customization loads before erpnext, so a wrap installed directly from
// app_ready would sit inside theirs and be overwritten on every refresh. The
// wrap below is installed after the app_ready handlers have all run, so it
// is outermost, runs last, and intersects with whatever the per-user rule
// allows.

frappe.provide("isoft.company_naming_series");

$(document).on("app_ready", function () {
	if (!frappe.boot.isoft_company_naming_series) return;
	isoft.company_naming_series.config = frappe.boot.isoft_company_naming_series;

	setTimeout(function () {
		const original_refresh = frappe.ui.form.Form.prototype.refresh;
		frappe.ui.form.Form.prototype.refresh = function (...args) {
			const result = original_refresh.apply(this, args);
			try {
				isoft.company_naming_series.apply(this);
			} catch (e) {
				console.error("company naming series", e); // eslint-disable-line no-console
			}
			return result;
		};
	}, 0);
});

isoft.company_naming_series.watched = {};

isoft.company_naming_series.watch_company = function (doctype) {
	if (isoft.company_naming_series.watched[doctype]) return;
	isoft.company_naming_series.watched[doctype] = true;

	frappe.model.on(doctype, "company", function (fieldname, value, doc) {
		if (cur_frm && cur_frm.doc && cur_frm.doc.name === doc.name) {
			isoft.company_naming_series.apply(cur_frm);
		}
	});
};

// The per-user rule for this doctype and company, or null when unrestricted.
isoft.company_naming_series.per_user_allowed = function (doctype, company) {
	const ns = window.erpnext && erpnext.naming_series_per_user;
	const by_company = ns && ns.assignments && ns.assignments[doctype];
	if (!by_company) return null;
	const list = by_company[company] || by_company[""];
	return list && list.length ? list : null;
};

// Series `company` may use on `doctype`, after the per-user rule (possibly
// empty), or null when nothing restricts it. Also for site Client Scripts that rebuild the
// naming_series dropdown themselves (e.g. Payment Entry by payment type):
// intersect their list with this one so both rules hold.
isoft.company_naming_series.allowed = function (doctype, company) {
	const cfg = isoft.company_naming_series.config && isoft.company_naming_series.config[doctype];
	if (!cfg) return null;

	const entry = company && cfg.companies[company];
	let allowed = entry ? entry.series.slice() : cfg.unassigned.slice();
	if (!allowed.length) return [];

	const per_user = isoft.company_naming_series.per_user_allowed(doctype, company);
	if (per_user) {
		const both = allowed.filter((s) => per_user.includes(s));
		// An empty intersection is a configuration clash; show the company's
		// list and let the server-side per-user check report it on save.
		if (both.length) allowed = both;
	}
	return allowed;
};

isoft.company_naming_series.apply = function (frm) {
	const cfg = isoft.company_naming_series.config[frm.doctype];
	if (!cfg || !frm.fields_dict.naming_series) return;

	isoft.company_naming_series.watch_company(frm.doctype);

	const company = frm.doc.company;
	const entry = company && cfg.companies[company];
	const allowed = isoft.company_naming_series.allowed(frm.doctype, company);
	if (!allowed) return;

	if (!allowed.length) {
		// Every series is claimed by other companies. Show nothing rather than
		// a series the server will reject; the save error names the fix.
		frm.set_df_property("naming_series", "options", "");
		if (frm.doc.__islocal && frm.doc.naming_series) frm.set_value("naming_series", "");
		frm.refresh_field("naming_series");
		return;
	}

	frm.set_df_property("naming_series", "options", allowed.join("\n"));

	if (frm.doc.__islocal) {
		// Form objects are reused across documents of a doctype, so key on the
		// document too; otherwise a new document would inherit the last one's state.
		const key = frm.doc.name + "|" + (company || "");
		const company_changed = frm.__isoft_ns_key !== key;
		frm.__isoft_ns_key = key;

		let value = frm.doc.naming_series;
		if (company_changed && entry && allowed.includes(entry.default)) {
			value = entry.default;
		} else if (!allowed.includes(value)) {
			value = entry && allowed.includes(entry.default) ? entry.default : allowed[0];
		}
		if (value !== frm.doc.naming_series) {
			frm.set_value("naming_series", value);
		}
	}

	frm.refresh_field("naming_series");
};
