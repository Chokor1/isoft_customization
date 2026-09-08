// Gold navbar bell, attention-grabbing when something is new.
//
// Core (frappe/ui/notifications/notifications.js) signals "you have something new"
// by swapping two spans inside .notifications-icon: it jQuery-hides .notifications-seen
// and shows .notifications-unseen, whose SVG carries a 5px red dot. That is easy to miss.
//
// Icon: app.html inlines the icon sprite *above* the app_include_js tags, and the navbar
// is only rendered later by desk startup (on DOM ready). So at parse time we swap the
// contents of the two bell <symbol>s for a filled gold bell; every later <use> of them
// renders gold from the very first paint -- no grey-then-gold flash, no JS class needed.
// Nothing else in frappe/erpnext references these two symbol ids (checked v13).
//
// Halo: pure CSS on .notifications-unseen::before, so it appears exactly when core shows
// that span, without waiting for any script of ours.
//
// NotificationsView is a module-private class, so it cannot be subclassed or patched.
// For the ring shake we watch the inline `style` core writes on .notifications-unseen
// (jQuery .toggle()) with a MutationObserver and mirror it as a class on the anchor.
//
// The unread badge is a separate concept from "unseen": core clears unseen the moment
// the dropdown opens, but individual notifications stay `read = 0` until clicked or
// "Mark all as read". The badge tracks unread, so a user who peeked and closed the
// dropdown still sees how many items are waiting; the loud animation follows unseen only.
// The count is one xcall after startup (bootinfo is redis-cached per user, so shipping
// it in boot would go stale).

(function () {
	// Filled gold bell, same 20x20 viewBox as core's outline bell.
	const GOLD_BELL =
		'<path d="M10 2.2c.6 0 1.1.5 1.1 1.1v.5c2.3.5 3.9 2.5 3.9 4.9v3.6c0 .6.2 1.1.6 1.5l1.2 1.2H3.2l1.2-1.2c.4-.4.6-.9.6-1.5V8.7c0-2.4 1.6-4.4 3.9-4.9v-.5c0-.6.5-1.1 1.1-1.1z" fill="#F2B705" stroke="#B8860B" stroke-width="1" stroke-linejoin="round"/>' +
		'<path d="M7.8 16.2h4.4a2.2 2.2 0 0 1-4.4 0z" fill="#B8860B"/>';

	function goldify_symbols() {
		['icon-notification', 'icon-notification-with-indicator'].forEach((id) => {
			const sym = document.getElementById(id);
			if (sym && !sym.getAttribute('data-isoft-gold')) {
				sym.innerHTML = GOLD_BELL;
				sym.setAttribute('viewBox', '0 0 20 20');
				sym.setAttribute('data-isoft-gold', '1');
			}
		});
	}
	goldify_symbols();
	document.addEventListener('DOMContentLoaded', goldify_symbols);
})();

(function () {
	const UNSEEN_CLASS = 'isoft-notif-unseen';
	const RING_CLASS = 'isoft-notif-ring';
	const HAS_COUNT_CLASS = 'isoft-notif-has-count';
	const BADGE_CLASS = 'isoft-notif-count';
	const RING_MS = 1200;
	const RING_EVERY_MS = 12000;

	let $icon = null;
	let ringTimer = null;
	let ringInterval = null;
	let countInFlight = null;

	function ring() {
		if (!$icon) return;
		$icon.removeClass(RING_CLASS);
		// Force reflow so re-adding the class restarts the CSS animation.
		void $icon[0].offsetWidth;
		$icon.addClass(RING_CLASS);
		clearTimeout(ringTimer);
		ringTimer = setTimeout(() => $icon && $icon.removeClass(RING_CLASS), RING_MS);
	}

	function startRinging() {
		stopRinging();
		ring();
		ringInterval = setInterval(ring, RING_EVERY_MS);
	}

	function stopRinging() {
		clearInterval(ringInterval);
		ringInterval = null;
		clearTimeout(ringTimer);
		if ($icon) $icon.removeClass(RING_CLASS);
	}

	function setUnseen(unseen) {
		if (!$icon) return;
		const was = $icon.hasClass(UNSEEN_CLASS);
		$icon.toggleClass(UNSEEN_CLASS, unseen);
		if (unseen && !was) {
			startRinging();
		} else if (!unseen && was) {
			stopRinging();
		}
	}

	function renderCount(n) {
		if (!$icon) return;
		let $badge = $icon.find('.' + BADGE_CLASS);
		if (!n) {
			$badge.remove();
			$icon.removeClass(HAS_COUNT_CLASS);
			return;
		}
		if (!$badge.length) {
			$badge = $('<span class="' + BADGE_CLASS + '" aria-live="polite"></span>').appendTo($icon);
		}
		$badge.text(n > 99 ? '99+' : String(n));
		$icon.addClass(HAS_COUNT_CLASS);
		$icon.attr('title', __('Notifications') + ' (' + n + ' ' + __('unread') + ')');
	}

	function refreshCount() {
		if (!$icon || !frappe.db || !frappe.db.count) return;
		if (countInFlight) return countInFlight;
		countInFlight = frappe.db
			.count('Notification Log', {
				filters: { read: 0, for_user: frappe.session.user },
			})
			.then((n) => renderCount(n))
			.catch(() => {})
			.then(() => {
				countInFlight = null;
			});
		return countInFlight;
	}

	function observe() {
		const $unseen = $icon.find('.notifications-unseen');
		if (!$unseen.length) return;

		const sync = () => setUnseen($unseen.is(':visible'));

		if (window.MutationObserver) {
			new MutationObserver(sync).observe($unseen[0], {
				attributes: true,
				attributeFilter: ['style'],
			});
		}
		sync();
	}

	function bindEvents() {
		if (frappe.realtime && frappe.realtime.on) {
			// A brand-new notification: ring immediately even if already unseen, and recount.
			frappe.realtime.on('notification', () => {
				ring();
				refreshCount();
			});
			frappe.realtime.on('indicator_hide', refreshCount);
		}

		const $dropdown = $icon.closest('.dropdown-notifications');
		// Clicking an item or "Mark all as read" changes read state while the dropdown
		// is open; recount when it closes. Also recount on open so the badge is honest.
		$dropdown.on('shown.bs.dropdown hidden.bs.dropdown', refreshCount);
		$dropdown.on('click', '.mark-all-read', () => renderCount(0));
	}

	function init() {
		// Other apps clone the navbar <li> markup (same classes) for their own icons,
		// so pick the anchor that actually carries core's seen/unseen bell pair.
		const $el = $('.navbar .notifications-icon')
			.filter((i, el) => $(el).find('.notifications-unseen use[href="#icon-notification-with-indicator"]').length > 0)
			.first();
		if (!$el.length || $el.data('isoft-notif-attention')) return false;
		$el.data('isoft-notif-attention', true);
		$icon = $el;
		observe();
		bindEvents();
		refreshCount();
		return true;
	}

	function boot() {
		if (frappe.session.user === 'Guest') return;
		if (init()) return;
		// Fallback only: the toolbar is built synchronously before 'startup' fires.
		let tries = 0;
		const t = setInterval(() => {
			if (init() || ++tries > 20) clearInterval(t);
		}, 250);
	}

	// 'startup' fires synchronously right after the navbar is built, before first paint.
	$(document).on('startup', boot);
})();
