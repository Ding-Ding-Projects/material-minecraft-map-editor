import assert from 'node:assert/strict';
import { Worker } from 'node:worker_threads';
import { evaluateRegex } from '../docs/site/regex-worker.mjs';

const captures = evaluateRegex({
  pattern: '(world)', flags: 'i', sample: 'Hello world', records: ['world editing', 'chunks'],
});
assert.equal(captures.ok, true);
assert.deepEqual(captures.matches, [true, false]);
assert.deepEqual(captures.sample.captures, ['world']);

const unicode = evaluateRegex({
  pattern: '世界', flags: 'u', sample: '你好世界', records: ['Minecraft 世界', 'Minecraft world'],
});
assert.deepEqual(unicode.matches, [true, false]);

const multiline = evaluateRegex({
  pattern: '^beta$', flags: 'imu', sample: 'alpha\nBETA\ngamma', records: ['alpha\nbeta', 'alphabet'],
});
assert.equal(multiline.sample.matched, true);
assert.deepEqual(multiline.matches, [true, false]);

const zeroWidth = evaluateRegex({ pattern: '^', flags: 'u', sample: 'world', records: ['one'] });
assert.equal(zeroWidth.sample.matched, true);
assert.equal(zeroWidth.sample.match, '');
assert.equal(zeroWidth.sample.index, 0);

const invalid = evaluateRegex({ pattern: '[', flags: 'u', sample: '', records: [] });
assert.equal(invalid.ok, false);

const plainRecords = ['literal.dot', 'literalXdot'];
const plainMatches = plainRecords.map((record) => record.toLowerCase().includes('literal.dot'));
const regexMatches = evaluateRegex({ pattern: 'literal.dot', flags: 'i', sample: '', records: plainRecords }).matches;
assert.deepEqual(plainMatches, [true, false]);
assert.deepEqual(regexMatches, [true, true]);

const moduleUrl = new URL('../docs/site/regex-worker.mjs', import.meta.url).href;
const adversarial = 'a'.repeat(40000) + '!';
const declaredTimeoutMs = 900;
const workerSource = `
  import { parentPort, workerData } from 'node:worker_threads';
  import { evaluateRegex } from ${JSON.stringify(moduleUrl)};
  await new Promise((resolve) => setTimeout(resolve, workerData.startupDelayMs));
  parentPort.postMessage(evaluateRegex(workerData.request));
`;
const workerUrl = new URL(`data:text/javascript,${encodeURIComponent(workerSource)}`);

const delayedWorker = new Worker(workerUrl, {
  type: 'module',
  workerData: {
    startupDelayMs: 300,
    request: { pattern: 'world', flags: 'iu', sample: 'Hello world', records: ['world', 'chunks'] },
  },
});
const delayedResult = await Promise.race([
  new Promise((resolve, reject) => {
    delayedWorker.once('message', resolve);
    delayedWorker.once('error', reject);
  }),
  new Promise((_, reject) => setTimeout(
    () => reject(new Error('safe delayed Worker exceeded the declared timeout')),
    declaredTimeoutMs,
  )),
]);
assert.equal(delayedResult.ok, true);
assert.deepEqual(delayedResult.matches, [true, false]);
await delayedWorker.terminate();

const worker = new Worker(workerUrl, {
  type: 'module',
  workerData: {
    startupDelayMs: 0,
    request: { pattern: '(a|aa)+$', flags: '', sample: '', records: [adversarial] },
  },
});
let completed = false;
worker.once('message', () => { completed = true; });
await new Promise((resolve) => setTimeout(resolve, declaredTimeoutMs));
assert.equal(completed, false, 'adversarial expression unexpectedly completed before the hard timeout');
await worker.terminate();

console.log('Regex Worker contract verified: capture, Unicode, multiline, zero-width, invalid, plain-vs-regex, delayed safe completion, adversarial termination');
