// Pure helpers behind the Target Total Assistant (target_total_assistant.js).
//
// No Frappe dependency on purpose: the same file runs under Node for the unit
// tests in isoft_customization/tests/target_total_math.test.js. In the browser it
// attaches as isoft.target_total.math.

(function () {
	function round(x, p) {
		// Half away from zero, like frappe's flt(), without its locale handling.
		const f = Math.pow(10, p || 0);
		const v = Math.round((Math.abs(x) + Number.EPSILON) * f) / f;
		return x < 0 ? -v : v;
	}

	const math = {
		// New rate for a free line at factor k, rounded to the rate precision, never negative.
		scaled_rate: function (original_rate, k, precision) {
			const r = round(original_rate * k, precision);
			return r < 0 ? 0 : r;
		},

		// Next factor from two (k, S(k)) samples. Flat response keeps k1; never below 0.
		secant_next: function (k0, s0, k1, s1, target) {
			if (s1 === s0) return k1;
			const k = k1 + (target - s1) * (k1 - k0) / (s1 - s0);
			return k < 0 ? 0 : k;
		},

		// Index of the free row with the largest absolute amount, -1 when none is free.
		largest_free: function (lines) {
			let best = -1, best_amount = -1;
			(lines || []).forEach(function (line, i) {
				if (!line.free) return;
				const a = Math.abs(line.amount || 0);
				if (a > best_amount) { best = i; best_amount = a; }
			});
			return best;
		},

		converged: function (s, target, tol) {
			return Math.abs(s - target) <= tol;
		},

		// Every non-Fixed row takes the mode; Fixed rows (incl. typed ones) stay Fixed.
		set_default_mode: function (rows, mode) {
			return (rows || []).map(function (r) {
				return r.mode === 'Fixed' ? r : Object.assign({}, r, { mode: mode });
			});
		},

		round: round
	};

	if (typeof module !== 'undefined') module.exports = math;
	if (typeof window !== 'undefined') {
		window.isoft = window.isoft || {};
		window.isoft.target_total = window.isoft.target_total || {};
		window.isoft.target_total.math = math;
	}
})();
