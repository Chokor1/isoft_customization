// Pricing Rules Manager  (/app/pricing-rules-manager)
//
// Two screens switched from a tab row at the top of the page:
//   Rules              every selling rule of the company; search by title or by any
//                      item it covers; enable/disable, export, delete; a drawer to
//                      create or edit a rule and its items
//   Import from Excel  template -> settings -> upload -> preview -> create; one
//                      Pricing Rule per distinct discount in the file
// Every rule made here has the same fixed shape (selling, discount %, apply on item
// code, every customer); only the discount, the items and the dates are chosen. The
// server enforces that shape: isoft_customization/pricing_rules.py

(function () {
    'use strict';

const API = 'isoft_customization.pricing_rules.';
const PAGE = 'pricing-rules-manager';

// Page-level state shared by both screens.
const PRM = { go: null, $host: null, active: null, companies: null };

const SCREENS = [
    { key: 'rules',  label: 'Rules',             icon: 'fa-tags',   tone: 'pr-i-money', run: function () { screenRules(); } },
    { key: 'import', label: 'Import from Excel', icon: 'fa-upload', tone: 'pr-i-item',  run: function () { screenImport(); } }
];

frappe.pages[PAGE].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({ parent: wrapper, title: __('Pricing Rules Manager'), single_column: true });
    PRM.$host = $('<div class="prm-host"></div>').appendTo(page.main);
    screenShell();
};

// Back from a desk form (a rule opened in a new tab and edited, say): refresh.
frappe.pages[PAGE].on_page_show = function () {
    if (PRM.active === 'rules' && $('#pr-table').length) load();
};

function screenShell(initial) {
    const $c = PRM.$host;
    $c.off('.pr');
    $(document).off('.prdoc');
    let active = initial || PRM.active || localStorage.getItem('isoft_prm_screen') || 'rules';
    if (!SCREENS.some(s => s.key === active)) active = 'rules';

    $c.html(CSS + `
<div class="pr-shell">
    <nav class="pr-shell-nav" id="pr-nav">
        ${SCREENS.map(s => `<button type="button" data-screen="${s.key}" class="${s.key === active ? 'is-on' : ''}">
            <i class="fa ${s.icon} ${s.tone}"></i> ${esc(s.label)}</button>`).join('')}
        <span class="pr-fixed" title="Every rule made here has this shape; only the discount, items and dates change.">
            <i class="fa fa-lock"></i> Selling · Discount % · Per item · All customers
        </span>
        <span class="pr-company" title="Company"><i class="fa fa-building"></i>
            <select class="pr-input" id="pr-company"><option value="${esc(company())}">${esc(company() || 'Company…')}</option></select></span>
    </nav>
    <div class="pr-shell-body" id="pr-body"></div>
</div>`);

    companies().then(list => {
        if (!company() && list.length) setCompany(list[0]);
        $('#pr-company').html(list.map(c => `<option value="${esc(c)}" ${c === company() ? 'selected' : ''}>${esc(c)}</option>`).join(''));
    });

    $c.on('change.pr', '#pr-company', function () {
        setCompany(this.value);
        // Both screens depend on the company: the list, and the overlap check.
        I.preview = null;
        (SCREENS.filter(s => s.key === PRM.active)[0] || SCREENS[0]).run();
    });
    $c.on('click.pr', '#pr-nav button', function () {
        go($(this).attr('data-screen'));
    });
    go(active, true);

    function go(key, first) {
        if (!first && key === PRM.active) return;
        PRM.active = key;
        localStorage.setItem('isoft_prm_screen', key);
        $('#pr-nav button').removeClass('is-on').filter(`[data-screen="${key}"]`).addClass('is-on');
        (SCREENS.filter(s => s.key === key)[0] || SCREENS[0]).run();
    }
    PRM.go = go;
}

// ---------------------------------------------------------------------------
// shared
// ---------------------------------------------------------------------------

function esc(t) {
    return String(t == null ? '' : t).replace(/[&<>"']/g, c =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[c]));
}
// frappe.call returns a jQuery Deferred in v13 (no .catch); give callers a real Promise.
function call(method, args) {
    return new Promise((resolve, reject) => {
        frappe.call({ method: method, args: args, callback: r => resolve(r.message), error: reject });
    });
}
function company() {
    if (PRM.company === undefined) {
        PRM.company = localStorage.getItem('isoft_prm_company')
            || (frappe.defaults.get_user_default && frappe.defaults.get_user_default('Company')) || '';
    }
    return PRM.company;
}
function setCompany(c) {
    PRM.company = c || '';
    localStorage.setItem('isoft_prm_company', PRM.company);
}
function companies() {
    if (!PRM.companies) {
        PRM.companies = call('frappe.client.get_list',
            { doctype: 'Company', fields: ['name'], limit_page_length: 0, order_by: 'name asc' })
            .then(m => (m || []).map(c => c.name), () => []);
    }
    return PRM.companies;
}
function pct(v) {
    const n = Math.round((parseFloat(v) || 0) * 10000) / 10000;
    return String(n) + '%';
}
function userDate(d) { return d ? frappe.datetime.str_to_user(d) : ''; }
function today() { return frappe.datetime.get_today(); }
// Scoped to the host: on_page_load runs before the page is attached to the document.
function body() { return PRM.$host.find('#pr-body'); }

let priceListsPromise = null;
function priceLists() {
    if (!priceListsPromise) {
        priceListsPromise = call('frappe.client.get_list',
            { doctype: 'Price List', filters: { selling: 1, enabled: 1 }, fields: ['name'], limit_page_length: 0, order_by: 'name asc' })
            .then(m => (m || []).map(p => p.name), () => []);
    }
    return priceListsPromise;
}
function priceListOptions(selected) {
    return priceLists().then(list => `<option value="">Any price list</option>` +
        list.map(p => `<option value="${esc(p)}" ${p === selected ? 'selected' : ''}>${esc(p)}</option>`).join(''));
}

function download(method, args) {
    const qs = Object.keys(args || {}).map(k => k + '=' + encodeURIComponent(args[k])).join('&');
    window.open('/api/method/' + API + method + (qs ? '?' + qs : ''), '_blank');
}

const STATUS_CHIP = { Active: 'pr-chip-ok', Scheduled: 'pr-chip-brand', Expired: 'pr-chip-warn', Disabled: 'pr-chip-mute' };

// ---------------------------------------------------------------------------
// Rules screen
// ---------------------------------------------------------------------------

const S = {
    rules: [], conflicts: [], byName: {}, conflictByRule: {},
    q: '', status: localStorage.getItem('isoft_prm_status') || 'all',
    onlySimple: false, sel: new Set(), loading: false
};
const STATUS_TABS = [
    { key: 'all', label: 'All' },
    { key: 'active', label: 'Active' },
    { key: 'scheduled', label: 'Scheduled' },
    { key: 'expired', label: 'Expired' },
    { key: 'disabled', label: 'Disabled' },
    { key: 'conflicts', label: 'Conflicts', icon: 'fa-exclamation-triangle' }
];
const RESOLVE_API = 'isoft_customization.pricing_rule_conflicts.resolve_conflict';

function screenRules() {
    const $b = body();
    $b.off('.prr');
    S.sel = new Set();
    if (!STATUS_TABS.some(t => t.key === S.status)) S.status = 'all';
    $b.html(`
<div class="pr-root">
    <div class="pr-head">
        <div class="pr-head-text">
            <div class="pr-title"><i class="fa fa-tags"></i> Pricing Rules</div>
            <div class="pr-kpis" id="pr-kpis"></div>
        </div>
        <span class="pr-spacer"></span>
        <button class="pr-btn pr-btn-icon" id="pr-refresh" title="Reload"><i class="fa fa-refresh"></i></button>
        <button class="pr-btn" id="pr-to-import"><i class="fa fa-upload"></i> Import</button>
        <button class="pr-btn pr-btn-primary" id="pr-new"><i class="fa fa-plus"></i> New rule</button>
    </div>
    <div class="pr-alert" id="pr-alert" hidden></div>
    <div class="pr-filters">
        <div class="pr-tabs" id="pr-status"></div>
        <span class="pr-spacer"></span>
        <label class="pr-check" title="Hide rules this page cannot edit (item group, brand and transaction rules, margins…); they open in the desk form">
            <input type="checkbox" id="pr-simple" ${S.onlySimple ? 'checked' : ''}> Item discounts only</label>
        <div class="pr-search"><i class="fa fa-search"></i>
            <input class="pr-input" id="pr-q" placeholder="Search rule or item code…" value="${esc(S.q)}" autocomplete="off">
        </div>
    </div>
    <div class="pr-bulk" id="pr-bulk" hidden></div>
    <div class="pr-card" id="pr-list">
        <div class="pr-wrap" id="pr-table"><div class="pr-empty"><i class="fa fa-spinner fa-spin"></i><p>Loading rules…</p></div></div>
        <div class="pr-foot" id="pr-foot"></div>
    </div>
</div>`);

    let t = null;
    $b.on('input.prr', '#pr-q', function () {
        clearTimeout(t);
        const v = this.value;
        t = setTimeout(() => { S.q = v; renderView(); }, 150);
    });
    $b.on('click.prr', '#pr-status button', function () { setStatus($(this).attr('data-s')); });
    $b.on('click.prr', '#pr-alert-open, #pr-kpi-conf', () => setStatus('conflicts'));
    $b.on('change.prr', '#pr-simple', function () { S.onlySimple = this.checked; renderTabs(); renderView(); });
    $b.on('click.prr', '#pr-refresh', load);
    $b.on('click.prr', '#pr-new', () => openDrawer(null));
    $b.on('click.prr', '#pr-to-import', () => PRM.go && PRM.go('import'));
    $b.on('click.prr', '.pr-open', function (e) { e.preventDefault(); openDrawer($(this).attr('data-name')); });
    $b.on('dblclick.prr', '#pr-table tbody tr', function (e) {
        if ($(e.target).closest('input,button,a,label').length) return;
        openDrawer($(this).attr('data-name'));
    });

    // selection
    $b.on('change.prr', '.pr-sel', function () {
        const n = $(this).attr('data-name');
        this.checked ? S.sel.add(n) : S.sel.delete(n);
        $(this).closest('tr').toggleClass('is-sel', this.checked);
        renderBulk();
    });
    $b.on('change.prr', '#pr-sel-all', function () {
        const on = this.checked;
        filtered().forEach(r => on ? S.sel.add(r.name) : S.sel.delete(r.name));
        renderView();
    });
    $b.on('click.prr', '[data-bulk]', function () { bulk($(this).attr('data-bulk')); });

    // inline enable switch
    $b.on('change.prr', '.pr-switch input', function () {
        const n = $(this).attr('data-name');
        const disabled = this.checked ? 0 : 1;
        const el = this;
        frappe.call({
            method: API + 'set_disabled', args: { names: JSON.stringify([n]), disabled: disabled },
            callback: () => { frappe.show_alert({ message: `${n} ${disabled ? 'disabled' : 'enabled'}`, indicator: 'green' }, 3); load(); },
            error: () => { el.checked = !el.checked; }
        });
    });

    // conflict fixes
    $b.on('click.prr', '[data-fix]', function () { fixConflict($(this).attr('data-fix'), $(this).attr('data-rule'), +$(this).attr('data-pair')); });

    renderTabs();
    load();
}

function setStatus(key) {
    S.status = key;
    localStorage.setItem('isoft_prm_status', key);
    renderTabs();
    renderView();
}

function load() {
    if (S.loading) return;
    S.loading = true;
    frappe.call({
        method: API + 'get_rules', args: { company: company() || null },
        callback: function (r) {
            const m = r.message || {};
            S.rules = m.rules || [];
            S.conflicts = m.conflicts || [];
            S.byName = {};
            S.rules.forEach(x => { S.byName[x.name] = x; });
            S.conflictByRule = {};
            S.conflicts.forEach(c => c.rules.forEach(n => {
                const l = (S.conflictByRule[n] = S.conflictByRule[n] || []);
                c.shared.forEach(i => { if (l.indexOf(i) === -1) l.push(i); });
            }));
            S.sel.forEach(n => { if (!S.byName[n]) S.sel.delete(n); });
            renderKpis();
            renderAlert();
            renderTabs();
            renderView();
        },
        always: function () { S.loading = false; }
    });
}

function renderKpis() {
    const soon = frappe.datetime.add_days(today(), 30);
    let ending = 0;
    const items = new Set();
    S.rules.forEach(r => {
        if (r.status !== 'Active') return;
        if (r.apply_on === 'Item Code') r.targets.forEach(t => items.add(t));
        if (r.valid_upto && r.valid_upto <= soon) ending++;
    });
    $('#pr-kpis').html(`
        <span><b>${items.size}</b> item${items.size === 1 ? '' : 's'} on discount</span>
        <span class="${ending ? 'is-warn' : ''}" title="Active rules whose Valid Upto is within 30 days"><b>${ending}</b> ending within 30 days</span>
        <span class="${S.conflicts.length ? 'is-bad is-link' : 'is-ok'}" ${S.conflicts.length ? 'id="pr-kpi-conf" title="Review conflicts"' : ''}>${S.conflicts.length
            ? `<b>${S.conflicts.length}</b> conflict${S.conflicts.length === 1 ? '' : 's'}`
            : '<i class="fa fa-check"></i> no conflicts'}</span>`);
}

function renderAlert() {
    const n = S.conflicts.length;
    const $el = $('#pr-alert');
    if (!n || S.status === 'conflicts') { $el.attr('hidden', true).empty(); return; }
    const items = new Set();
    S.conflicts.forEach(c => c.shared.forEach(i => items.add(i)));
    $el.removeAttr('hidden').html(`
        <i class="fa fa-exclamation-triangle"></i>
        <span><b>${n} conflict${n === 1 ? '' : 's'}:</b> ${items.size} item${items.size === 1 ? ' is' : 's are'} in two rules with the same priority, so selling ${items.size === 1 ? 'it' : 'them'} fails with “Multiple Price Rules”.</span>
        <button class="pr-btn pr-btn-sm" id="pr-alert-open">Review conflicts <i class="fa fa-arrow-right"></i></button>`);
}

function countFor(key) {
    if (key === 'conflicts') return S.conflicts.length;
    return S.rules.filter(r => (!S.onlySimple || r.simple) && (key === 'all' || r.status.toLowerCase() === key)).length;
}

function renderTabs() {
    $('#pr-status').html(STATUS_TABS.map(t => {
        const n = countFor(t.key);
        const bad = t.key === 'conflicts' && n > 0;
        return `<button type="button" data-s="${t.key}" class="${S.status === t.key ? 'is-on' : ''} ${bad ? 'is-bad' : ''}">
            ${t.icon && bad ? `<i class="fa ${t.icon}"></i>` : ''}${t.label}<span class="pr-count">${S.rules.length || t.key === 'conflicts' ? n : ''}</span></button>`;
    }).join(''));
    renderAlert();
}

function filtered() {
    const q = S.q.trim().toLowerCase();
    return S.rules.filter(r => {
        if (S.status !== 'all' && r.status.toLowerCase() !== S.status) return false;
        if (S.onlySimple && !r.simple) return false;
        if (!q) return true;
        return (r.title || '').toLowerCase().includes(q) || r.name.toLowerCase().includes(q)
            || r.targets.some(t => String(t).toLowerCase().includes(q));
    });
}

function targetLabel(r) {
    const n = r.targets.length;
    const unit = { 'Item Code': ['item', 'items'], 'Item Group': ['item group', 'item groups'], 'Brand': ['brand', 'brands'] }[r.apply_on];
    if (!unit) return `<span class="pr-dim">${esc(r.apply_on || '-')}</span>`;
    return `${n} ${unit[n === 1 ? 0 : 1]}`;
}

function scopeCell(r) {
    if (r.everyone) return 'Everyone';
    const i = (r.scope || '').indexOf(': ');
    return i === -1 ? esc(r.scope)
        : `<span class="pr-scope-k">${esc(r.scope.slice(0, i))}</span> ${esc(r.scope.slice(i + 2))}`;
}

function renderView() {
    if (S.status === 'conflicts') renderConflicts(); else renderTable();
}

function renderTable() {
    const rows = filtered();
    const q = S.q.trim().toLowerCase();
    if (!S.rules.length) {
        $('#pr-table').html(`<div class="pr-empty"><i class="fa fa-tags"></i><h3>No pricing rules yet</h3>
            <p>Create one with <b>New rule</b>, or bring many at once with <b>Import</b>: one row per item, and every distinct discount becomes its own rule.</p></div>`);
        $('#pr-foot').text('');
        renderBulk();
        return;
    }
    if (!rows.length) {
        $('#pr-table').html(`<div class="pr-empty"><i class="fa fa-filter"></i><h3>Nothing matches</h3><p>Clear the search or pick another status.</p></div>`);
        $('#pr-foot').text(`0 of ${S.rules.length} rules`);
        renderBulk();
        return;
    }
    const allSel = rows.every(r => S.sel.has(r.name));
    $('#pr-table').html(`<table class="pr-table pr-rules">
        <thead><tr>
            <th class="pr-chk"><input type="checkbox" id="pr-sel-all" ${allSel ? 'checked' : ''}></th>
            <th>Rule</th><th class="num">Discount</th><th>Applies to</th><th>Customers</th><th>Price list</th>
            <th>Valid</th><th>Status</th><th class="pr-on" title="Enabled">On</th>
        </tr></thead>
        <tbody>${rows.map(r => {
            const hits = q && !(r.title || '').toLowerCase().includes(q) && !r.name.toLowerCase().includes(q)
                ? r.targets.filter(t => String(t).toLowerCase().includes(q)).slice(0, 3) : [];
            const conf = S.conflictByRule[r.name];
            return `<tr data-name="${esc(r.name)}" class="${conf ? 'is-conflict' : ''} ${S.sel.has(r.name) ? 'is-sel' : ''} ${r.disabled ? 'is-off' : ''}">
                <td class="pr-chk"><input type="checkbox" class="pr-sel" data-name="${esc(r.name)}" ${S.sel.has(r.name) ? 'checked' : ''}></td>
                <td class="pr-rule">
                    <a href="#" class="pr-open" data-name="${esc(r.name)}">${esc(r.title || r.name)}</a>
                    <span class="pr-id">${esc(r.name)}${r.simple ? '' : ' · <span title="Edited in the desk form">desk only</span>'}${r.priority ? ` · <span class="pr-prio">priority ${r.priority}</span>` : ''}</span>
                    ${conf ? `<a href="#" class="pr-hit is-bad" onclick="return false" data-s-conf title="Also in another rule with the same priority"><i class="fa fa-exclamation-triangle"></i> conflicts on ${conf.slice(0, 3).map(esc).join(', ')}${conf.length > 3 ? '…' : ''}</a>` : ''}
                    ${hits.length ? `<span class="pr-hit"><i class="fa fa-search"></i> ${hits.map(esc).join(', ')}</span>` : ''}
                </td>
                <td class="num"><span class="pr-disc">${esc(r.discount)}</span></td>
                <td class="pr-nw">${targetLabel(r)}</td>
                <td class="pr-nw pr-ell">${scopeCell(r)}</td>
                <td class="pr-nw">${r.price_list ? esc(r.price_list) : '<span class="pr-dim">Any</span>'}</td>
                <td class="pr-dates">${userDate(r.valid_from) || '—'} <span class="pr-dim">→</span> ${r.valid_upto ? userDate(r.valid_upto) : '<span class="pr-dim">no end</span>'}</td>
                <td><span class="pr-chip ${STATUS_CHIP[r.status] || 'pr-chip-mute'}">${esc(r.status)}</span></td>
                <td class="pr-on"><label class="pr-switch" title="${r.disabled ? 'Enable' : 'Disable'}"><input type="checkbox" data-name="${esc(r.name)}" ${r.disabled ? '' : 'checked'}><span></span></label></td>
            </tr>`;
        }).join('')}</tbody></table>`);
    $('#pr-table [data-s-conf]').on('click', () => setStatus('conflicts'));
    $('#pr-foot').html(`<span>${rows.length} of ${S.rules.length} rules</span><span class="pr-dim">Double-click a row or click its title to edit</span>`);
    renderBulk();
}

// ---------------------------------------------------------------------------
// Conflicts section
// ---------------------------------------------------------------------------

function renderConflicts() {
    $('#pr-bulk').attr('hidden', true);
    const q = S.q.trim().toLowerCase();
    const list = S.conflicts.map((c, i) => Object.assign({ i }, c)).filter(c => !q
        || c.shared.some(s => String(s).toLowerCase().includes(q))
        || c.rules.some(n => n.toLowerCase().includes(q) || ((S.byName[n] || {}).title || '').toLowerCase().includes(q)));

    if (!S.conflicts.length) {
        $('#pr-table').html(`<div class="pr-empty pr-empty-ok"><i class="fa fa-check-circle"></i><h3>No conflicts</h3>
            <p>No item is in two enabled rules with the same priority for the same customers, dates and price list, so every sale finds one rule.
            New rules are checked when they are saved.</p></div>`);
        $('#pr-foot').html('<span>0 conflicts</span>');
        return;
    }
    if (!list.length) {
        $('#pr-table').html(`<div class="pr-empty"><i class="fa fa-filter"></i><h3>No conflict matches the search</h3></div>`);
        $('#pr-foot').html(`<span>0 of ${S.conflicts.length} conflicts</span>`);
        return;
    }

    const side = (name, c) => {
        const r = S.byName[name] || { name: name, title: '', discount: '', scope: '', targets: [], priority: 0 };
        const n = c.shared.length;
        const total = r.targets.length;
        const left = total - n;
        const unit = (k) => ({ 'Item Code': ['item', 'items'], 'Item Group': ['item group', 'item groups'], 'Brand': ['brand', 'brands'] }[c.apply_on] || ['item', 'items'])[k === 1 ? 0 : 1];
        return `<div class="pr-cside">
            <div class="pr-cside-head">
                <a href="#" class="pr-open" data-name="${esc(name)}">${esc(r.title || name)}</a>
                <span class="pr-disc">${esc(r.discount)}</span>
            </div>
            <div class="pr-cside-meta">${esc(name)} · ${scopeCell(r)} · ${total} ${unit(total)}${r.priority ? ' · priority ' + r.priority : ''}
                ${r.price_list ? ' · ' + esc(r.price_list) : ''}</div>
            <div class="pr-cside-acts">
                ${left > 0 ? `<button class="pr-btn pr-btn-sm" data-fix="remove" data-rule="${esc(name)}" data-pair="${c.i}"
                    title="${esc(name)} keeps its other ${left} ${unit(left)}"><i class="fa fa-minus-circle"></i> Remove the ${n === 1 ? '' : n + ' '}shared ${unit(n)}</button>` : ''}
                <button class="pr-btn pr-btn-sm pr-btn-danger" data-fix="disable" data-rule="${esc(name)}" data-pair="${c.i}"
                    title="${left > 0 ? `All ${total} ${unit(total)} lose this discount` : 'It holds only the shared ' + unit(n)}"><i class="fa fa-ban"></i> Disable rule</button>
                <button class="pr-btn pr-btn-sm" data-fix="win" data-rule="${esc(name)}" data-pair="${c.i}"
                    title="Give ${esc(name)} a higher priority; the other rule stays as it is"><i class="fa fa-trophy"></i> Make this one win</button>
            </div>
            <div class="pr-cside-note">${left > 0
                ? `Removing keeps it for its other ${left} ${unit(left)}. Disabling stops all ${total}.`
                : `It holds only the shared ${unit(n)}, so disabling loses nothing else.`}</div>
        </div>`;
    };

    $('#pr-table').html(`<div class="pr-conflicts">
        <p class="pr-conf-intro">Each card is two enabled rules with the <b>same priority</b> that cover the same items for the same customers, dates and price list.
        ERPNext refuses every sale they both match (“Multiple Price Rules exists with same criteria”). Fix one side of each card.</p>
        ${list.map(c => `<div class="pr-ccard">
            <div class="pr-ccard-head">
                <i class="fa fa-exclamation-triangle"></i>
                <span><b>${c.shared.length} shared ${c.apply_on === 'Item Code' ? (c.shared.length === 1 ? 'item' : 'items') : esc(c.apply_on).toLowerCase()}:</b></span>
                <span class="pr-codes">${c.shared.slice(0, 10).map(s => `<code>${esc(s)}</code>`).join('')}${c.shared.length > 10 ? `<span class="pr-dim">+${c.shared.length - 10}</span>` : ''}</span>
            </div>
            <div class="pr-ccard-body">
                ${side(c.rules[0], c)}
                <div class="pr-cvs">vs</div>
                ${side(c.rules[1], c)}
            </div>
        </div>`).join('')}
    </div>`);
    $('#pr-foot').html(`<span>${list.length} of ${S.conflicts.length} conflict${S.conflicts.length === 1 ? '' : 's'}</span><span class="pr-dim">Fixing one side clears the card</span>`);
}

function fixConflict(action, rule, pairIndex) {
    const c = S.conflicts[pairIndex];
    if (!c) return;
    const r = S.byName[rule] || { targets: [], discount: '' };
    const total = r.targets.length;
    const n = c.shared.length;
    const done = (msg) => { frappe.show_alert({ message: msg, indicator: 'green' }, 5); load(); };

    if (action === 'remove') {
        frappe.call({
            method: RESOLVE_API, args: { rule: rule, action: 'remove', targets: JSON.stringify(c.shared) }, freeze: true,
            callback: () => done(`Removed ${n} item(s) from ${rule}`)
        });
    } else if (action === 'disable') {
        frappe.confirm(
            `Disable pricing rule <b>${esc(rule)}</b>${r.title ? ' · ' + esc(r.title) : ''}?<br>Its discount: ${esc(r.discount)}<br><br>`
            + (total > n
                ? `All ${total} items in it lose this discount, including the ${total - n} not in the conflict. To keep those, use <b>Remove</b> instead.`
                : 'It holds only the shared items, so nothing else is affected.')
            + '<br>You can enable it again later.',
            () => frappe.call({
                method: RESOLVE_API, args: { rule: rule, action: 'disable' }, freeze: true,
                callback: () => done(`${rule} disabled`)
            })
        );
    } else if (action === 'win') {
        frappe.confirm(
            `Give <b>${esc(rule)}</b> a higher priority so it wins wherever it meets the other rule?<br>The other rule stays as it is and keeps applying everywhere else.`,
            () => frappe.call({
                method: API + 'make_rule_win', args: { name: rule }, freeze: true,
                callback: (res) => done(`${rule} now has priority ${(res.message || {}).priority}`)
            })
        );
    }
}

function renderBulk() {
    const n = S.sel.size;
    const $b = $('#pr-bulk');
    if (!n) { $b.attr('hidden', true).empty(); return; }
    $b.removeAttr('hidden').html(`
        <b>${n} selected</b>
        <button class="pr-btn" data-bulk="enable"><i class="fa fa-toggle-on"></i> Enable</button>
        <button class="pr-btn" data-bulk="disable"><i class="fa fa-toggle-off"></i> Disable</button>
        <button class="pr-btn" data-bulk="export"><i class="fa fa-file-excel-o"></i> Export to Excel</button>
        <button class="pr-btn pr-btn-danger" data-bulk="delete"><i class="fa fa-trash"></i> Delete</button>
        <span class="pr-spacer"></span>
        <button class="pr-link" data-bulk="clear">Clear selection</button>`);
}

function bulk(action) {
    const names = Array.from(S.sel);
    if (action === 'clear') { S.sel.clear(); renderView(); return; }
    if (!names.length) return;
    if (action === 'export') {
        download('export_rules', { names: JSON.stringify(names) });
        return;
    }
    if (action === 'enable' || action === 'disable') {
        frappe.call({
            method: API + 'set_disabled', args: { names: JSON.stringify(names), disabled: action === 'disable' ? 1 : 0 },
            freeze: true,
            callback: () => { frappe.show_alert({ message: `${names.length} rule(s) ${action}d`, indicator: 'green' }, 4); load(); }
        });
        return;
    }
    if (action === 'delete') {
        frappe.confirm(`Delete ${names.length} pricing rule(s)? This cannot be undone. Disabling keeps the history instead.`, () => {
            frappe.call({
                method: API + 'delete_rules', args: { names: JSON.stringify(names) }, freeze: true,
                callback: () => { S.sel.clear(); frappe.show_alert({ message: `${names.length} rule(s) deleted`, indicator: 'green' }, 4); load(); }
            });
        });
    }
}

// ---------------------------------------------------------------------------
// Rule drawer (create / edit)
// ---------------------------------------------------------------------------

let D = null;   // { model, dirty, $el, itemCtl, filter }

function openDrawer(name) {
    if (D && D.dirty) {
        frappe.confirm('Discard the changes to this rule?', () => { D.dirty = false; openDrawer(name); });
        return;
    }
    closeDrawer();
    const $el = $(`<div class="pr-drawer-back"></div><aside class="pr-drawer" role="dialog" aria-label="Pricing rule">
        <div class="pr-dr-head"><div class="pr-dr-title">${name ? esc(name) : 'New pricing rule'}</div>
            <span class="pr-spacer"></span><button class="pr-x" id="pr-dr-close" title="Close (Esc)">×</button></div>
        <div class="pr-dr-body"><div class="pr-empty"><i class="fa fa-spinner fa-spin"></i><p>Loading…</p></div></div>
        <div class="pr-dr-foot"></div></aside>`);
    $('.pr-root').append($el);
    D = { model: null, dirty: false, $el: $el, filter: '' };
    requestAnimationFrame(() => $el.addClass('is-open'));

    $el.on('click', '#pr-dr-close, .pr-dr-cancel', () => tryClose());
    $el.filter('.pr-drawer-back').on('click', () => tryClose());
    $(document).off('keydown.prdoc').on('keydown.prdoc', function (e) {
        if (e.key === 'Escape' && D && D.$el.is(':visible') && !$('.modal.show').length) tryClose();
    });

    if (!name) {
        fillDrawer({
            name: null, title: '', discount_percentage: '', valid_from: today(), valid_upto: '', price_list: '',
            disabled: 0, items: [], simple: 1, can_write: 1, can_delete: 0, status: 'New', scope: 'Everyone', has_max: 1
        });
        return;
    }
    frappe.call({
        method: API + 'get_rule', args: { name: name },
        callback: r => { if (D && D.$el === $el) fillDrawer(r.message); },
        error: () => closeDrawer()
    });
}

function tryClose() {
    if (!D) return;
    if (D.dirty) {
        frappe.confirm('Discard the changes to this rule?', () => { D.dirty = false; closeDrawer(); });
        return;
    }
    closeDrawer();
}

function closeDrawer() {
    $(document).off('keydown.prdoc');
    if (!D) return;
    const $el = D.$el;
    D = null;
    $el.removeClass('is-open');
    setTimeout(() => $el.remove(), 180);
}

function markDirty() { if (D) { D.dirty = true; D.$el.find('.pr-dr-save').prop('disabled', false); } }

function fillDrawer(m) {
    D.model = m;
    const $el = D.$el;
    const editable = m.simple && m.can_write;
    $el.find('.pr-dr-title').html(`${esc(m.name ? (m.title || m.name) : 'New pricing rule')}
        ${m.name ? `<span class="pr-id">${esc(m.name)}</span>` : ''}
        <span class="pr-chip ${STATUS_CHIP[m.status] || 'pr-chip-brand'}">${esc(m.status)}</span>`);

    if (!m.simple) {
        $el.find('.pr-dr-body').html(`
            <div class="pr-note is-warn"><i class="fa fa-info-circle"></i>
                This rule is not a plain item discount (${esc(m.apply_on)} · ${esc(m.discount)} · ${esc(m.scope)}). This page shows it but leaves editing to the desk form, so none of its other settings are lost.</div>
            <div class="pr-grid2">
                <div><span class="k">Discount</span><b>${esc(m.discount)}</b></div>
                <div><span class="k">Customers</span><b>${esc(m.scope)}</b></div>
                <div><span class="k">Valid</span><b>${userDate(m.valid_from) || '—'} → ${m.valid_upto ? userDate(m.valid_upto) : 'no end'}</b></div>
                <div><span class="k">Price list</span><b>${esc(m.price_list || 'Any')}</b></div>
            </div>
            ${m.items.length ? itemsReadOnly(m.items) : ''}`);
        $el.find('.pr-dr-foot').html(`<span class="pr-spacer"></span>
            <button class="pr-btn pr-dr-cancel">Close</button>
            <a class="pr-btn pr-btn-primary" href="/app/pricing-rule/${encodeURIComponent(m.name)}" target="_blank" rel="noopener"><i class="fa fa-external-link"></i> Open in desk</a>`);
        bindDeskLink($el);
        return;
    }

    $el.find('.pr-dr-body').html(`
        <div class="pr-form">
            <div class="pr-field pr-span2"><label>Title</label>
                <input class="pr-input" data-f="title" value="${esc(m.title)}" placeholder="e.g. Black Friday TVs" maxlength="140" ${editable ? '' : 'disabled'}></div>
            <div class="pr-field"><label>Discount %</label>
                <input class="pr-input pr-num" data-f="discount_percentage" type="number" min="0.01" max="100" step="0.01" value="${esc(m.discount_percentage)}" placeholder="10" ${editable ? '' : 'disabled'}></div>
            <div class="pr-field"><label>Price list</label>
                <select class="pr-input" data-f="price_list" ${editable ? '' : 'disabled'}><option value="">Any price list</option></select></div>
            <div class="pr-field"><label>Valid from</label>
                <input class="pr-input" data-f="valid_from" type="date" value="${esc(m.valid_from || '')}" ${editable ? '' : 'disabled'}></div>
            <div class="pr-field"><label>Valid upto <span class="pr-dim">(blank = no end)</span></label>
                <input class="pr-input" data-f="valid_upto" type="date" value="${esc(m.valid_upto || '')}" ${editable ? '' : 'disabled'}></div>
            <label class="pr-check pr-span2"><input type="checkbox" data-f="enabled" ${m.disabled ? '' : 'checked'} ${editable ? '' : 'disabled'}> Enabled</label>
        </div>
        <div class="pr-fixed-row"><i class="fa fa-lock"></i> Selling · Discount percentage · Apply on Item Code · All customer groups · ${esc(m.company || company())}</div>

        <div class="pr-items-head">
            <b>Items <span class="pr-dim" id="pr-it-count">(${m.items.length})</span></b>
            <span class="pr-spacer"></span>
            ${m.items.length > 12 ? '<input class="pr-input pr-it-filter" id="pr-it-filter" placeholder="Filter items…">' : ''}
        </div>
        ${editable ? `<div class="pr-add">
            <div class="pr-add-ctl" id="pr-add-ctl"></div>
            <button class="pr-link" id="pr-paste"><i class="fa fa-paste"></i> Paste a list of codes</button>
        </div>` : ''}
        <div class="pr-items" id="pr-items"></div>
        <div id="pr-overlap"></div>`);

    priceListOptions(m.price_list).then(html => { $el.find('[data-f="price_list"]').html(html); });

    $el.find('.pr-dr-foot').html(`
        ${m.name && m.can_delete ? '<button class="pr-btn pr-btn-danger" id="pr-dr-delete"><i class="fa fa-trash"></i></button>' : ''}
        ${m.name ? `<a class="pr-link" href="/app/pricing-rule/${encodeURIComponent(m.name)}" target="_blank" rel="noopener">Open in desk</a>` : ''}
        <span class="pr-spacer"></span>
        <button class="pr-btn pr-dr-cancel">Cancel</button>
        ${editable ? `<button class="pr-btn pr-btn-primary pr-dr-save" ${m.name ? 'disabled' : ''}>${m.name ? 'Save' : 'Create rule'}</button>` : ''}`);
    bindDeskLink($el);

    $el.on('input change', '[data-f]', function () {
        const f = $(this).attr('data-f');
        if (f === 'enabled') m.disabled = this.checked ? 0 : 1;
        else m[f] = $(this).val();
        if (f === 'discount_percentage') renderItems();
        markDirty();
    });
    $el.on('input', '#pr-it-filter', function () { D.filter = this.value.toLowerCase(); renderItems(); });
    $el.on('change', '.pr-it-uom', function () { m.items[+$(this).attr('data-i')].uom = $(this).val(); markDirty(); });
    $el.on('input', '.pr-it-max', function () { m.items[+$(this).attr('data-i')].max = parseInt(this.value, 10) || 0; markDirty(); });
    $el.on('click', '.pr-it-del', function () {
        m.items.splice(+$(this).attr('data-i'), 1);
        renderItems();
        markDirty();
    });
    $el.on('click', '#pr-paste', pasteDialog);
    $el.on('click', '.pr-dr-save', () => save(''));
    $el.on('click', '#pr-dr-delete', function () {
        frappe.confirm(`Delete ${esc(m.name)}? Disabling it keeps the history instead.`, () => {
            frappe.call({
                method: API + 'delete_rules', args: { names: JSON.stringify([m.name]) }, freeze: true,
                callback: () => { D.dirty = false; closeDrawer(); frappe.show_alert({ message: `${m.name} deleted`, indicator: 'green' }, 4); load(); }
            });
        });
    });

    if (editable) makeItemPicker();
    renderItems();
    if (!m.name) setTimeout(() => $el.find('[data-f="title"]').trigger('focus'), 200);
}

// Desk links inside a desk page are routed into the same tab by the v13
// router; send them to a new tab on purpose.
function bindDeskLink($el) {
    $el.on('click', 'a[target="_blank"]', function (e) {
        e.preventDefault();
        e.stopPropagation();
        window.open(this.href, '_blank', 'noopener');
    });
}

function itemsReadOnly(items) {
    return `<div class="pr-items-head"><b>Items <span class="pr-dim">(${items.length})</span></b></div>
        <div class="pr-items"><table class="pr-table pr-it-table"><thead><tr><th>Item</th><th>UOM</th><th class="num">Max</th></tr></thead>
        <tbody>${items.map(it => `<tr><td><b>${esc(it.item_code)}</b><span class="pr-it-name">${esc(it.item_name)}</span></td>
            <td>${esc(it.uom || 'Any')}</td><td class="num">${it.max || ''}</td></tr>`).join('')}</tbody></table></div>`;
}

function renderItems() {
    if (!D || !D.model) return;
    const m = D.model;
    const editable = m.simple && m.can_write;
    const disc = parseFloat(m.discount_percentage) || 0;
    const f = D.filter;
    D.$el.find('#pr-it-count').text(`(${m.items.length})`);
    const rows = m.items.map((it, i) => ({ it, i }))
        .filter(x => !f || x.it.item_code.toLowerCase().includes(f) || (x.it.item_name || '').toLowerCase().includes(f));
    if (!m.items.length) {
        D.$el.find('#pr-items').html(`<div class="pr-empty pr-empty-sm"><p>No items yet. Search one above, or paste a list of codes.</p></div>`);
        return;
    }
    D.$el.find('#pr-items').html(`<table class="pr-table pr-it-table">
        <thead><tr><th>Item</th><th>UOM</th><th class="num" title="Stored in the rule's Max column">Max</th>${editable ? '<th></th>' : ''}</tr></thead>
        <tbody>${rows.map(({ it, i }) => {
            const tooMuch = it.max_discount && disc > it.max_discount;
            const flags = [
                it.disabled ? '<span class="pr-chip pr-chip-mute">disabled item</span>' : '',
                tooMuch ? `<span class="pr-chip pr-chip-bad" title="Item Max Discount">allows ${pct(it.max_discount)} at most</span>` : ''
            ].join(' ');
            return `<tr class="${tooMuch ? 'is-conflict' : ''}">
            <td><b>${esc(it.item_code)}</b> ${flags}<span class="pr-it-name">${esc(it.item_name || '')}</span></td>
            <td>${editable ? `<select class="pr-input pr-it-uom" data-i="${i}">
                    <option value="">Any unit</option>
                    ${(it.uoms || []).map(u => `<option value="${esc(u)}" ${u === it.uom ? 'selected' : ''}>${esc(u)}</option>`).join('')}
                    ${it.uom && (it.uoms || []).indexOf(it.uom) === -1 ? `<option value="${esc(it.uom)}" selected>${esc(it.uom)}</option>` : ''}
                </select>` : esc(it.uom || 'Any')}</td>
            <td class="num">${editable ? `<input class="pr-input pr-it-max" data-i="${i}" type="number" min="0" step="1" value="${it.max || ''}" placeholder="0">` : (it.max || '')}</td>
            ${editable ? `<td><button class="pr-x pr-it-del" data-i="${i}" title="Remove">×</button></td>` : ''}
        </tr>`;
        }).join('')}</tbody></table>`);
}

function makeItemPicker() {
    const $wrap = D.$el.find('#pr-add-ctl');
    const ctl = frappe.ui.form.make_control({
        parent: $wrap,
        df: {
            fieldtype: 'Link', options: 'Item', fieldname: 'pr_add_item', placeholder: 'Add an item: type a code or name…',
            get_query: () => ({ filters: { disabled: 0 } }),
            onchange: function () {
                const v = ctl.get_value();
                if (!v) return;
                addItems([v]).then(() => { ctl.set_value(''); });
            }
        },
        render_input: true
    });
    $wrap.find('.control-label').remove();
    $wrap.find('.form-group').css('margin', 0);
}

function addItems(codes) {
    const m = D.model;
    const have = new Set(m.items.map(i => i.item_code.toLowerCase()));
    const want = codes.map(c => String(c).trim()).filter(c => c && !have.has(c.toLowerCase()));
    if (!want.length) {
        frappe.show_alert({ message: 'Already in this rule', indicator: 'orange' }, 3);
        return Promise.resolve();
    }
    return call(API + 'get_item_info', { item_codes: JSON.stringify(want) }).then(msg => {
        if (!D || D.model !== m) return;
        const res = msg || {};
        (res.items || []).forEach(i => {
            if (have.has(i.item_code.toLowerCase())) return;
            have.add(i.item_code.toLowerCase());
            m.items.push({ item_code: i.item_code, item_name: i.item_name, uom: '', uoms: i.uoms, max: 0,
                max_discount: i.max_discount, disabled: i.disabled });
        });
        if ((res.items || []).length) markDirty();
        renderItems();
        if ((res.missing || []).length) {
            frappe.msgprint({ title: 'Not found', indicator: 'orange',
                message: `These codes are not items: ${res.missing.slice(0, 50).map(esc).join(', ')}${res.missing.length > 50 ? '…' : ''}` });
        }
    });
}

function pasteDialog() {
    const d = new frappe.ui.Dialog({
        title: 'Add items by code',
        fields: [{ fieldname: 'codes', fieldtype: 'Small Text', label: 'Item codes',
            description: 'One per line, or separated by commas. Copy a column from Excel and paste it here.' }],
        primary_action_label: 'Add',
        primary_action: v => {
            const codes = (v.codes || '').split(/[\n,;\t]+/).map(s => s.trim()).filter(Boolean);
            d.hide();
            if (codes.length) addItems(codes);
        }
    });
    d.show();
}

function save(resolve) {
    const m = D.model;
    const payload = {
        name: m.name, company: m.company || company(), title: m.title, discount_percentage: m.discount_percentage,
        valid_from: m.valid_from, valid_upto: m.valid_upto, price_list: m.price_list, disabled: m.disabled,
        items: m.items.map(i => ({ item_code: i.item_code, uom: i.uom || '', max: i.max || 0 })),
        resolve: resolve || ''
    };
    frappe.call({
        method: API + 'save_rule', args: { payload: JSON.stringify(payload) }, freeze: true, freeze_message: 'Saving…',
        callback: r => {
            const res = r.message || {};
            if (!res.saved) { showOverlaps(res.overlaps || [], res.suggested_priority); return; }
            const moved = (res.moved || []).map(x => `${x.rule} (${x.action === 'disabled' ? 'disabled, it had nothing else' : 'item removed'})`);
            frappe.show_alert({ message: `${res.name} saved${res.priority ? ' with priority ' + res.priority : ''}${moved.length ? ' · took items from ' + moved.join(', ') : ''}`, indicator: 'green' }, 6);
            D.dirty = false;
            closeDrawer();
            load();
        }
    });
}

// What an overlap means, in one chip.
function kindChip(o) {
    return o.kind === 'conflict'
        ? '<span class="pr-chip pr-chip-bad" title="Same priority: ERPNext refuses every line both rules match">blocks the sale</span>'
        : `<span class="pr-chip pr-chip-warn" title="${o.priority ? 'It has a higher priority' : 'It names the price list, this rule does not'}">wins over this rule</span>`;
}

function showOverlaps(list, suggested) {
    const blocking = list.filter(o => o.kind === 'conflict');
    const movable = list.filter(o => !o.promotional_scheme);
    const $o = D.$el.find('#pr-overlap');
    $o.html(`<div class="pr-note is-bad">
        <b><i class="fa fa-exclamation-triangle"></i> ${list.length === 1 ? '1 item is' : list.length + ' items are'} already in another active rule.</b>
        ${blocking.length ? `<p><b>Blocks the sale</b>: same priority, so ERPNext refuses every line both rules match (“Multiple Price Rules exists with same criteria”). This cannot be saved as it is.</p>` : ''}
        ${list.length > blocking.length ? `<p><b>Wins over this rule</b>: the other rule has a higher priority, or names the price list and this one does not, so this discount would never apply there.</p>` : ''}
        <table class="pr-table pr-it-table"><thead><tr><th>Item</th><th>Other rule</th><th>Its discount</th><th>Customers</th><th></th></tr></thead>
        <tbody>${list.map(o => `<tr><td><b>${esc(o.item_code)}</b></td><td>${esc(o.rule)} <span class="pr-dim">${esc(o.title || '')}</span></td>
            <td>${esc(o.discount)}</td><td>${esc(o.scope)}</td><td>${kindChip(o)}</td></tr>`).join('')}</tbody></table>
        <div class="pr-note-actions">
            ${movable.length ? `<button class="pr-btn pr-btn-primary" id="pr-ov-move">Move ${list.length > 1 ? 'them' : 'it'} to this rule and save</button>` : ''}
            ${suggested ? `<button class="pr-btn" id="pr-ov-prio">Give this rule priority ${suggested} and save</button>` : ''}
            ${!blocking.length ? `<button class="pr-btn" id="pr-ov-keep">Save anyway</button>` : ''}
            <button class="pr-link" id="pr-ov-cancel">Back to editing</button>
        </div>
        <p class="pr-dim">Moving removes the item from the other rule (a rule left with no items is disabled, not deleted). A priority leaves the other rules untouched and makes this one win wherever both apply.</p>
    </div>`);
    $o[0].scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    $o.off('click').on('click', '#pr-ov-move', () => save('move'))
        .on('click', '#pr-ov-prio', () => save('priority'))
        .on('click', '#pr-ov-keep', () => save('keep'))
        .on('click', '#pr-ov-cancel', () => $o.empty());
}

// ---------------------------------------------------------------------------
// Import screen
// ---------------------------------------------------------------------------

const I = { fileUrl: null, fileName: '', preview: null, resolve: 'move', prefix: '', vf: '', vu: '', pl: '', busy: false };

function screenImport() {
    const $b = body();
    $b.off('.pri');
    if (!I.vf) I.vf = today();
    if (!I.prefix) I.prefix = 'Import ' + userDate(today());

    $b.html(`
<div class="pr-root pr-scroll">
  <div class="pr-import">
    <div class="pr-head">
        <div>
            <div class="pr-title"><i class="fa fa-upload"></i> Import pricing rules from Excel</div>
            <div class="pr-sub">One row per item. Every distinct discount in the file becomes its own pricing rule.</div>
        </div>
    </div>

    <section class="pr-step">
        <div class="pr-step-n">1</div>
        <div class="pr-step-body">
            <h4>Fill the template</h4>
            <div class="pr-cols">
                <div><b>Item Code</b><span>required</span></div>
                <div><b>UOM</b><span>optional · blank = every unit</span></div>
                <div><b>Max</b><span>optional · whole number</span></div>
                <div><b>Discount %</b><span>required · 10 = 10%</span></div>
            </div>
            <div class="pr-example">
                <table class="pr-table pr-it-table"><thead><tr><th>Item Code</th><th>UOM</th><th class="num">Max</th><th class="num">Discount %</th><th></th></tr></thead>
                <tbody>
                    <tr><td>TV-55-4K</td><td></td><td class="num"></td><td class="num">10</td><td rowspan="2" class="pr-arrow">→ rule “… - 10%”, 2 items</td></tr>
                    <tr><td>TV-65-4K</td><td>PCS</td><td class="num">5</td><td class="num">10</td></tr>
                    <tr><td>SOUNDBAR-X</td><td></td><td class="num"></td><td class="num">15</td><td class="pr-arrow">→ rule “… - 15%”, 1 item</td></tr>
                </tbody></table>
            </div>
            <button class="pr-btn" id="pri-template"><i class="fa fa-download"></i> Download template (.xlsx)</button>
            <span class="pr-dim" style="margin-left:.5rem;">To change existing discounts: select rules on the Rules screen → Export, edit, import back.</span>
        </div>
    </section>

    <section class="pr-step">
        <div class="pr-step-n">2</div>
        <div class="pr-step-body">
            <h4>Settings for the new rules</h4>
            <div class="pr-form pr-form-4">
                <div class="pr-field"><label>Rule title</label><input class="pr-input" id="pri-prefix" value="${esc(I.prefix)}" maxlength="120"></div>
                <div class="pr-field"><label>Valid from</label><input class="pr-input" id="pri-vf" type="date" value="${esc(I.vf)}"></div>
                <div class="pr-field"><label>Valid upto <span class="pr-dim">(blank = no end)</span></label><input class="pr-input" id="pri-vu" type="date" value="${esc(I.vu)}"></div>
                <div class="pr-field"><label>Price list</label><select class="pr-input" id="pri-pl"><option value="">Any price list</option></select></div>
            </div>
            <div class="pr-fixed-row"><i class="fa fa-lock"></i> Fixed: Selling · Discount percentage (not margin) · Apply on Item Code · All customer groups · Company <b>${esc(company() || '—')}</b></div>
        </div>
    </section>

    <section class="pr-step">
        <div class="pr-step-n">3</div>
        <div class="pr-step-body">
            <h4>Upload and check</h4>
            <label class="pr-drop" id="pri-drop">
                <input type="file" id="pri-file" accept=".xlsx,.csv" hidden>
                <i class="fa fa-cloud-upload"></i>
                <span id="pri-drop-text">${I.fileName ? `<b>${esc(I.fileName)}</b> · click or drop to replace` : 'Drop the .xlsx here, or click to choose'}</span>
            </label>
            <div id="pri-preview"></div>
        </div>
    </section>
  </div>
  <div class="pr-actionbar" id="pri-bar" hidden></div>
</div>`);

    priceListOptions(I.pl).then(html => $('#pri-pl').html(html));

    $b.on('click.pri', '#pri-template', () => download('download_template'));
    let t = null;
    const rerun = () => { clearTimeout(t); t = setTimeout(() => { if (I.fileUrl) runPreview(); else renderBar(); }, 350); };
    $b.on('input.pri', '#pri-prefix', function () { I.prefix = this.value; renderGroupsTitles(); });
    $b.on('change.pri', '#pri-vf', function () { I.vf = this.value || today(); rerun(); });
    $b.on('change.pri', '#pri-vu', function () { I.vu = this.value; rerun(); });
    $b.on('change.pri', '#pri-pl', function () { I.pl = this.value; rerun(); });
    $b.on('change.pri', '#pri-file', function () { if (this.files && this.files[0]) upload(this.files[0]); this.value = ''; });
    $b.on('dragover.pri', '#pri-drop', function (e) { e.preventDefault(); $(this).addClass('is-over'); });
    $b.on('dragleave.pri drop.pri', '#pri-drop', function () { $(this).removeClass('is-over'); });
    $b.on('drop.pri', '#pri-drop', function (e) {
        e.preventDefault();
        const f = e.originalEvent.dataTransfer && e.originalEvent.dataTransfer.files[0];
        if (f) upload(f);
    });
    $b.on('click.pri', '[data-resolve]', function () {
        I.resolve = $(this).attr('data-resolve');
        renderPreview();
    });
    $b.on('click.pri', '.pr-gcard-head', function () { $(this).closest('.pr-gcard').toggleClass('is-open'); });
    $b.on('click.pri', '#pri-create', create);
    $b.on('click.pri', '#pri-to-rules', () => PRM.go && PRM.go('rules'));
    $b.on('click.pri', '#pri-again', () => { I.fileUrl = null; I.fileName = ''; I.preview = null; screenImport(); });

    if (I.preview) renderPreview(); else renderBar();
}

function upload(file) {
    if (!/\.(xlsx|csv)$/i.test(file.name)) {
        frappe.msgprint('Upload an .xlsx or .csv file. Old .xls files: open in Excel and save as .xlsx.');
        return;
    }
    $('#pri-drop-text').html(`<i class="fa fa-spinner fa-spin"></i> Uploading ${esc(file.name)}…`);
    const fd = new FormData();
    fd.append('file', file, file.name);
    fd.append('is_private', 1);
    fd.append('folder', 'Home');
    fetch('/api/method/upload_file', {
        method: 'POST', body: fd, credentials: 'same-origin',
        headers: { 'X-Frappe-CSRF-Token': frappe.csrf_token, 'Accept': 'application/json' }
    }).then(r => r.json().then(j => ({ ok: r.ok, j }))).then(({ ok, j }) => {
        const url = j && j.message && j.message.file_url;
        if (!ok || !url) {
            let msg = 'Upload failed.';
            try { msg = JSON.parse(JSON.parse(j._server_messages)[0]).message || msg; } catch (e) { /* keep default */ }
            throw new Error(msg);
        }
        I.fileUrl = url;
        I.fileName = file.name;
        $('#pri-drop-text').html(`<b>${esc(file.name)}</b> · click or drop to replace`);
        runPreview();
    }).catch(err => {
        $('#pri-drop-text').text('Drop the .xlsx here, or click to choose');
        frappe.msgprint({ title: 'Upload failed', message: esc(err.message || err), indicator: 'red' });
    });
}

function runPreview() {
    $('#pri-preview').html('<div class="pr-empty pr-empty-sm"><i class="fa fa-spinner fa-spin"></i><p>Reading the file…</p></div>');
    I.preview = null;
    renderBar();
    frappe.call({
        method: API + 'preview_import',
        args: { file_url: I.fileUrl, company: company(), valid_from: I.vf, valid_upto: I.vu || null, price_list: I.pl || null },
        callback: r => { I.preview = r.message; renderPreview(); },
        error: () => { $('#pri-preview').empty(); }
    });
}

function groupTitle(d) {
    const p = (I.prefix || '').trim() || ('Import ' + userDate(today()));
    return `${p} - ${pct(d)}`;
}
function renderGroupsTitles() {
    $('.pr-gcard').each(function () { $(this).find('.pr-gtitle').text(groupTitle($(this).attr('data-d'))); });
}

function renderPreview() {
    const p = I.preview;
    if (!p) return;
    const ready = p.groups.reduce((a, g) => a + g.items.length, 0);
    const blocking = p.overlaps.filter(o => o.kind === 'conflict');
    const byItem = {};
    p.overlaps.forEach(o => { (byItem[o.item_code] = byItem[o.item_code] || []).push(o); });

    $('#pri-preview').html(`
        <div class="pr-stats">
            <div class="pr-tile"><div class="k">Rows read</div><div class="v">${p.rows}</div></div>
            <div class="pr-tile is-ok"><div class="k">Ready</div><div class="v">${ready}</div></div>
            <div class="pr-tile ${p.errors.length ? 'is-bad' : ''}"><div class="k">Rows with errors</div><div class="v">${p.errors.length}</div></div>
            <div class="pr-tile"><div class="k">Rules to create</div><div class="v">${p.groups.length}</div></div>
            <div class="pr-tile ${p.overlaps.length ? 'is-warn' : ''}"><div class="k">Already in a rule</div><div class="v">${Object.keys(byItem).length}</div></div>
        </div>

        ${p.errors.length ? `<div class="pr-block">
            <h5 class="is-bad"><i class="fa fa-times-circle"></i> ${p.errors.length} row${p.errors.length > 1 ? 's' : ''} will be skipped</h5>
            <div class="pr-card pr-card-sm"><div class="pr-wrap"><table class="pr-table pr-it-table">
                <thead><tr><th class="num">Row</th><th>Item Code</th><th>Problem</th></tr></thead>
                <tbody>${p.errors.map(e => `<tr><td class="num">${e.row}</td><td>${esc(e.item_code)}</td><td>${esc(e.error)}</td></tr>`).join('')}</tbody>
            </table></div></div>
            <p class="pr-dim">Fix them in the file and upload it again, or create the rules without them.</p></div>` : ''}

        ${p.warnings.length ? `<div class="pr-block"><h5 class="is-warn"><i class="fa fa-info-circle"></i> Worth a look</h5>
            <ul class="pr-ul">${p.warnings.slice(0, 30).map(w => `<li>Row ${w.row} · <b>${esc(w.item_code)}</b>: ${esc(w.warning)}</li>`).join('')}</ul></div>` : ''}

        ${p.overlaps.length ? `<div class="pr-block">
            <h5 class="is-warn"><i class="fa fa-exclamation-triangle"></i> ${Object.keys(byItem).length} item(s) already have an active rule</h5>
            <p class="pr-dim">${blocking.length ? '<b>Blocks the sale</b>: same priority, ERPNext would refuse the line with “Multiple Price Rules”, and the rule cannot be saved. ' : ''}${p.overlaps.length > blocking.length ? '<b>Wins over the new rule</b>: the old rule has a higher priority or names the price list, so the new discount would not apply there. ' : ''}Choose what happens:</p>
            <div class="pr-seg pr-seg-lg">
                <button type="button" data-resolve="move" class="${I.resolve === 'move' ? 'is-on' : ''}"><i class="fa fa-exchange"></i> Move them to the new rules</button>
                <button type="button" data-resolve="priority" class="${I.resolve === 'priority' ? 'is-on' : ''}"><i class="fa fa-sort-amount-desc"></i> Give the new rules a higher priority</button>
                <button type="button" data-resolve="skip" class="${I.resolve === 'skip' ? 'is-on' : ''}"><i class="fa fa-ban"></i> Leave them out of this import</button>
            </div>
            <p class="pr-dim">${{
                move: 'The items are removed from their old rules; an old rule left with no items is disabled, not deleted.',
                priority: 'The old rules stay as they are; each new rule that meets one gets the lowest priority that wins over it (shown on the rule below).',
                skip: 'Those items are not imported; their old discount stays.'
            }[I.resolve]}</p>
            <div class="pr-card pr-card-sm"><div class="pr-wrap"><table class="pr-table pr-it-table">
                <thead><tr><th>Item</th><th>Existing rule</th><th>Its discount</th><th>Customers</th><th></th></tr></thead>
                <tbody>${p.overlaps.map(o => `<tr><td><b>${esc(o.item_code)}</b></td><td>${esc(o.rule)} <span class="pr-dim">${esc(o.title || '')}</span></td>
                    <td>${esc(o.discount)}</td><td>${esc(o.scope)}</td><td>${kindChip(o)}</td></tr>`).join('')}</tbody>
            </table></div></div></div>` : ''}

        ${p.groups.length ? `<div class="pr-block">
            <h5><i class="fa fa-clone"></i> Rules that will be created</h5>
            <div class="pr-gcards">${p.groups.map(g => `
                <div class="pr-gcard" data-d="${g.discount}">
                    <div class="pr-gcard-head">
                        <span class="pr-gpct">${pct(g.discount)}</span>
                        <span class="pr-gtitle">${esc(groupTitle(g.discount))}</span>
                        <span class="pr-spacer"></span>
                        <span class="pr-dim">${g.items.length} item${g.items.length > 1 ? 's' : ''}</span>
                        ${g.items.some(i => byItem[i.item_code]) ? '<span class="pr-chip pr-chip-warn">has items in other rules</span>' : ''}
                        ${I.resolve === 'priority' && g.priority ? `<span class="pr-chip pr-chip-brand">priority ${g.priority}</span>` : ''}
                        ${I.resolve === 'priority' && g.priority === 0 ? '<span class="pr-chip pr-chip-bad" title="Even priority 20 does not win; move or leave out instead">no priority wins</span>' : ''}
                        <i class="fa fa-chevron-down pr-caret"></i>
                    </div>
                    <div class="pr-gcard-body"><table class="pr-table pr-it-table">
                        <thead><tr><th class="num">Row</th><th>Item</th><th>UOM</th><th class="num">Max</th><th></th></tr></thead>
                        <tbody>${g.items.map(i => `<tr><td class="num">${i.row}</td><td><b>${esc(i.item_code)}</b><span class="pr-it-name">${esc(i.item_name || '')}</span></td>
                            <td>${esc(i.uom || 'Any')}</td><td class="num">${i.max || ''}</td>
                            <td>${byItem[i.item_code] ? byItem[i.item_code].map(o => `<span class="pr-chip pr-chip-warn" title="${esc(o.title)}">in ${esc(o.rule)} · ${esc(o.discount)}</span>`).join(' ') : ''}</td></tr>`).join('')}</tbody>
                    </table></div>
                </div>`).join('')}</div></div>` : `<div class="pr-empty pr-empty-sm"><i class="fa fa-times-circle"></i><p>No usable rows in this file.</p></div>`}
    `);
    renderBar();
}

function renderBar() {
    const $bar = $('#pri-bar');
    const p = I.preview;
    if (!p || !p.groups.length) { $bar.attr('hidden', true).empty(); return; }
    const skip = I.resolve === 'skip' ? new Set(p.overlaps.map(o => o.item_code)) : new Set();
    let rules = 0, items = 0;
    p.groups.forEach(g => {
        const n = g.items.filter(i => !skip.has(i.item_code)).length;
        if (n) { rules++; items += n; }
    });
    const moving = I.resolve === 'move' ? new Set(p.overlaps.filter(o => !o.promotional_scheme).map(o => o.rule)).size : 0;
    const noWin = I.resolve === 'priority' && p.groups.some(g => g.priority === 0);
    $bar.removeAttr('hidden').html(`
        <div><b>${rules} rule${rules === 1 ? '' : 's'}</b> · ${items} item${items === 1 ? '' : 's'}
            ${p.errors.length ? ` · <span class="is-bad">${p.errors.length} row(s) skipped</span>` : ''}
            ${moving ? ` · items taken from ${moving} existing rule(s)` : ''}
            ${skip.size ? ` · ${skip.size} item(s) left out` : ''}
            ${noWin ? ' · <span class="is-bad">a rule cannot win with any priority: move or leave out instead</span>' : ''}</div>
        <span class="pr-spacer"></span>
        <button class="pr-btn pr-btn-primary" id="pri-create" ${rules && !noWin ? '' : 'disabled'}><i class="fa fa-check"></i> Create ${rules} pricing rule${rules === 1 ? '' : 's'}</button>`);
}

function create() {
    if (I.busy || !I.preview) return;
    const go = () => {
        I.busy = true;
        frappe.call({
            method: API + 'apply_import',
            args: {
                file_url: I.fileUrl, company: company(), title_prefix: I.prefix, valid_from: I.vf,
                valid_upto: I.vu || null, price_list: I.pl || null, resolve: I.resolve
            },
            freeze: true, freeze_message: 'Creating pricing rules…',
            callback: r => { renderResult(r.message || {}); },
            always: () => { I.busy = false; }
        });
    };
    const moving = I.resolve === 'move' && I.preview.overlaps.length;
    if (moving) {
        frappe.confirm('Some items will be removed from their current pricing rules and put in the new ones. Continue?', go);
    } else {
        go();
    }
}

function renderResult(res) {
    const created = res.created || [];
    I.preview = null;
    I.fileUrl = null;
    I.fileName = '';
    $('#pri-bar').attr('hidden', true).empty();
    $('.pr-import').html(`
        <div class="pr-done">
            <div class="pr-done-icon"><i class="fa fa-check-circle"></i></div>
            <h3>${created.length} pricing rule${created.length === 1 ? '' : 's'} created</h3>
            <div class="pr-card pr-card-sm"><table class="pr-table pr-it-table">
                <thead><tr><th>Rule</th><th>Title</th><th class="num">Discount</th><th class="num">Items</th><th class="num">Priority</th></tr></thead>
                <tbody>${created.map(c => `<tr><td><a href="/app/pricing-rule/${encodeURIComponent(c.name)}" target="_blank" rel="noopener">${esc(c.name)}</a></td>
                    <td>${esc(c.title)}</td><td class="num">${pct(c.discount)}</td><td class="num">${c.items}</td><td class="num">${c.priority || ''}</td></tr>`).join('')}</tbody>
            </table></div>
            ${(res.moved || []).length ? `<p>Items taken from: ${res.moved.map(m => `<b>${esc(m.rule)}</b> (${m.items.length} item${m.items.length > 1 ? 's' : ''}${m.action === 'disabled' ? ', now disabled' : ''})`).join(', ')}</p>` : ''}
            ${(res.skipped_overlap || []).length ? `<p>Left out because they already had a rule: ${res.skipped_overlap.map(esc).join(', ')}</p>` : ''}
            ${(res.errors || []).length ? `<p class="is-bad">${res.errors.length} row(s) with errors were skipped.</p>` : ''}
            <div class="pr-done-actions">
                <button class="pr-btn pr-btn-primary" id="pri-to-rules"><i class="fa fa-tags"></i> See the rules</button>
                <button class="pr-btn" id="pri-again"><i class="fa fa-upload"></i> Import another file</button>
            </div>
        </div>`);
    $('.pr-import').on('click', 'a[target="_blank"]', function (e) { e.preventDefault(); e.stopPropagation(); window.open(this.href, '_blank', 'noopener'); });
    frappe.show_alert({ message: `${created.length} pricing rule(s) created`, indicator: 'green' }, 5);
}

// ---------------------------------------------------------------------------
// styles
// ---------------------------------------------------------------------------

const CSS = `
<style>
/* Slate palette shared with the other Isoft screens; dark follows the desk theme. */
/* Frappe's watermark (body::before) paints over the tables; route-scoped so other pages keep it. */
body[data-route="pricing-rules-manager"]::before { display: none; }
/* The desk title bar only repeats the page name (the tab row and each screen's
   heading already say it) and costs ~75px, so this page goes without it. */
#page-pricing-rules-manager .page-head { display: none; }
.prm-host {
    --pr-page: #f1f5f9; --pr-surface: #ffffff; --pr-surface-2: #f8fafc; --pr-surface-3: #f1f5f9;
    --pr-line: #e2e8f0; --pr-line-2: #cbd5e1;
    --pr-text: #0f172a; --pr-text-2: #334155; --pr-text-3: #64748b; --pr-text-4: #94a3b8;
    --pr-brand: #2563eb; --pr-brand-strong: #1d4ed8;
    --pr-brand-soft: color-mix(in srgb, var(--pr-brand) 10%, var(--pr-surface));
    --pr-brand-ring: color-mix(in srgb, var(--pr-brand) 28%, transparent);
    --pr-ok: #15803d; --pr-warn: #b45309; --pr-bad: #b91c1c; --pr-r: 8px;
    height: calc(100vh - 112px); min-height: 520px; padding: 0.75rem 0 0.5rem;
}
[data-theme="dark"] .prm-host {
    --pr-page: #0f172a; --pr-surface: #1e293b; --pr-surface-2: #172033; --pr-surface-3: #273449;
    --pr-line: #334155; --pr-line-2: #475569;
    --pr-text: #f1f5f9; --pr-text-2: #cbd5e1; --pr-text-3: #94a3b8; --pr-text-4: #64748b;
    --pr-brand: #3b82f6; --pr-brand-strong: #60a5fa;
    --pr-ok: #4ade80; --pr-warn: #fbbf24; --pr-bad: #f87171;
}
.pr-i-money { color: var(--pr-ok); }
.pr-i-item  { color: var(--pr-brand); }
.pr-company { display: inline-flex; align-items: center; gap: 0.35rem; margin-left: 0.4rem; color: var(--pr-text-4); font-size: 0.75rem; }
.pr-company .pr-input { height: 28px; width: auto; max-width: 240px; font-size: 0.78rem; }
.pr-shell {
    display: flex; flex-direction: column; gap: 0.55rem; height: 100%; min-height: 0;
    color: var(--pr-text);
    font-family: var(--font-stack, 'Inter', system-ui, -apple-system, sans-serif);
}
.pr-shell [hidden] { display: none !important; }
.pr-shell *:focus { outline: none; }
.pr-shell-nav {
    display: flex; align-items: center; gap: 0.25rem; flex-shrink: 0; overflow-x: auto; overflow-y: hidden;
    border-bottom: 1px solid var(--pr-line); padding-bottom: 0.1rem;
}
.pr-shell-nav button {
    display: inline-flex; align-items: center; gap: 0.4rem; white-space: nowrap;
    border: 0; border-bottom: 2px solid transparent; background: transparent;
    font-family: inherit; font-size: 0.82rem; font-weight: 500;
    color: var(--pr-text-3); padding: 0.35rem 0.7rem 0.4rem; cursor: pointer; border-radius: 6px 6px 0 0;
}
.pr-shell-nav button:hover { color: var(--pr-text); background: var(--pr-surface-3); }
.pr-shell-nav button.is-on { color: var(--pr-brand-strong); border-bottom-color: var(--pr-brand); font-weight: 600; }
.pr-fixed { margin-left: auto; font-size: 0.72rem; color: var(--pr-text-4); white-space: nowrap; padding: 0 0.3rem; }
.pr-fixed i { font-size: 0.65rem; margin-right: 0.2rem; }
.pr-shell-body { flex: 1 1 auto; min-height: 0; display: flex; }
.pr-root { flex: 1 1 auto; min-width: 0; height: 100%; display: flex; flex-direction: column; gap: 0.6rem; position: relative; overflow: hidden; }
.pr-root.pr-scroll { overflow-y: auto; display: block; }
.pr-root button:focus-visible, .pr-root input:focus-visible, .pr-root select:focus-visible { box-shadow: 0 0 0 3px var(--pr-brand-ring); }

.pr-head { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
.pr-title { display: flex; align-items: center; gap: 0.45rem; font-size: 0.95rem; font-weight: 600; }
.pr-title i { color: var(--pr-brand); font-size: 0.85rem; }
.pr-sub { font-size: 0.75rem; color: var(--pr-text-3); }
.pr-spacer { flex: 1; }
.pr-dim { color: var(--pr-text-4); font-weight: 400; }
.is-bad { color: var(--pr-bad); }
.is-warn { color: var(--pr-warn); }

.pr-btn {
    height: 32px; padding: 0 0.75rem; border: 1px solid var(--pr-line-2); border-radius: 6px;
    background: var(--pr-surface); color: var(--pr-text-2); font-family: inherit; font-size: 0.82rem; font-weight: 500;
    cursor: pointer; display: inline-flex; align-items: center; gap: 0.4rem; white-space: nowrap; text-decoration: none !important;
}
.pr-btn:hover:not(:disabled) { background: var(--pr-surface-3); color: var(--pr-text); }
.pr-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.pr-btn-primary { background: var(--pr-brand); border-color: var(--pr-brand); color: #fff; font-weight: 600; }
.pr-btn-primary:hover:not(:disabled) { background: var(--pr-brand-strong); border-color: var(--pr-brand-strong); color: #fff; }
.pr-btn-danger { color: var(--pr-bad); }
.pr-btn-danger:hover:not(:disabled) { background: color-mix(in srgb, var(--pr-bad) 10%, var(--pr-surface)); color: var(--pr-bad); }
.pr-link { border: 0; background: transparent; color: var(--pr-brand-strong); font-family: inherit; font-size: 0.8rem; cursor: pointer; padding: 0; }
.pr-link:hover { text-decoration: underline; }
.pr-x { border: 0; background: transparent; color: var(--pr-text-4); cursor: pointer; font-size: 1.15rem; line-height: 1; padding: 0.1rem 0.35rem; border-radius: 5px; }
.pr-x:hover { color: var(--pr-bad); background: color-mix(in srgb, var(--pr-bad) 12%, transparent); }

.pr-input {
    height: 32px; border: 1px solid var(--pr-line-2); border-radius: 6px; background: var(--pr-surface); color: var(--pr-text);
    font-family: inherit; font-size: 0.82rem; padding: 0 0.5rem; width: 100%; min-width: 0;
}
.pr-input:focus { border-color: var(--pr-brand); box-shadow: 0 0 0 3px var(--pr-brand-ring); }
.pr-input:disabled { background: var(--pr-surface-2); color: var(--pr-text-3); }
.pr-check { display: inline-flex; align-items: center; gap: 0.4rem; font-size: 0.82rem; color: var(--pr-text-2); margin: 0; height: 32px; white-space: nowrap; cursor: pointer; }
.pr-check input { accent-color: var(--pr-brand); width: 15px; height: 15px; margin: 0; }

.pr-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 0.5rem; flex-shrink: 0; }
.pr-tile { border: 1px solid var(--pr-line); border-radius: var(--pr-r, 8px); background: var(--pr-surface); padding: 0.5rem 0.65rem; }
.pr-tile.is-click { cursor: pointer; }
.pr-tile.is-click:hover { border-color: var(--pr-line-2); background: var(--pr-surface-2); }
.pr-tile.is-on { border-color: var(--pr-brand); box-shadow: 0 0 0 2px var(--pr-brand-ring); }
.pr-tile .k { font-size: 0.72rem; color: var(--pr-text-3); }
.pr-tile .v { font-size: 1.05rem; font-weight: 700; font-variant-numeric: tabular-nums; }
.pr-tile.is-bad .v { color: var(--pr-bad); }
.pr-tile.is-ok .v { color: var(--pr-ok); }
.pr-tile.is-warn .v { color: var(--pr-warn); }

.pr-conflict {
    display: flex; align-items: flex-start; gap: 0.6rem; flex-shrink: 0; font-size: 0.8rem; line-height: 1.5;
    padding: 0.55rem 0.75rem; border-radius: var(--pr-r, 8px); color: var(--pr-text-2);
    background: color-mix(in srgb, var(--pr-bad) 8%, var(--pr-surface));
    border: 1px solid color-mix(in srgb, var(--pr-bad) 30%, var(--pr-line));
}
.pr-conflict > i { color: var(--pr-bad); margin-top: 0.2rem; }
.pr-conflict > div { flex: 1; }
.pr-conflict-list { font-size: 0.75rem; color: var(--pr-text-3); margin-top: 0.2rem; }

.pr-filters {
    display: flex; flex-wrap: wrap; gap: 0.5rem 0.7rem; align-items: center; flex-shrink: 0;
    background: var(--pr-surface); border: 1px solid var(--pr-line); border-radius: var(--pr-r, 8px); padding: 0.5rem 0.7rem;
}
.pr-search { position: relative; flex: 1 1 260px; max-width: 420px; }
.pr-search i { position: absolute; left: 0.6rem; top: 50%; transform: translateY(-50%); font-size: 0.75rem; color: var(--pr-text-4); }
.pr-search .pr-input { padding-left: 1.8rem; }
.pr-seg { display: inline-flex; border: 1px solid var(--pr-line-2); border-radius: 7px; overflow: hidden; background: var(--pr-surface); flex-wrap: wrap; }
.pr-seg button {
    border: 0; background: transparent; color: var(--pr-text-3); cursor: pointer; font-family: inherit;
    font-size: 0.78rem; padding: 0 0.7rem; height: 30px; display: inline-flex; align-items: center; gap: 0.35rem; white-space: nowrap;
}
.pr-seg button + button { border-left: 1px solid var(--pr-line-2); }
.pr-seg button.is-on { background: var(--pr-brand); color: #fff; font-weight: 600; }
.pr-seg button:not(.is-on):hover { background: var(--pr-surface-3); color: var(--pr-text); }
.pr-seg-lg button { height: 34px; font-size: 0.82rem; padding: 0 0.9rem; }

.pr-bulk {
    display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; flex-shrink: 0; font-size: 0.82rem;
    padding: 0.4rem 0.7rem; border-radius: var(--pr-r, 8px); background: var(--pr-brand-soft); border: 1px solid color-mix(in srgb, var(--pr-brand) 30%, var(--pr-line));
}

.pr-card { flex: 1; min-height: 0; display: flex; flex-direction: column; background: var(--pr-surface); border: 1px solid var(--pr-line); border-radius: var(--pr-r, 8px); overflow: hidden; }
.pr-card-sm { flex: none; max-height: 300px; }
.pr-wrap { flex: 1; overflow: auto; scrollbar-width: thin; scrollbar-color: var(--pr-line-2) transparent; }
.pr-foot { display: flex; justify-content: space-between; gap: 1rem; padding: 0.4rem 0.75rem; border-top: 1px solid var(--pr-line); background: var(--pr-surface-2); font-size: 0.74rem; color: var(--pr-text-3); }

/* Rules screen */
.pr-head-text { display: flex; align-items: baseline; gap: 1rem; flex-wrap: wrap; }
.pr-kpis { display: flex; gap: 0.35rem; flex-wrap: wrap; font-size: 0.74rem; }
.pr-kpis > span { padding: 0.12rem 0.55rem; border-radius: 999px; background: var(--pr-surface); border: 1px solid var(--pr-line); color: var(--pr-text-3); white-space: nowrap; }
.pr-kpis > span b { color: var(--pr-text); font-variant-numeric: tabular-nums; }
.pr-kpis > span.is-warn { border-color: color-mix(in srgb, var(--pr-warn) 35%, var(--pr-line)); }
.pr-kpis > span.is-warn b { color: var(--pr-warn); }
.pr-kpis > span.is-bad { border-color: color-mix(in srgb, var(--pr-bad) 40%, var(--pr-line)); color: var(--pr-bad); }
.pr-kpis > span.is-bad b { color: var(--pr-bad); }
.pr-kpis > span.is-ok { color: var(--pr-ok); }
.pr-kpis > span.is-link { cursor: pointer; }
.pr-kpis > span.is-link:hover { background: color-mix(in srgb, var(--pr-bad) 8%, var(--pr-surface)); }
.pr-btn-icon { width: 32px; padding: 0; justify-content: center; }
.pr-btn-sm { height: 27px; padding: 0 0.6rem; font-size: 0.76rem; }

.pr-alert {
    display: flex; align-items: center; gap: 0.6rem; flex-shrink: 0; font-size: 0.8rem; color: var(--pr-text-2);
    padding: 0.4rem 0.5rem 0.4rem 0.75rem; border-radius: var(--pr-r);
    background: color-mix(in srgb, var(--pr-bad) 8%, var(--pr-surface));
    border: 1px solid color-mix(in srgb, var(--pr-bad) 30%, var(--pr-line));
}
.pr-alert > i { color: var(--pr-bad); }
.pr-alert > span { flex: 1; }
.pr-alert b { color: var(--pr-bad); }

.pr-tabs { display: flex; gap: 0.15rem; flex-wrap: wrap; }
.pr-tabs button {
    display: inline-flex; align-items: center; gap: 0.4rem; height: 30px; padding: 0 0.65rem;
    border: 0; border-radius: 6px; background: transparent; color: var(--pr-text-3);
    font-family: inherit; font-size: 0.8rem; font-weight: 500; cursor: pointer; white-space: nowrap;
}
.pr-tabs button:hover { background: var(--pr-surface-3); color: var(--pr-text); }
.pr-tabs button.is-on { background: var(--pr-brand-soft); color: var(--pr-brand-strong); font-weight: 600; }
.pr-tabs .pr-count {
    min-width: 20px; padding: 0 0.35rem; border-radius: 999px; font-size: 0.68rem; font-weight: 600; line-height: 17px; text-align: center;
    background: var(--pr-surface-3); color: var(--pr-text-3); font-variant-numeric: tabular-nums;
}
.pr-tabs button.is-on .pr-count { background: var(--pr-brand); color: #fff; }
.pr-tabs button.is-bad { color: var(--pr-bad); }
.pr-tabs button.is-bad .pr-count { background: var(--pr-bad); color: #fff; }
.pr-tabs button.is-bad.is-on { background: color-mix(in srgb, var(--pr-bad) 10%, var(--pr-surface)); }
.pr-tabs + .pr-spacer + .pr-check { margin-left: auto; }
.pr-filters .pr-search { flex: 0 1 300px; }

.pr-rules td { padding-top: 0.38rem; padding-bottom: 0.38rem; }
.pr-rules tr.is-off td:not(.pr-on):not(.pr-chk) { opacity: 0.6; }
.pr-nw { white-space: nowrap; }
.pr-ell { max-width: 220px; overflow: hidden; text-overflow: ellipsis; }
.pr-scope-k { color: var(--pr-text-4); font-size: 0.72rem; }
.pr-disc { display: inline-block; min-width: 46px; text-align: center; font-weight: 700; font-variant-numeric: tabular-nums;
    padding: 0.05rem 0.4rem; border-radius: 6px; color: var(--pr-ok); background: color-mix(in srgb, var(--pr-ok) 11%, var(--pr-surface)); }
.pr-prio { color: var(--pr-brand-strong); }
.pr-on { width: 44px; text-align: center; }
a.pr-hit.is-bad { text-decoration: none; }
a.pr-hit.is-bad:hover { text-decoration: underline; }

/* Conflicts section */
.pr-conflicts { padding: 0.75rem; display: flex; flex-direction: column; gap: 0.7rem; }
.pr-conf-intro { margin: 0; font-size: 0.78rem; color: var(--pr-text-3); line-height: 1.5; max-width: 900px; }
.pr-ccard { border: 1px solid color-mix(in srgb, var(--pr-bad) 28%, var(--pr-line)); border-radius: 10px; overflow: hidden; background: var(--pr-surface); flex-shrink: 0; }
.pr-ccard-head {
    display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; padding: 0.5rem 0.75rem; font-size: 0.8rem;
    background: color-mix(in srgb, var(--pr-bad) 7%, var(--pr-surface)); border-bottom: 1px solid color-mix(in srgb, var(--pr-bad) 20%, var(--pr-line));
}
.pr-ccard-head > i { color: var(--pr-bad); }
.pr-codes { display: inline-flex; gap: 0.3rem; flex-wrap: wrap; align-items: center; }
.pr-codes code { font-size: 0.72rem; padding: 0.05rem 0.4rem; border-radius: 5px; background: var(--pr-surface); border: 1px solid var(--pr-line); color: var(--pr-text); }
.pr-ccard-body { display: grid; grid-template-columns: 1fr auto 1fr; }
@media (max-width: 1000px) { .pr-ccard-body { grid-template-columns: 1fr; } .pr-cvs { padding: 0.2rem 0; } }
.pr-cvs { display: flex; align-items: center; justify-content: center; padding: 0 0.6rem; font-size: 0.7rem; font-weight: 700; color: var(--pr-text-4); text-transform: uppercase; }
.pr-cside { padding: 0.65rem 0.8rem; display: flex; flex-direction: column; gap: 0.35rem; min-width: 0; }
.pr-cside-head { display: flex; align-items: center; gap: 0.5rem; }
.pr-cside-head .pr-open { font-weight: 600; color: var(--pr-text); text-decoration: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
.pr-cside-head .pr-open:hover { color: var(--pr-brand-strong); text-decoration: underline; }
.pr-cside-meta { font-size: 0.72rem; color: var(--pr-text-3); }
.pr-cside-acts { display: flex; gap: 0.35rem; flex-wrap: wrap; margin-top: 0.15rem; }
.pr-cside-note { font-size: 0.7rem; color: var(--pr-text-4); }
.pr-empty-ok i { color: var(--pr-ok); }

.pr-table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 0.8rem; }
.pr-table thead th {
    position: sticky; top: 0; z-index: 2; background: var(--pr-surface-2); color: var(--pr-text-2);
    font-size: 0.71rem; font-weight: 600; text-align: left; padding: 0.45rem 0.6rem; border-bottom: 1px solid var(--pr-line); white-space: nowrap;
}
.pr-table td { padding: 0.45rem 0.6rem; border-bottom: 1px solid var(--pr-line); vertical-align: middle; }
.pr-table tbody tr:hover td { background: var(--pr-surface-2); }
.pr-table tbody tr.is-sel td { background: var(--pr-brand-soft); }
.pr-table tr.is-conflict td:first-child { box-shadow: inset 3px 0 0 0 var(--pr-bad); }
.pr-table .num { text-align: right; font-variant-numeric: tabular-nums; }
.pr-table .pr-chk { width: 34px; padding-right: 0.2rem; }
.pr-table .pr-chk input { accent-color: var(--pr-brand); width: 15px; height: 15px; margin: 0; display: block; cursor: pointer; }
.pr-rule { min-width: 220px; }
.pr-rule a.pr-open { font-weight: 600; color: var(--pr-text); text-decoration: none; }
.pr-rule a.pr-open:hover { color: var(--pr-brand-strong); text-decoration: underline; }
.pr-id { display: block; font-size: 0.7rem; color: var(--pr-text-4); }
.pr-dr-title .pr-id { display: inline; margin: 0 0.4rem; font-weight: 400; }
.pr-hit { display: inline-block; font-size: 0.7rem; color: var(--pr-brand-strong); margin-top: 0.1rem; }
.pr-hit.is-bad { color: var(--pr-bad); margin-right: 0.5rem; }
.pr-scope { font-size: 0.76rem; color: var(--pr-text-2); }
.pr-dates { white-space: nowrap; font-variant-numeric: tabular-nums; }
.pr-it-name { display: block; font-size: 0.72rem; color: var(--pr-text-3); max-width: 360px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.pr-chip { display: inline-flex; align-items: center; padding: 0.06rem 0.45rem; border-radius: 999px; font-size: 0.7rem; font-weight: 600; white-space: nowrap; }
.pr-chip-ok { background: color-mix(in srgb, var(--pr-ok) 15%, var(--pr-surface)); color: var(--pr-ok); }
.pr-chip-bad { background: color-mix(in srgb, var(--pr-bad) 15%, var(--pr-surface)); color: var(--pr-bad); }
.pr-chip-warn { background: color-mix(in srgb, var(--pr-warn) 16%, var(--pr-surface)); color: var(--pr-warn); }
.pr-chip-brand { background: var(--pr-brand-soft); color: var(--pr-brand-strong); }
.pr-chip-mute { background: var(--pr-surface-3); color: var(--pr-text-3); }

.pr-switch { position: relative; display: inline-block; width: 30px; height: 17px; margin: 0; cursor: pointer; vertical-align: middle; }
.pr-switch input { opacity: 0; width: 0; height: 0; position: absolute; }
.pr-switch span { position: absolute; inset: 0; background: var(--pr-line-2); border-radius: 999px; transition: background 0.15s; }
.pr-switch span::after { content: ''; position: absolute; left: 2px; top: 2px; width: 13px; height: 13px; border-radius: 50%; background: #fff; transition: transform 0.15s; }
.pr-switch input:checked + span { background: var(--pr-ok); }
.pr-switch input:checked + span::after { transform: translateX(13px); }

.pr-empty { text-align: center; padding: 2.4rem 1rem; color: var(--pr-text-3); }
.pr-empty i { display: block; font-size: 1.6rem; color: var(--pr-text-4); margin-bottom: 0.55rem; }
.pr-empty h3 { font-size: 0.92rem; font-weight: 600; color: var(--pr-text-2); margin: 0 0 0.3rem; }
.pr-empty p { margin: 0 auto; font-size: 0.8rem; max-width: 460px; line-height: 1.5; }
.pr-empty-sm { padding: 1rem; }

/* drawer */
.pr-drawer-back { position: fixed; inset: 0; z-index: 1030; background: rgba(15, 23, 42, 0); transition: background 0.18s; }
.pr-drawer-back.is-open { background: rgba(15, 23, 42, 0.25); }
.pr-drawer {
    position: fixed; top: 0; right: 0; bottom: 0; z-index: 1031; width: min(640px, 100vw);
    display: flex; flex-direction: column; background: var(--pr-surface); color: var(--pr-text);
    border-left: 1px solid var(--pr-line); box-shadow: -12px 0 32px rgba(15, 23, 42, 0.18);
    transform: translateX(100%); transition: transform 0.18s ease-out;
    font-family: var(--font-stack, 'Inter', system-ui, -apple-system, sans-serif);
}
.pr-drawer.is-open { transform: none; }
.pr-drawer [hidden] { display: none !important; }
.pr-dr-head { display: flex; align-items: center; gap: 0.5rem; padding: 0.75rem 1rem; border-bottom: 1px solid var(--pr-line); flex-shrink: 0; }
.pr-dr-title { font-size: 0.95rem; font-weight: 600; display: flex; align-items: center; flex-wrap: wrap; gap: 0.2rem; }
.pr-dr-body { flex: 1; overflow-y: auto; padding: 0.9rem 1rem; display: flex; flex-direction: column; gap: 0.75rem; }
.pr-dr-body > * { flex-shrink: 0; }
.pr-dr-foot { display: flex; align-items: center; gap: 0.5rem; padding: 0.65rem 1rem; border-top: 1px solid var(--pr-line); background: var(--pr-surface-2); flex-shrink: 0; }

.pr-form { display: grid; grid-template-columns: 1fr 1fr; gap: 0.6rem 0.75rem; }
.pr-form-4 { grid-template-columns: 2fr 1fr 1fr 1.3fr; }
@media (max-width: 900px) { .pr-form-4 { grid-template-columns: 1fr 1fr; } }
.pr-span2 { grid-column: span 2; }
.pr-field { display: flex; flex-direction: column; gap: 0.2rem; min-width: 0; }
.pr-field > label { font-size: 0.72rem; color: var(--pr-text-3); font-weight: 500; margin: 0; }
.pr-num { text-align: right; }
.pr-fixed-row { font-size: 0.72rem; color: var(--pr-text-3); background: var(--pr-surface-2); border: 1px dashed var(--pr-line-2); border-radius: 6px; padding: 0.35rem 0.6rem; }
.pr-fixed-row i { font-size: 0.65rem; margin-right: 0.25rem; color: var(--pr-text-4); }
.pr-grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; }
.pr-grid2 > div { border: 1px solid var(--pr-line); border-radius: 6px; padding: 0.45rem 0.6rem; }
.pr-grid2 .k { display: block; font-size: 0.7rem; color: var(--pr-text-3); }

.pr-items-head { display: flex; align-items: center; gap: 0.5rem; font-size: 0.85rem; }
.pr-it-filter { max-width: 200px; height: 28px; }
.pr-add { display: flex; align-items: center; gap: 0.75rem; }
.pr-add-ctl { flex: 1; }
.pr-add-ctl .form-group { margin: 0; }
.pr-add-ctl .awesomplete > ul { z-index: 20; }
.pr-add-ctl input { height: 32px; font-size: 0.82rem; }
.pr-items { border: 1px solid var(--pr-line); border-radius: 8px; overflow: auto; max-height: 48vh; }
.pr-it-table td { padding: 0.35rem 0.55rem; }
.pr-it-table .pr-input { height: 28px; font-size: 0.78rem; }
.pr-it-uom { width: 110px; }
.pr-it-max { width: 72px; text-align: right; }

.pr-note { font-size: 0.8rem; line-height: 1.5; padding: 0.6rem 0.75rem; border-radius: 8px; border: 1px solid var(--pr-line); background: var(--pr-surface-2); color: var(--pr-text-2); }
.pr-note p { margin: 0.3rem 0; }
.pr-note.is-warn { background: color-mix(in srgb, var(--pr-warn) 10%, var(--pr-surface)); border-color: color-mix(in srgb, var(--pr-warn) 35%, var(--pr-line)); color: var(--pr-text-2); }
.pr-note.is-bad { background: color-mix(in srgb, var(--pr-bad) 7%, var(--pr-surface)); border-color: color-mix(in srgb, var(--pr-bad) 30%, var(--pr-line)); color: var(--pr-text-2); }
.pr-note.is-bad > b { color: var(--pr-bad); }
.pr-note .pr-table { margin: 0.4rem 0; background: var(--pr-surface); border: 1px solid var(--pr-line); border-radius: 6px; }
.pr-note-actions { display: flex; align-items: center; gap: 0.75rem; margin-top: 0.4rem; }

/* import */
.pr-import { max-width: 1100px; margin: 0 auto; display: flex; flex-direction: column; gap: 0.75rem; padding-bottom: 1rem; }
.pr-step { display: flex; gap: 0.85rem; background: var(--pr-surface); border: 1px solid var(--pr-line); border-radius: var(--pr-r, 8px); padding: 0.9rem 1rem; }
.pr-step-n { flex: 0 0 26px; height: 26px; border-radius: 50%; background: var(--pr-brand-soft); color: var(--pr-brand-strong); font-weight: 700; font-size: 0.8rem; display: flex; align-items: center; justify-content: center; }
.pr-step-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 0.6rem; align-items: flex-start; }
.pr-step-body > * { max-width: 100%; }
.pr-step-body > .pr-form, .pr-step-body > #pri-preview, .pr-step-body > .pr-drop, .pr-step-body > .pr-fixed-row { width: 100%; }
.pr-step h4 { font-size: 0.88rem; font-weight: 600; margin: 0.15rem 0 0; }
.pr-cols { display: grid; grid-template-columns: repeat(4, minmax(120px, 1fr)); gap: 0.4rem; width: 100%; }
.pr-cols > div { border: 1px solid var(--pr-line); border-radius: 6px; padding: 0.4rem 0.55rem; background: var(--pr-surface-2); }
.pr-cols b { display: block; font-size: 0.8rem; }
.pr-cols span { font-size: 0.7rem; color: var(--pr-text-3); }
.pr-example { border: 1px solid var(--pr-line); border-radius: 6px; overflow: hidden; }
.pr-example .pr-arrow { color: var(--pr-brand-strong); font-size: 0.74rem; white-space: nowrap; border-left: 1px solid var(--pr-line); }
.pr-drop {
    display: flex; align-items: center; justify-content: center; gap: 0.6rem; margin: 0; cursor: pointer;
    min-height: 74px; border: 2px dashed var(--pr-line-2); border-radius: 10px; color: var(--pr-text-3); font-size: 0.85rem;
    background: var(--pr-surface-2);
}
.pr-drop i { font-size: 1.3rem; color: var(--pr-brand); }
.pr-drop:hover, .pr-drop.is-over { border-color: var(--pr-brand); background: var(--pr-brand-soft); color: var(--pr-text-2); }
#pri-preview { display: flex; flex-direction: column; gap: 0.75rem; }
.pr-block { display: flex; flex-direction: column; gap: 0.4rem; }
.pr-block h5 { font-size: 0.84rem; font-weight: 600; margin: 0; }
.pr-block p { margin: 0; font-size: 0.78rem; }
.pr-ul { margin: 0; padding-left: 1.1rem; font-size: 0.78rem; color: var(--pr-text-2); }
.pr-gcards { display: flex; flex-direction: column; gap: 0.4rem; }
.pr-gcard { border: 1px solid var(--pr-line); border-radius: 8px; overflow: hidden; background: var(--pr-surface); }
.pr-gcard-head { display: flex; align-items: center; gap: 0.6rem; padding: 0.5rem 0.7rem; cursor: pointer; font-size: 0.82rem; }
.pr-gcard-head:hover { background: var(--pr-surface-2); }
.pr-gpct { min-width: 58px; text-align: center; font-weight: 700; color: var(--pr-ok); background: color-mix(in srgb, var(--pr-ok) 12%, var(--pr-surface)); border-radius: 6px; padding: 0.15rem 0.4rem; font-variant-numeric: tabular-nums; }
.pr-gtitle { font-weight: 600; }
.pr-caret { color: var(--pr-text-4); font-size: 0.7rem; transition: transform 0.15s; }
.pr-gcard.is-open .pr-caret { transform: rotate(180deg); }
.pr-gcard-body { display: none; border-top: 1px solid var(--pr-line); max-height: 320px; overflow: auto; }
.pr-gcard.is-open .pr-gcard-body { display: block; }
.pr-actionbar {
    position: sticky; bottom: 0; z-index: 5; max-width: 1100px; margin: 0 auto; display: flex; align-items: center; gap: 0.75rem;
    padding: 0.6rem 0.9rem; font-size: 0.82rem; border: 1px solid var(--pr-line); border-radius: 10px;
    background: color-mix(in srgb, var(--pr-surface) 94%, transparent); backdrop-filter: blur(6px);
    box-shadow: 0 -6px 20px rgba(15, 23, 42, 0.08);
}
.pr-done { text-align: center; padding: 1.5rem 1rem; background: var(--pr-surface); border: 1px solid var(--pr-line); border-radius: var(--pr-r, 8px); display: flex; flex-direction: column; gap: 0.7rem; align-items: center; }
.pr-done-icon i { font-size: 2.2rem; color: var(--pr-ok); }
.pr-done h3 { font-size: 1rem; font-weight: 600; margin: 0; }
.pr-done .pr-card { width: 100%; max-width: 760px; text-align: left; }
.pr-done p { margin: 0; font-size: 0.8rem; color: var(--pr-text-2); }
.pr-done-actions { display: flex; gap: 0.5rem; }
</style>`;

})();
