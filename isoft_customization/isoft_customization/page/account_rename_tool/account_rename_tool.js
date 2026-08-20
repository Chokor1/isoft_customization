frappe.pages['account-rename-tool'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Account Rename Tool'),
		single_column: true,
	});
	new AccountRenameTool(page);
};

class AccountRenameTool {
	constructor(page) {
		this.page = page;
		this.rows = [];
		this.make_styles();
		this.make_layout();
		this.make_controls();
		this.bind_actions();
	}

	make_styles() {
		if (document.getElementById('art-styles')) document.getElementById('art-styles').remove();
		const css = `
		.art-wrap { max-width: 1600px; margin: 0 auto; }
		.art-card { background: var(--card-bg, #fff); border: 1px solid var(--border-color, #e2e6ea);
			border-radius: 10px; padding: 16px 18px; margin-bottom: 16px; }
		.art-filters { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; align-items: end; }
		.art-filters .art-cell .frappe-control { margin: 0; }
		.art-actions { display: flex; gap: 10px; align-items: center; margin-top: 14px; flex-wrap: wrap; }
		.art-toolbar { display: flex; gap: 12px; align-items: center; justify-content: space-between;
			margin-bottom: 10px; flex-wrap: wrap; }
		.art-count { color: var(--text-muted, #8d99a6); font-size: 12px; }
		.art-count b { color: var(--text-color, #1f272e); }
		.art-search { max-width: 260px; }
		.art-table-wrap { overflow: auto; border: 1px solid var(--border-color, #e2e6ea); border-radius: 10px; }
		table.art-table { width: 100%; border-collapse: collapse; font-size: 13px; }
		table.art-table th, table.art-table td { padding: 8px 10px; border-bottom: 1px solid var(--border-color, #edf0f2);
			text-align: left; vertical-align: middle; white-space: nowrap; }
		table.art-table thead th { position: sticky; top: 0; background: var(--subtle-fg, #f4f5f6);
			z-index: 1; font-weight: 600; color: var(--text-muted, #6c7680); }
		table.art-table tbody tr.art-edited { background: rgba(255, 196, 0, 0.10); }
		table.art-table tbody tr.art-done { background: rgba(40, 167, 69, 0.10); }
		table.art-table tbody tr.art-fail { background: rgba(220, 53, 69, 0.10); }
		table.art-table input.art-input { width: 100%; min-width: 120px; border: 1px solid var(--border-color, #d1d8dd);
			border-radius: 6px; padding: 5px 8px; background: var(--control-bg, #fff); color: var(--text-color, #1f272e); }
		table.art-table input.art-input.art-changed { border-color: var(--primary, #2490ef); font-weight: 600; }
		table.art-table input.art-input:focus { border-color: var(--primary, #2490ef); outline: none; }
		.art-id { font-family: var(--font-mono, monospace); color: var(--text-muted, #6c7680); }
		.art-status { font-weight: 600; }
		.art-empty { padding: 40px; text-align: center; color: var(--text-muted, #8d99a6); }
		@media (max-width: 768px) { .art-filters { grid-template-columns: 1fr 1fr; } }
		`;
		const style = document.createElement('style');
		style.id = 'art-styles';
		style.textContent = css;
		document.head.appendChild(style);
	}

	make_layout() {
		const $body = $(this.page.body);
		$body.html(`
			<div class="art-wrap">
				<div class="art-card">
					<div class="art-filters">
						<div class="art-cell art-company"></div>
						<div class="art-cell art-roottype"></div>
						<div class="art-cell art-textfilter"></div>
						<div class="art-cell art-groups"></div>
					</div>
					<div class="art-actions">
						<button class="btn btn-primary btn-sm art-load">${frappe.utils.icon('list', 'xs')} ${__('Load Accounts')}</button>
						<span class="art-count art-loadinfo"></span>
					</div>
				</div>

				<div class="art-toolbar">
					<input type="text" class="form-control input-sm art-search" placeholder="${__('Search loaded accounts...')}">
					<span class="art-count art-editinfo"></span>
				</div>

				<div class="art-table-wrap">
					<table class="art-table">
						<thead>
							<tr>
								<th style="width:36px">#</th>
								<th>${__('Account ID')}</th>
								<th style="width:160px">${__('Number')}</th>
								<th>${__('Account Name')}</th>
								<th style="width:120px">${__('Status')}</th>
							</tr>
						</thead>
						<tbody class="art-tbody"></tbody>
					</table>
					<div class="art-empty art-emptymsg">${__('Set filters and click Load Accounts to begin.')}</div>
				</div>
			</div>
		`);
		this.$tbody = $body.find('.art-tbody');
		this.$empty = $body.find('.art-emptymsg');
	}

