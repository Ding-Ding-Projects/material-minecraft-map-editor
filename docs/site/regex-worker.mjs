const MAX_PATTERN = 256;
const MAX_SAMPLE = 512;
const MAX_RECORDS = 128;
const MAX_RECORD_BYTES = 1024 * 1024;
const ALLOWED_FLAGS = /^[dgimsuvy]*$/;

function validateRequest(request) {
  if (!request || typeof request !== 'object') throw new Error('Invalid regex request');
  const pattern = String(request.pattern || '');
  const flags = String(request.flags || '');
  const sample = String(request.sample || '');
  const records = Array.isArray(request.records) ? request.records.map(String) : [];
  if (pattern.length > MAX_PATTERN) throw new Error('Pattern is limited to 256 characters');
  if (!ALLOWED_FLAGS.test(flags) || new Set(flags).size !== flags.length) throw new Error('Unsupported regular-expression flag');
  if (sample.length > MAX_SAMPLE) throw new Error('Sample text is limited to 512 characters');
  if (records.length > MAX_RECORDS) throw new Error('Regex record count is limited to 128');
  const bytes = new TextEncoder().encode(records.join('') + sample + pattern).byteLength;
  if (bytes > MAX_RECORD_BYTES) throw new Error('Regex request is limited to 1 MiB');
  return { pattern, flags, sample, records };
}

export function evaluateRegex(request) {
  const { pattern, flags, sample, records } = validateRequest(request);
  let expression;
  try {
    expression = new RegExp(pattern || '(?!)', flags);
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
  expression.lastIndex = 0;
  const sampleMatch = pattern ? expression.exec(sample) : null;
  const sampleResult = sampleMatch
    ? {
        matched: true,
        index: sampleMatch.index,
        match: sampleMatch[0],
        captures: sampleMatch.slice(1),
      }
    : { matched: false, index: -1, match: '', captures: [] };
  const matches = records.map((record) => {
    expression.lastIndex = 0;
    return pattern ? expression.test(record) : true;
  });
  return { ok: true, matches, sample: sampleResult };
}

if (typeof globalThis.addEventListener === 'function' && typeof globalThis.postMessage === 'function') {
  globalThis.addEventListener('message', (event) => {
    const id = event.data?.id;
    try {
      globalThis.postMessage({ id, ...evaluateRegex(event.data?.request) });
    } catch (error) {
      globalThis.postMessage({ id, ok: false, error: error instanceof Error ? error.message : String(error) });
    }
  });
}
