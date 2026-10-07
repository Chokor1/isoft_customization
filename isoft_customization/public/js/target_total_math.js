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
		// Rule rounding. rule = {base, rules: [{upto, to}]}: the price is split into
		// whole blocks of `base` plus a remainder; the remainder below the first
		// matching threshold `upto` becomes `to`, above every threshold it goes up to
		// the next block. Example base 100, [{20->0}, {70->50}]: 1030 -> 1050,
		// 22390 -> 22400, 1015 -> 1000. Sign is kept (returns). No base = off.
		round_rule: function (value, rule) {
			const base = rule && Number(rule.base) || 0;
			if (!base) return value;
			const rules = (rule.rules || []).map(function (r) { return { upto: Number(r.upto) || 0, to: Number(r.to) || 0 }; })
				.sort(function (a, b) { return a.upto - b.upto; });
			const sign = value < 0 ? -1 : 1, v = Math.abs(value);
			const q = Math.floor(v / base + 1e-9);
			let r = v - q * base;
			if (r < 1e-9) r = 0;
			let to = base;
			for (let i = 0; i < rules.length; i++) { if (r < rules[i].upto - 1e-9) { to = rules[i].to; break; } }
			return sign * round(q * base + to, 6);
		},

		// Deltas from value to the `count` nearest rule landing points below and
		// above it (never below zero), ascending. Used by the residue search when
		// rounding is on, so every move lands on a valid rounded price.
		landing_deltas: function (value, rule, count) {
			const base = rule && Number(rule.base) || 0;
			if (!base) return [];
			const tos = {};
			(rule.rules || []).forEach(function (r) { tos[Number(r.to) || 0] = 1; });
			tos[base] = 1;
			const q0 = Math.floor(Math.abs(value) / base);
			const points = {};
			for (let q = Math.max(0, q0 - count - 1); q <= q0 + count + 1; q++) {
				Object.keys(tos).forEach(function (t) { points[round(q * base + Number(t), 6)] = 1; });
			}
			const sorted = Object.keys(points).map(Number).filter(function (p) { return p >= 0 && Math.abs(p - value) > 1e-9; })
				.sort(function (a, b) { return a - b; });
			const below = sorted.filter(function (p) { return p < value; }).slice(-count);
			const above = sorted.filter(function (p) { return p > value; }).slice(0, count);
			return below.concat(above).map(function (p) { return round(p - value, 6); });
		},

		// New rate for a free line at factor k: rounded to the rate precision, then
		// by the rounding rule when one is given, never negative.
		scaled_rate: function (original_rate, k, precision, rule) {
			let r = round(original_rate * k, precision);
			if (rule && Number(rule.base)) r = math.round_rule(r, rule);
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