	make_controls() {
		const $body = $(this.page.body);
		this.company_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Link', options: 'Company', label: __('Company'), fieldname: 'company', reqd: 1 },
			parent: $body.find('.art-company'),
			render_input: true,
		});
		this.company_field.set_value(frappe.defaults.get_default('company') || '');

		this.roottype_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Select', label: __('Root Type'), fieldname: 'root_type',
				options: ['', 'Asset', 'Liability', 'Equity', 'Income', 'Expense'].join('\n') },
			parent: $body.find('.art-roottype'),
			render_input: true,
		});

		this.textfilter_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Data', label: __('Name / Number contains'), fieldname: 'text' },
			parent: $body.find('.art-textfilter'),
			render_input: true,
		});

		this.groups_field = frappe.ui.form.make_control({
			df: { fieldtype: 'Check', label: __('Include Group Accounts'), fieldname: 'include_groups' },
			parent: $body.find('.art-groups'),
			render_input: true,
		});
	}

	bind_actions() {
		const $body = $(this.page.body);
		$body.find('.art-load').on('click', () => this.load_accounts());
		$body.find('.art-search').on('input', (e) => this.apply_search(e.target.value));
		this.page.set_primary_action(__('Rename Accounts'), () => this.rename_all(), 'edit');

		// Size the table to fill the remaining viewport so the page itself never scrolls.
		this.$tablewrap = $body.find('.art-table-wrap');
		this._resize = () => this.adjust_height();
		$(window).on('resize.art', frappe.utils.debounce(this._resize, 100));
		setTimeout(() => this.adjust_height(), 0);
	}

	adjust_height() {
		if (!this.$tablewrap || !this.$tablewrap.length) return;
		const el = this.$tablewrap[0];
		const top = el.getBoundingClientRect().top; // viewport-relative distance to table top
		const avail = window.innerHeight - top - 32; // leave a bottom gap
		el.style.height = Math.max(180, avail) + 'px';

		// Second pass: eliminate any residual page scroll caused by container padding.
		const overflow = document.documentElement.scrollHeight - window.innerHeight;
		if (overflow > 0) {
			el.style.height = Math.max(180, el.offsetHeight - overflow - 8) + 'px';
		}
	}

	load_accounts() {
		const company = this.company_field.get_value();
		if (!company) {
			frappe.msgprint(__('Please select a Company first.'));
			return;
		}
		const filters = { company };
		if (!this.groups_field.get_value()) filters.is_group = 0;
		const rt = this.roottype_field.get_value();
		if (rt) filters.root_type = rt;

		frappe.call({
			method: 'frappe.client.get_list',
			args: {
				doctype: 'Account',
				filters,
				fields: ['name', 'account_name', 'account_number'],
				limit_page_length: 0,
				order_by: 'lft asc',
			},
			freeze: true,
			freeze_message: __('Loading accounts...'),
			callback: (r) => {
				let list = r.message || [];
				const q = (this.textfilter_field.get_value() || '').toLowerCase();
				if (q) {
					list = list.filter((a) =>
						(a.account_name || '').toLowerCase().includes(q) ||
						(a.account_number || '').toLowerCase().includes(q) ||
						(a.name || '').toLowerCase().includes(q));
				}
				this.rows = list.map((a) => ({
					account: a.name,
					orig_number: a.account_number || '',
					orig_name: a.account_name || '',
					number: a.account_number || '',
					name: a.account_name || '',
					status: '',
				}));
				this.render_rows();
				$(this.page.body).find('.art-loadinfo').html(__('Loaded <b>{0}</b> accounts', [this.rows.length]));
			},
		});
	}

	render_rows() {
		this.$tbody.empty();
		if (!this.rows.length) {
			this.$empty.show().text(__('No accounts found for these filters.'));
			this.update_edit_info();
			return;
		}
		this.$empty.hide();
		this.rows.forEach((row, i) => {
			const $tr = $(`
				<tr data-idx="${i}">
					<td>${i + 1}</td>
					<td class="art-id">${frappe.utils.escape_html(row.account)}</td>
					<td><input class="art-input art-f-number" value="${frappe.utils.escape_html(row.number)}"></td>
					<td><input class="art-input art-f-name" value="${frappe.utils.escape_html(row.name)}"></td>
					<td class="art-status">${row.status || ''}</td>
				</tr>
			`);
			$tr.find('.art-f-number').on('input', (e) => { row.number = e.target.value; this.mark(row, $tr); });
			$tr.find('.art-f-name').on('input', (e) => { row.name = e.target.value; this.mark(row, $tr); });
			this.$tbody.append($tr);
		});
		this.update_edit_info();
		this.adjust_height();
	}

	is_changed(row) {
		return (row.number || '') !== (row.orig_number || '') || (row.name || '') !== (row.orig_name || '');
	}

	mark(row, $tr) {
		const numChanged = (row.number || '') !== (row.orig_number || '');
		const nameChanged = (row.name || '') !== (row.orig_name || '');
		$tr.find('.art-f-number').toggleClass('art-changed', numChanged);
		$tr.find('.art-f-name').toggleClass('art-changed', nameChanged);
		$tr.toggleClass('art-edited', numChanged || nameChanged);
		this.update_edit_info();
	}

	changed_rows() {
		return this.rows.filter((r) => this.is_changed(r));
	}

	update_edit_info() {
		const n = this.changed_rows().length;
		$(this.page.body).find('.art-editinfo').html(
			n ? __('<b>{0}</b> account(s) edited — ready to rename', [n]) : __('No changes yet'));
	}

	apply_search(term) {
		const q = (term || '').toLowerCase();
		this.$tbody.find('tr').each(function () {
			const txt = $(this).find('.art-id').text().toLowerCase() + ' ' +
				($(this).find('.art-f-number').val() || '').toLowerCase() + ' ' +
				($(this).find('.art-f-name').val() || '').toLowerCase();
			$(this).toggle(!q || txt.includes(q));
		});
	}

	rename_all() {
		const targets = this.changed_rows();
		if (!targets.length) {
			frappe.msgprint(__('Nothing to do. Edit a Number or Name on at least one row.'));
			return;
		}
		const blank = targets.filter((r) => !(r.name || '').trim());
		if (blank.length) {
			frappe.msgprint(__('Account Name cannot be empty ({0} row(s)). Please fix before renaming.', [blank.length]));
			return;
		}
		frappe.confirm(
			__('Rename {0} account(s) and cascade the new IDs into all linked records? This cannot be undone.', [targets.length]),
			() => this.run(targets),
		);
	}

	run(targets) {
		let idx = 0, done = 0, failed = 0;
		const total = targets.length;
		// Freeze exactly ONCE; update the message text as we progress.
		frappe.dom.freeze(__('Renaming... 0 / {0}', [total]));
		const set_progress = (n) => {
			$('.freeze-message .lead').text(__('Renaming... {0} / {1}', [n, total]));
		};

		let finished = false;
		const finish = () => {
			if (finished) return;
			finished = true;
			frappe.dom.unfreeze();
			this.update_edit_info();
			frappe.msgprint({
				title: __('Rename complete'),
				indicator: failed ? 'orange' : 'green',
				message: __('{0} renamed, {1} failed.', [done, failed]),
			});
		};

		const next = () => {
			if (idx >= total) return finish();
			const row = targets[idx++];
			set_progress(idx);

			const eff_name = (row.name || '').trim();
			const eff_number = (row.number || '').trim();
			const $tr = this.$tbody.find(`tr[data-idx="${this.rows.indexOf(row)}"]`);

			frappe.call({
				method: 'erpnext.accounts.doctype.account.account.update_account_number',
				args: { name: row.account, account_name: eff_name, account_number: eff_number },
				callback: (r) => {
					if (r.message) row.account = r.message;
					row.orig_name = eff_name;
					row.orig_number = eff_number;
					row.name = eff_name;
					row.number = eff_number;
					row.status = __('✔ Renamed');
					$tr.removeClass('art-edited').addClass('art-done');
					$tr.find('.art-id').text(row.account);
					$tr.find('.art-f-number').val(eff_number).removeClass('art-changed');
					$tr.find('.art-f-name').val(eff_name).removeClass('art-changed');
					$tr.find('.art-status').text(row.status);
					done++;
					next();
				},
				error: () => {
					row.status = __('✖ Failed');
					$tr.removeClass('art-edited').addClass('art-fail');
					$tr.find('.art-status').text(row.status);
					failed++;
					next();
				},
			});
		};
		next();
	}
}
