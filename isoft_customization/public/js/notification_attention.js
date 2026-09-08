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
	// Rounded, modern bell (Material "notifications" outline, Apache-2.0), 24x24 viewBox,
	// filled with a soft gold gradient. The gradient lives inside the symbol; <use>
	// clones resolve url(#...) against the document, where the original still exists.
	const GOLD_BELL =
		'<defs><linearGradient id="isoft-bell-gold" x1="0" y1="0" x2="0" y2="1">' +
		'<stop offset="0" stop-color="#FFD966"/><stop offset="1" stop-color="#F2A81D"/>' +
		'</linearGradient></defs>' +
		'<path fill="url(#isoft-bell-gold)" d="M12 2.5c.7 0 1.3.6 1.3 1.3v.6c2.9.6 5 3.1 5 6.1v4.4l1.5 1.7c.5.6.1 1.4-.6 1.4H4.8c-.7 0-1.1-.8-.6-1.4l1.5-1.7v-4.4c0-3 2.1-5.5 5-6.1v-.6c0-.7.6-1.3 1.3-1.3z"/>' +
		'<path fill="#E29A12" d="M9.7 19h4.6a2.3 2.3 0 0 1-4.6 0z"/>';

	function goldify_symbols() {
		['icon-notification', 'icon-notification-with-indicator'].forEach((id) => {
			const sym = document.getElementById(id);
			if (sym && !sym.getAttribute('data-isoft-gold')) {
				sym.innerHTML = GOLD_BELL;
				sym.setAttribute('viewBox', '0 0 24 24');
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
