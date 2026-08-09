import assert from 'node:assert/strict';

import { DPR_EPSILON, dprMatches } from './site_runtime_math.mjs';

assert.equal(DPR_EPSILON, 0.01);
for (const [actual, expected] of [
  [1, 1],
  [0.9999999997, 1],
  [1.0000000003, 1],
  [1.9999999997, 2],
  [2.0000000003, 2],
  [1.995, 2],
]) {
  assert.equal(dprMatches(actual, expected), true, `${actual} should match ${expected}`);
}
for (const [actual, expected] of [
  [1.98, 2],
  [2.02, 2],
  [Number.NaN, 1],
  [Number.POSITIVE_INFINITY, 1],
]) {
  assert.equal(dprMatches(actual, expected), false, `${actual} should not match ${expected}`);
}

console.log('Site runtime DPR tolerance verified, including fractional CDP noise');
