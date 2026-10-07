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
		// Rounds value to a multiple of step. method: 'Nearest' | 'Up' | 'Down'
		// ('Up' and 'Down' are away from / towards zero, so returns keep their sign).
		// step 0 (or none) leaves the value untouched.
		round_step: function (value, step, method) {
			step = Number(step) || 0;
			if (!step) return value;
			const sign = value < 0 ? -1 : 1;
			const q = Math.abs(value) / step + 1e-9;
			let n;
			if (method === 'Up') n = Math.ceil(q - 2e-9);
			else if (method === 'Down') n = Math.floor(q);
			else n = Math.floor(q + 0.5);
			return sign * round(n * step, 6);
		},

		// New rate for a free line at factor k: rounded to the rate precision, then
		// to the price step when one is set, never negative.
		scaled_rate: function (original_rate, k, precision, step, method) {
			let r = round(original_rate * k, precision);
			if (step) r = math.round_step(r, step, method);
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
