// Unit tests for the pure fitting helpers behind the Target Total Assistant.
// Run: node --test isoft_customization/tests/target_total_math.test.js
const test = require('node:test');
const assert = require('node:assert');
const m = require('../public/js/target_total_math.js');

test('scaled_rate rounds and clamps', () => {
	assert.equal(m.scaled_rate(123.456, 1.1, 2), 135.8);
	assert.equal(m.scaled_rate(10, -0.5, 2), 0);
});

test('secant_next moves toward the target', () => {
	// S(k) = 1000k: s0 at k0=1 is 1000, s1 at k1=1.2 is 1200, target 1500 -> k=1.5
	assert.ok(Math.abs(m.secant_next(1, 1000, 1.2, 1200, 1500) - 1.5) < 1e-12);
	assert.equal(m.secant_next(1, 1000, 1.2, 1000, 1500), 1.2); // flat: keep k1
	assert.equal(m.secant_next(1, 1000, 0.5, 500, -100), 0);    // clamp
});

test('secant converges on a non-linear S', () => {
	const S = k => 100 * k + 50 * Math.sqrt(k); // inclusive-tax-like curvature
	let k0 = 1, s0 = S(1), k1 = 2, s1 = S(2), target = 400, n = 0;
	while (!m.converged(s1, target, 0.005) && n++ < 12) {
		const k2 = m.secant_next(k0, s0, k1, s1, target);
		k0 = k1; s0 = s1; k1 = k2; s1 = S(k2);
	}
	assert.ok(m.converged(s1, target, 0.005), `not converged: ${s1}`);
});

test('largest_free picks by row index among free rows', () => {
	const rows = [{amount: 500, free: false}, {amount: 300, free: true}, {amount: 300.5, free: true}];
	assert.equal(m.largest_free(rows), 2);
	assert.equal(m.largest_free([{amount: 1, free: false}]), -1);
});

test('set_default_mode leaves Fixed rows alone', () => {
	const rows = [{mode: 'Fixed'}, {mode: 'Rate'}];
	assert.deepEqual(m.set_default_mode(rows, 'Price List Rate').map(r => r.mode), ['Fixed', 'Price List Rate']);
});
