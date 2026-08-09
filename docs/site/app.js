import {
  applyThemeRoles,
  contrastRatio,
  hexRgb,
  hslRgb,
  normaliseHex,
  rgbHex,
  rgbHsl,
} from './theme.mjs';

const EXPECTED_RELEASE_ORIGIN = 'https://github.com';
const EXPECTED_RELEASE_REPOSITORY = '/Ding-Ding-Projects/material-minecraft-map-editor';
const EXPECTED_PHOTO_REPOSITORY = '/Ding-Ding-Projects/dim-sum-photos';
const localizationResponse = await fetch(new URL('./i18n.json', import.meta.url), { cache: 'no-store' });
if (!localizationResponse.ok) throw new Error('Localization resources are unavailable');
const localization = await localizationResponse.json();
if (localization?.schemaVersion !== 1 || !localization.messages || !localization.toneSuffixes) {
  throw new Error('Localization resources are invalid');
}
const searchInventoryResponse = await fetch(new URL('./search-surfaces.json', import.meta.url), { cache: 'no-store' });
if (!searchInventoryResponse.ok) throw new Error('Search surface inventory is unavailable');
const searchInventory = await searchInventoryResponse.json();
if (searchInventory?.schemaVersion !== 1 || !Array.isArray(searchInventory.surfaces)) {
  throw new Error('Search surface inventory is invalid');
}
const messages = localization.messages;
const localizedBindings = [];
const localizedAttributeBindings = [];
const localizedOptionBindings = [];
let commandPalette = null;
let paletteSearchController = null;
let activeLocalization = { mode: 'english', funnyEn: 1, funnyYue: 1 };
const searchControllers = new Map();

const query = (selector, root = document) => root.querySelector(selector);
const queryAll = (selector, root = document) => [...root.querySelectorAll(selector)];
const tabs = queryAll('.nav-tab');
const pages = queryAll('.page-section');

function formatMessage(template, values = {}, language = 'en') {
  return String(template).replace(/\{([A-Za-z][A-Za-z0-9]*)\}/g, (_match, name) => {
    const value = values[name];
    if (value && typeof value === 'object') return String(value[language] ?? value.en ?? `{${name}}`);
    return String(value ?? `{${name}}`);
  });
}

function messageFor(key, language, values = {}) {
  const template = language === 'zh-Hant' ? messages[key] : key;
  return formatMessage(typeof template === 'string' ? template : key, values, language);
}

function toneMessage(value, sourceKey, language, level) {
  if (!/[.!?…]$/.test(sourceKey) || sourceKey.length < 20) return value;
  const suffixes = localization.toneSuffixes[language] || [];
  return `${value}${suffixes[Math.max(0, Math.min(4, Number(level || 1) - 1))] || ''}`;
}

function refreshLocalizedBinding(binding, funnyEn = 1, funnyYue = 1) {
  binding.english.textContent = toneMessage(messageFor(binding.key, 'en', binding.values), binding.key, 'en', funnyEn);
  binding.cantonese.textContent = toneMessage(messageFor(binding.key, 'zh-Hant', binding.values), binding.key, 'zh-Hant', funnyYue);
}

function createLocalizedCopy(key, values = {}) {
  const wrapper = document.createElement('span');
  wrapper.className = 'localized-copy';
  wrapper.dataset.i18nKey = key;
  const english = document.createElement('span');
  english.lang = 'en';
  const cantonese = document.createElement('span');
  cantonese.lang = 'zh-Hant';
  wrapper.append(english, cantonese);
  const binding = { wrapper, english, cantonese, key, values };
  localizedBindings.push(binding);
  refreshLocalizedBinding(binding, activeLocalization.funnyEn, activeLocalization.funnyYue);
  return wrapper;
}

function setLocalizedContent(element, key, values = {}) {
  if (!element) return;
  element.replaceChildren(createLocalizedCopy(key, values));
}

function localizedArticleValue(value, language) {
  if (!value || typeof value !== 'object') return '';
  return String(value[language] || '');
}

function createArticleLocalizedCopy(value) {
  const wrapper = document.createElement('span');
  wrapper.className = 'localized-copy article-localized-copy';
  for (const language of ['en', 'zh-Hant']) {
    const node = document.createElement('span');
    node.lang = language;
    node.textContent = localizedArticleValue(value, language);
    wrapper.append(node);
  }
  return wrapper;
}

function localizedString(key, mode, values = {}) {
  const english = messageFor(key, 'en', values);
  const cantonese = messageFor(key, 'zh-Hant', values);
  if (mode === 'bilingual') return `${english} / ${cantonese}`;
  return mode === 'cantonese' ? cantonese : english;
}

function setLocalizedAttribute(element, attribute, key, values = {}) {
  if (!element) return;
  localizedAttributeBindings.push({ element, attribute, key, values });
  element.setAttribute(attribute, localizedString(key, activeLocalization.mode, values));
}

function installStaticLocalization() {
  const excluded = new Set(['CODE', 'KBD', 'OPTION', 'SCRIPT', 'STYLE']);
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach((node) => {
    const parent = node.parentElement;
    const key = node.nodeValue?.trim();
    if (!parent || !key || excluded.has(parent.tagName) || parent.closest('[aria-hidden="true"]')) return;
    if (!Object.prototype.hasOwnProperty.call(messages, key)) return;
    const before = node.nodeValue.match(/^\s*/)?.[0] || '';
    const after = node.nodeValue.match(/\s*$/)?.[0] || '';
    node.replaceWith(document.createTextNode(before), createLocalizedCopy(key), document.createTextNode(after));
  });

  ['aria-label', 'placeholder', 'title'].forEach((attribute) => {
    queryAll(`[${attribute}]`).forEach((element) => {
      const key = element.getAttribute(attribute);
      if (key && Object.prototype.hasOwnProperty.call(messages, key)) localizedAttributeBindings.push({ element, attribute, key, values: {} });
    });
  });
  queryAll('option').forEach((option) => {
    const key = option.textContent.trim();
    if (Object.prototype.hasOwnProperty.call(messages, key)) localizedOptionBindings.push({ option, key });
  });
}

installStaticLocalization();

function showTab(name, { updateHash = true, focus = true } = {}) {
  if (!tabs.some((tab) => tab.dataset.tab === name)) return;
  tabs.forEach((tab) => {
    const active = tab.dataset.tab === name;
    tab.classList.toggle('is-active', active);
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
  });
  pages.forEach((page) => {
    const active = page.dataset.page === name;
    page.hidden = !active;
    page.classList.toggle('is-visible', active);
  });
  searchControllers.forEach((controller) => {
    const page = controller.search.closest('.page-section')?.dataset.page;
    if (page && page !== name) controller.cancel();
    if (page === name) controller.apply({ immediate: true });
  });
  if (updateHash) history.replaceState(null, '', `#${name}`);
  if (focus) query(`#${CSS.escape(name)}`)?.focus({ preventScroll: true });
}

tabs.forEach((tab, index) => {
  tab.addEventListener('click', () => showTab(tab.dataset.tab));
  tab.addEventListener('keydown', (event) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    let next = index;
    if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = tabs.length - 1;
    tabs[next].focus();
    showTab(tabs[next].dataset.tab, { focus: false });
  });
});

queryAll('[data-tab-link]').forEach((control) => {
  control.addEventListener('click', (event) => {
    if (!control.dataset.tabLink) return;
    event.preventDefault();
    showTab(control.dataset.tabLink);
  });
});

function safePublicationUrl(value, releaseTag, assetName) {
  try {
    const url = new URL(value);
    if (url.origin !== EXPECTED_RELEASE_ORIGIN || url.username || url.password || url.search || url.hash) return null;
    const expectedPath = `${EXPECTED_RELEASE_REPOSITORY}/releases/download/${releaseTag}/${assetName}`;
    if (url.pathname !== expectedPath) return null;
    return url.href;
  } catch (_error) {
    return null;
  }
}

function safePhotoUrl(value) {
  try {
    const url = new URL(value);
    if (url.origin !== EXPECTED_RELEASE_ORIGIN || url.username || url.password || url.search || url.hash) return null;
    if (!url.pathname.startsWith(`${EXPECTED_PHOTO_REPOSITORY}/releases/download/catalog-v1`) || !url.pathname.endsWith('.png')) return null;
    return url.href;
  } catch (_error) {
    return null;
  }
}

function verifiedManifest(manifest) {
  if (manifest?.schemaVersion !== 1 || manifest.verified !== true || !/^[0-9a-f]{40}$/i.test(String(manifest.commit || ''))) return false;
  const tag = String(manifest.releaseTag || '');
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(tag)) return false;
  if (manifest.releaseUrl !== `${EXPECTED_RELEASE_ORIGIN}${EXPECTED_RELEASE_REPOSITORY}/releases/tag/${tag}`) return false;
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(String(manifest.publishedAt || ''))) return false;
  if (!String(manifest.codeName?.en || '').trim() || !String(manifest.codeName?.zhHant || '').trim()) return false;
  if (!safePhotoUrl(manifest.codeName?.photoUrl)) return false;
  if (typeof manifest.delta?.emitted !== 'boolean' || !String(manifest.delta?.reason || '').trim()) return false;
  return ['Setup.exe', 'RELEASES', 'full.nupkg'].every((key) => {
    const asset = manifest.assets?.[key];
    if (!asset || typeof asset.sha256 !== 'string' || !/^[0-9a-f]{64}$/i.test(asset.sha256)) return false;
    if (!Number.isSafeInteger(asset.bytes) || asset.bytes <= 0) return false;
    const name = key === 'full.nupkg' ? String(asset.name || '') : key;
    if (key === 'full.nupkg') return name.endsWith('-full.nupkg') && safePublicationUrl(asset.url, tag, name) !== null;
    return asset.name === key && safePublicationUrl(asset.url, tag, key) !== null;
  });
}

async function loadSiteConfig() {
  const response = await fetch(new URL('site-config.json', document.baseURI), { cache: 'no-store' });
  if (!response.ok) throw new Error('Site configuration is unavailable');
  const config = await response.json();
  if (config?.schemaVersion !== 1) throw new Error('Unsupported site configuration');
  const base = new URL(config.baseUrl || './', document.baseURI);
  document.documentElement.dataset.baseUrl = base.href;
  return { ...config, base };
}

async function loadPublicationManifest(config) {
  const releaseDownload = query('#release-download');
  try {
    const manifestUrl = new URL(config.releaseManifest || './release-manifest.json', config.base);
    const response = await fetch(manifestUrl, { cache: 'no-store' });
    if (!response.ok) throw new Error('Release manifest is unavailable');
    const manifest = await response.json();
    if (!verifiedManifest(manifest)) throw new Error('Release assets are not verified');
    const tag = String(manifest.releaseTag || '');
    const asset = manifest.assets['Setup.exe'];
    const url = safePublicationUrl(asset.url, tag, 'Setup.exe');
    if (!url) throw new Error('Setup.exe is not immutable');
    setLocalizedContent(query('#release-eyebrow'), 'VERIFIED WINDOWS BUILD · {tag}', { tag });
    setLocalizedContent(query('#release-title'), 'Install the verified unsigned Squirrel package');
    setLocalizedContent(query('#release-copy'), 'This immutable unsigned Squirrel.Windows installer is backed by the verified tag, commit, asset path, byte size, and SHA-256 release manifest. Windows may show an unknown-publisher warning because signing is intentionally disabled.');
    const codeName = manifest.codeName?.en && manifest.codeName?.zhHant
      ? `${manifest.codeName.en} · ${manifest.codeName.zhHant}`
      : '';
    const codeNameElement = query('#release-code-name');
    const codeNameLink = query('#release-code-name-link');
    const photoUrl = safePhotoUrl(manifest.codeName?.photoUrl);
    if (codeName && photoUrl) {
      setLocalizedContent(codeNameLink, 'Release code name: {codeName}', { codeName });
      codeNameLink.href = photoUrl;
      codeNameElement.hidden = false;
    } else {
      codeNameElement.hidden = true;
      codeNameLink.removeAttribute('href');
    }
    releaseDownload.hidden = false;
    releaseDownload.href = url;
    releaseDownload.removeAttribute('data-tab-link');
    releaseDownload.target = '_blank';
    releaseDownload.rel = 'noreferrer';
    setLocalizedContent(releaseDownload, 'Download Setup.exe · {tag} · Windows x64 ↗', { tag });
  } catch (_error) {
    releaseDownload.hidden = true;
    query('#release-code-name').hidden = true;
    query('#release-code-name-link').removeAttribute('href');
  }
}

function escapeRegexLiteral(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

const REGEX_WORKER_TIMEOUT_MS = 900;

class SafeRegexWorker {
  constructor() {
    this.worker = null;
    this.resolvePending = null;
  }

  cancel() {
    if (this.worker) this.worker.terminate();
    this.worker = null;
    if (this.resolvePending) this.resolvePending({ cancelled: true });
    this.resolvePending = null;
  }

  evaluate(request) {
    this.cancel();
    const worker = new Worker(new URL('./regex-worker.mjs', import.meta.url), { type: 'module' });
    this.worker = worker;
    return new Promise((resolve) => {
      this.resolvePending = resolve;
      const finish = (result) => {
        if (this.worker !== worker) return;
        clearTimeout(timer);
        worker.terminate();
        this.worker = null;
        this.resolvePending = null;
        resolve(result);
      };
      const timer = setTimeout(
        () => finish({ timeout: true }),
        REGEX_WORKER_TIMEOUT_MS,
      );
      worker.addEventListener('message', (event) => finish(event.data), { once: true });
      worker.addEventListener('error', () => finish({ workerError: true }), { once: true });
      worker.postMessage({ id: 1, request });
    });
  }
}

function createBuilderButton(label, accessibleLabel, snippet, pattern, search, toggle) {
  const button = document.createElement('button');
  button.type = 'button';
  setLocalizedContent(button, label);
  setLocalizedAttribute(button, 'aria-label', accessibleLabel);
  button.addEventListener('click', () => {
    const start = pattern.selectionStart ?? pattern.value.length;
    const end = pattern.selectionEnd ?? start;
    const selected = pattern.value.slice(start, end);
    const value = typeof snippet === 'function' ? snippet(selected) : snippet;
    pattern.setRangeText(value, start, end, 'end');
    search.value = pattern.value;
    toggle.checked = true;
    pattern.dispatchEvent(new Event('input', { bubbles: true }));
    pattern.focus();
  });
  return button;
}

function upgradeRegexBuilder({ surface, search, pattern, toggle, feedback }) {
  const details = query(`#${CSS.escape(surface.builderId)}`);
  const controls = query('.regex-controls', details);
  if (!details || !controls) throw new Error(`Missing regex builder for ${surface.name}`);
  const guide = document.createElement('div');
  guide.className = 'regex-guide';
  const title = document.createElement('span');
  title.className = 'regex-guide-title';
  setLocalizedContent(title, 'Guided building blocks');
  guide.append(
    title,
    createBuilderButton('Literal', 'Insert literal', (selected) => escapeRegexLiteral(selected || 'text'), pattern, search, toggle),
    createBuilderButton('Character class', 'Insert character class', '[A-Za-z0-9_]', pattern, search, toggle),
    createBuilderButton('Anchors', 'Insert start and end anchors', '^$', pattern, search, toggle),
    createBuilderButton('Group', 'Insert capture group', (selected) => `(${selected || 'text'})`, pattern, search, toggle),
    createBuilderButton('Alternation', 'Insert alternation', (selected) => selected ? `${selected}|other` : 'one|two', pattern, search, toggle),
    createBuilderButton('Quantifier', 'Insert bounded quantifier', '{1,3}', pattern, search, toggle),
  );
  const actions = document.createElement('div');
  actions.className = 'regex-actions';
  const copy = document.createElement('button');
  copy.type = 'button';
  setLocalizedContent(copy, 'Copy pattern');
  copy.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(`/${pattern.value}/${query(`#${CSS.escape(surface.flagsId)}`).value}`);
      setLocalizedContent(feedback, 'Pattern copied');
    } catch (_error) {
      setLocalizedContent(feedback, 'Clipboard is unavailable');
    }
  });
  const exportButton = document.createElement('button');
  exportButton.type = 'button';
  setLocalizedContent(exportButton, 'Export pattern');
  exportButton.addEventListener('click', () => {
    const payload = JSON.stringify({ schemaVersion: 1, engine: 'JavaScript RegExp', pattern: pattern.value, flags: query(`#${CSS.escape(surface.flagsId)}`).value }, null, 2);
    const url = URL.createObjectURL(new Blob([`${payload}\n`], { type: 'application/json' }));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `amulet-${surface.name}-regex.json`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
    setLocalizedContent(feedback, 'Pattern export downloaded');
  });
  actions.append(copy, exportButton);
  controls.prepend(guide);
  controls.append(actions);
  details.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    details.open = false;
    search.focus();
  });
  let wasOpen = details.open;
  details.addEventListener('toggle', () => {
    if (wasOpen && !details.open) queueMicrotask(() => search.focus());
    wasOpen = details.open;
  });
}

function wireSearch({ search, pattern, toggle, flags, sample, feedback, captures, records, text, empty, onMatches }) {
  const surface = searchInventory.surfaces.find((entry) => entry.searchId === search?.id);
  if (!surface) throw new Error(`Search field ${search?.id || 'unknown'} is absent from the hand-written inventory`);
  for (const id of [surface.builderId, surface.toggleId, surface.patternId, surface.flagsId, surface.sampleId, surface.feedbackId, surface.capturesId]) {
    if (!query(`#${CSS.escape(id)}`)) throw new Error(`Search inventory target is missing: ${id}`);
  }
  const regexWorker = new SafeRegexWorker();
  let generation = 0;
  let debounce = null;
  const applyMatches = (sourceRecords, matches) => {
    const matched = sourceRecords.filter((_record, index) => matches[index]);
    if (onMatches) onMatches(matched);
    else sourceRecords.forEach((record, index) => { record.hidden = !matches[index]; });
    if (empty) empty.hidden = matched.length !== 0;
    return matched.length;
  };
  const updateSample = (sampleResult) => {
    if (!captures) return;
    if (!sampleResult?.matched) setLocalizedContent(captures, 'Sample does not match');
    else if (sampleResult.match === '') setLocalizedContent(captures, 'Sample matched with zero-width result at {index}', { index: sampleResult.index });
    else if (sampleResult.captures?.length) setLocalizedContent(captures, 'Captures: {captures}', { captures: sampleResult.captures.join(' · ') });
    else setLocalizedContent(captures, 'Sample match at {index}: {match}', { index: sampleResult.index, match: sampleResult.match });
  };
  const apply = ({ immediate = false } = {}) => {
    generation += 1;
    const currentGeneration = generation;
    if (debounce) clearTimeout(debounce);
    regexWorker.cancel();
    const sourceRecords = records();
    const raw = String(search?.value || '');
    if (!toggle?.checked) {
      const needle = raw.toLocaleLowerCase();
      const matches = sourceRecords.map((record) => !needle || String(text(record)).toLocaleLowerCase().includes(needle));
      const count = applyMatches(sourceRecords, matches);
      setLocalizedContent(feedback, 'Plain-text mode');
      const sampleText = String(sample?.value || '');
      const index = needle ? sampleText.toLocaleLowerCase().indexOf(needle) : 0;
      updateSample(index >= 0 ? { matched: true, index, match: needle ? sampleText.slice(index, index + raw.length) : '', captures: [] } : { matched: false });
      return Promise.resolve(count);
    }
    const run = async () => {
      const result = await regexWorker.evaluate({ pattern: raw, flags: flags?.value || 'i', sample: sample?.value || '', records: sourceRecords.map(text) });
      if (currentGeneration !== generation || result.cancelled) return 0;
      if (result.timeout) {
        setLocalizedContent(feedback, 'Regex evaluation timed out; the worker was stopped and no stale result was applied.');
        return 0;
      }
      if (result.workerError) {
        setLocalizedContent(feedback, 'Regex worker failed; no search result was changed.');
        return 0;
      }
      if (!result.ok) {
        setLocalizedContent(feedback, 'Invalid pattern: {message}', { message: result.error || 'Invalid JavaScript regular expression' });
        return 0;
      }
      const count = applyMatches(sourceRecords, result.matches);
      setLocalizedContent(feedback, 'Live matches: {count}', { count });
      updateSample(result.sample);
      return count;
    };
    if (immediate) return run();
    return new Promise((resolve) => {
      debounce = setTimeout(() => { debounce = null; run().then(resolve); }, 120);
    });
  };
  const controller = {
    search,
    surface,
    apply,
    cancel() {
      generation += 1;
      if (debounce) clearTimeout(debounce);
      debounce = null;
      regexWorker.cancel();
    },
  };
  upgradeRegexBuilder({ surface, search, pattern, toggle, feedback });
  search.addEventListener('input', () => { pattern.value = search.value; apply(); });
  pattern.addEventListener('input', () => { search.value = pattern.value; apply(); });
  toggle.addEventListener('change', () => { pattern.value = search.value; apply({ immediate: true }); });
  flags.addEventListener('change', () => apply({ immediate: true }));
  sample.addEventListener('input', () => apply());
  searchControllers.set(surface.name, controller);
  if (searchControllers.size === searchInventory.surfaces.length) {
    document.documentElement.dataset.searchInventoryReady = 'true';
  }
  apply({ immediate: true });
  return controller;
}

const featureSearch = query('#feature-search');
const featurePattern = query('#feature-pattern');
const featureToggle = query('#feature-regex');
const featureFlags = query('#feature-flags');
const featureFeedback = query('#regex-feedback');
const featureCaptures = query('#regex-captures');
const featureSample = query('#feature-sample');
wireSearch({
  search: featureSearch,
  pattern: featurePattern,
  toggle: featureToggle,
  flags: featureFlags,
  sample: featureSample,
  feedback: featureFeedback,
  captures: featureCaptures,
  records: () => queryAll('#feature-grid .feature-card'),
  text: (card) => `${card.dataset.search || ''} ${card.textContent}`,
  empty: query('#feature-empty'),
});

const settings = {
  language: query('#site-language'),
  funnyEn: query('#funny-en'),
  funnyYue: query('#funny-yue'),
  theme: query('#site-theme'),
  density: query('#site-density'),
  accent: query('#site-accent'),
  accentHex: query('#site-accent-hex'),
  accentRgb: query('#site-accent-rgb'),
  accentHsl: query('#site-accent-hsl'),
  accentHue: query('#site-accent-hue'),
  font: query('#site-font'),
  scale: query('#site-scale'),
};
const settingsKey = 'amulet-site-settings-v2';
function applyLanguage(language, funnyEn = 1, funnyYue = 1) {
  const mode = ['english', 'cantonese', 'bilingual'].includes(language) ? language : 'english';
  activeLocalization = { mode, funnyEn, funnyYue };
  document.documentElement.lang = mode === 'cantonese' ? 'zh-Hant' : 'en';
  document.documentElement.dataset.language = mode;
  localizedBindings.forEach((binding) => {
    if (binding.wrapper.isConnected) refreshLocalizedBinding(binding, funnyEn, funnyYue);
  });
  localizedAttributeBindings.forEach(({ element, attribute, key, values }) => {
    if (element.isConnected) element.setAttribute(attribute, localizedString(key, mode, values));
  });
  localizedOptionBindings.forEach(({ option, key }) => {
    option.textContent = localizedString(key, mode);
  });
  document.title = localizedString('Amulet Map Editor · World editing, made clear', mode);
  query('meta[name="description"]')?.setAttribute('content', localizedString('Amulet Map Editor — an open-source Minecraft world editor.', mode));
  if (commandPalette?.open) paletteSearchController?.apply({ immediate: true });
}

function parseRgb(value) {
  const match = String(value || '').match(/^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)$/i);
  if (!match) return null;
  const channels = match.slice(1, 4).map(Number);
  return channels.every((channel) => channel <= 255) ? channels : null;
}

function parseHsl(value) {
  const match = String(value || '').match(/^hsla?\(\s*(\d{1,3})\s*,\s*(\d{1,3})%\s*,\s*(\d{1,3})%\s*\)$/i);
  if (!match) return null;
  const channels = match.slice(1, 4).map(Number);
  return channels.every((channel, index) => channel <= (index ? 100 : 360)) ? channels : null;
}

function syncAccentFields(hex) {
  const rgb = hexRgb(hex);
  const hsl = rgbHsl(rgb);
  if (settings.accent && settings.accent.value !== hex) settings.accent.value = hex;
  if (settings.accentHex) settings.accentHex.value = hex;
  if (settings.accentRgb) settings.accentRgb.value = `rgb(${rgb.join(', ')})`;
  if (settings.accentHsl) settings.accentHsl.value = `hsl(${hsl[0]}, ${hsl[1]}%, ${hsl[2]}%)`;
  if (settings.accentHue) settings.accentHue.value = String(hsl[0]);
  query('#site-accent-hue-value')?.replaceChildren(`${hsl[0]}°`);
}

function applySettings({ persist = true } = {}) {
  const accent = normaliseHex(settings.accentHex?.value) || normaliseHex(settings.accent?.value) || '#4d5f92';
  const value = {
    language: settings.language?.value || 'english',
    funnyEn: Number(settings.funnyEn?.value || 1),
    funnyYue: Number(settings.funnyYue?.value || 1),
    theme: settings.theme?.value || 'light',
    density: settings.density?.value || 'comfortable',
    accent,
    font: settings.font?.value || 'system-ui',
    scale: Number(settings.scale?.value || 100),
  };
  syncAccentFields(value.accent);
  document.documentElement.classList.toggle('dark', value.theme === 'dark');
  document.documentElement.dataset.density = value.density;
  document.documentElement.style.setProperty('--seed', value.accent);
  document.documentElement.style.setProperty('--ui-scale', String(value.scale / 100));
  document.documentElement.style.setProperty('--site-font', value.font);
  const roles = applyThemeRoles(document.documentElement, value.accent, value.theme);
  const primarySurface = contrastRatio(roles.primary, roles.surface).toFixed(2);
  const onPrimary = contrastRatio(roles.onPrimary, roles.primary).toFixed(2);
  setLocalizedContent(query('#accent-contrast'), 'Derived primary/surface: {primary}:1 · On-primary/primary: {onPrimary}:1', { primary: primarySurface, onPrimary });
  query('#site-scale-value')?.replaceChildren(`${value.scale}%`);
  query('#funny-en-value')?.replaceChildren(String(value.funnyEn));
  query('#funny-yue-value')?.replaceChildren(String(value.funnyYue));
  applyLanguage(value.language, value.funnyEn, value.funnyYue);
  if (persist) {
    try { localStorage.setItem(settingsKey, JSON.stringify(value)); } catch (_error) { /* Browser storage may be unavailable. */ }
  }
  return value;
}

function loadSettings() {
  try {
    const saved = JSON.parse(localStorage.getItem(settingsKey) || 'null');
    if (saved && typeof saved === 'object') {
      Object.entries(settings).forEach(([key, control]) => {
        if (control && saved[key] !== undefined) control.value = String(saved[key]);
      });
      const savedAccent = normaliseHex(saved.accent);
      if (savedAccent && settings.accentHex) settings.accentHex.value = savedAccent;
    }
  } catch (_error) { /* Invalid browser state falls back to shipped values. */ }
  applySettings({ persist: false });
}

settings.accentHex?.addEventListener('input', () => { if (normaliseHex(settings.accentHex.value)) applySettings(); });
settings.accent?.addEventListener('input', () => {
  settings.accentHex.value = settings.accent.value;
  applySettings();
});
settings.accentRgb?.addEventListener('change', () => {
  const rgb = parseRgb(settings.accentRgb.value);
  if (rgb) { settings.accentHex.value = rgbHex(rgb); applySettings(); }
});
settings.accentHsl?.addEventListener('change', () => {
  const hsl = parseHsl(settings.accentHsl.value);
  if (hsl) { settings.accentHex.value = rgbHex(hslRgb(hsl)); applySettings(); }
});
settings.accentHue?.addEventListener('input', () => {
  const current = rgbHsl(hexRgb(normaliseHex(settings.accentHex.value) || '#4d5f92'));
  current[0] = Number(settings.accentHue.value);
  settings.accentHex.value = rgbHex(hslRgb(current));
  applySettings();
});

Object.values(settings).forEach((control) => {
  if (control && ![settings.accent, settings.accentHex, settings.accentRgb, settings.accentHsl, settings.accentHue].includes(control)) {
    control.addEventListener('input', applySettings);
  }
  control?.addEventListener('change', applySettings);
});

query('#reset-site-settings')?.addEventListener('click', () => {
  const shipped = { language: 'english', funnyEn: '1', funnyYue: '1', theme: 'light', density: 'comfortable', accent: '#4d5f92', accentHex: '#4d5f92', font: 'system-ui', scale: '100' };
  Object.entries(shipped).forEach(([key, value]) => { if (settings[key]) settings[key].value = value; });
  applySettings();
});
loadSettings();

wireSearch({
  search: query('#settings-search'),
  pattern: query('#settings-pattern'),
  toggle: query('#settings-regex'),
  flags: query('#settings-flags'),
  sample: query('#settings-sample'),
  feedback: query('#settings-feedback'),
  captures: query('#settings-captures'),
  records: () => queryAll('#settings-grid .setting-card'),
  text: (card) => `${card.dataset.search || ''} ${card.textContent}`,
  empty: query('#settings-empty'),
});

let articles = [];
let articleBySlug = new Map();
let currentArticle = null;
let filterArticles = null;

function articleSlugFromHref(href) {
  const path = String(href || '').split('#', 1)[0];
  const match = path.match(/(?:^|\/)([a-z0-9-]+)\/README\.md$/i);
  return match && articleBySlug.has(match[1]) ? match[1] : null;
}

function appendInline(parent, source) {
  const token = /(\[([^\]]+)\]\(([^)]+)\)|`([^`]+)`|\*\*([^*]+)\*\*)/g;
  let cursor = 0;
  let match;
  while ((match = token.exec(source)) !== null) {
    if (match.index > cursor) parent.append(document.createTextNode(source.slice(cursor, match.index)));
    if (match[4] !== undefined) {
      const code = document.createElement('code');
      code.textContent = match[4];
      parent.append(code);
    } else if (match[5] !== undefined) {
      const strong = document.createElement('strong');
      strong.textContent = match[5];
      parent.append(strong);
    } else {
      const label = match[2];
      const href = match[3];
      const slug = articleSlugFromHref(href);
      if (slug) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'inline-link';
        button.textContent = label;
        button.addEventListener('click', () => openArticle(slug));
        parent.append(button);
      } else if (/^https:\/\//i.test(href)) {
        const anchor = document.createElement('a');
        anchor.href = href;
        anchor.target = '_blank';
        anchor.rel = 'noreferrer';
        anchor.textContent = label;
        parent.append(anchor);
      } else if (href.startsWith('#')) {
        const anchor = document.createElement('a');
        anchor.href = href;
        anchor.textContent = label;
        parent.append(anchor);
      } else {
        const reference = document.createElement('span');
        reference.textContent = `${label} (${href})`;
        reference.title = 'This repository-only reference is preserved as text in the static documentation bundle.';
        parent.append(reference);
      }
    }
    cursor = token.lastIndex;
  }
  if (cursor < source.length) parent.append(document.createTextNode(source.slice(cursor)));
}

function renderMarkdown(markdown, target, { skipTitle = false, idPrefix = 'article' } = {}) {
  target.replaceChildren();
  const lines = String(markdown || '').split(/\r?\n/);
  let paragraph = [];
  let list = null;
  let fence = null;
  let fenceLanguage = '';
  let headingIndex = 0;

  const flushParagraph = () => {
    if (!paragraph.length) return;
    const element = document.createElement('p');
    appendInline(element, paragraph.join(' '));
    target.append(element);
    paragraph = [];
  };
  const flushList = () => { list = null; };
  const flushFence = () => {
    if (!fence) return;
    const pre = document.createElement('pre');
    const code = document.createElement('code');
    if (fenceLanguage) code.dataset.language = fenceLanguage;
    code.textContent = fence.join('\n');
    pre.append(code);
    target.append(pre);
    fence = null;
    fenceLanguage = '';
  };

  lines.forEach((rawLine) => {
    if (rawLine.startsWith('```')) {
      flushParagraph();
      flushList();
      if (fence) flushFence();
      else { fence = []; fenceLanguage = rawLine.slice(3).trim(); }
      return;
    }
    if (fence) { fence.push(rawLine); return; }
    const heading = rawLine.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      flushList();
      const element = document.createElement(`h${heading[1].length}`);
      const label = heading[2].trim();
      if (skipTitle && heading[1].length === 1) return;
      headingIndex += 1;
      const headingSlug = label.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'heading';
      element.id = `${idPrefix}-${headingIndex}-${headingSlug}`;
      appendInline(element, label);
      target.append(element);
      return;
    }
    const unordered = rawLine.match(/^\s*[-*]\s+(.+)$/);
    const ordered = rawLine.match(/^\s*\d+\.\s+(.+)$/);
    if (unordered || ordered) {
      flushParagraph();
      const tag = ordered ? 'ol' : 'ul';
      if (!list || list.tagName.toLowerCase() !== tag) {
        list = document.createElement(tag);
        target.append(list);
      }
      const item = document.createElement('li');
      appendInline(item, (unordered || ordered)[1]);
      list.append(item);
      return;
    }
    if (!rawLine.trim()) {
      flushParagraph();
      flushList();
      return;
    }
    if (rawLine.startsWith('> ')) {
      flushParagraph();
      flushList();
      const quote = document.createElement('blockquote');
      appendInline(quote, rawLine.slice(2));
      target.append(quote);
      return;
    }
    paragraph.push(rawLine.trim());
  });
  flushParagraph();
  flushFence();
}

function validateArticleCatalog(catalog) {
  if (catalog?.schemaVersion !== 2 || !Array.isArray(catalog.articles) || catalog.articleCount !== catalog.articles.length) throw new Error('Invalid article catalog');
  const slugs = new Set(catalog.articles.map((article) => article.slug));
  catalog.articles.forEach((article) => {
    const localizedFields = ['title', 'summary', 'markdown'];
    if (!/^[a-z0-9-]{1,80}$/.test(article.slug) || localizedFields.some((field) => !article[field] || typeof article[field].en !== 'string' || typeof article[field]['zh-Hant'] !== 'string')) throw new Error('Invalid article record');
    if (!/^docs\/features\/[a-z0-9-]+\/README\.md$/.test(article.sourcePath) || !/^[0-9a-f]{64}$/.test(article.sha256) || !/^docs\/site\/locales\/zh-Hant\/articles\/[a-z0-9-]+\.md$/.test(article.translationPath) || !/^[0-9a-f]{64}$/.test(article.translationSha256)) throw new Error('Invalid article provenance');
    if (!Array.isArray(article.suggested) || article.suggested.length < 2 || article.suggested.some((slug) => !slugs.has(slug) || slug === article.slug)) throw new Error('Invalid suggested-article navigation');
  });
  return catalog.articles;
}

function renderArticleCards() {
  const cards = articles.map((article) => {
    const card = document.createElement('article');
    card.className = 'article-card';
    card.dataset.search = `${article.title.en} ${article.title['zh-Hant']} ${article.summary.en} ${article.summary['zh-Hant']} ${article.markdown.en} ${article.markdown['zh-Hant']}`;
    const eyebrow = document.createElement('span');
    eyebrow.className = 'eyebrow';
    setLocalizedContent(eyebrow, 'FEATURE ARTICLE');
    const title = document.createElement('h2');
    title.append(createArticleLocalizedCopy(article.title));
    const summary = document.createElement('p');
    summary.append(createArticleLocalizedCopy(article.summary));
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'inline-link';
    setLocalizedContent(button, 'Read on this site →');
    setLocalizedAttribute(button, 'aria-label', 'Open article: {title}', { title: article.title });
    button.dataset.article = article.slug;
    button.addEventListener('click', () => openArticle(article.slug));
    card.append(eyebrow, title, summary, button);
    return card;
  });
  query('#article-grid').replaceChildren(...cards);
}

function openArticle(slug, { updateHash = true, focus = true } = {}) {
  const article = articleBySlug.get(slug);
  if (!article) return false;
  currentArticle = article;
  showTab('docs', { updateHash: false, focus: false });
  query('#docs-heading').hidden = true;
  query('#article-grid').hidden = true;
  query('#docs-empty').hidden = true;
  query('#article-status').hidden = true;
  const view = query('#article-view');
  view.hidden = false;
  setLocalizedContent(query('#article-source'), 'Reviewed English and Cantonese sources · {source} · SHA-256 {digest}…', { source: article.sourcePath, digest: article.sha256.slice(0, 12) });
  query('#article-title').replaceChildren(createArticleLocalizedCopy(article.title));
  const articleContent = query('#article-content');
  const englishBody = document.createElement('section');
  englishBody.className = 'article-language-copy';
  englishBody.lang = 'en';
  const cantoneseBody = document.createElement('section');
  cantoneseBody.className = 'article-language-copy';
  cantoneseBody.lang = 'zh-Hant';
  renderMarkdown(article.markdown.en, englishBody, { skipTitle: true, idPrefix: `article-en-${article.slug}` });
  renderMarkdown(article.markdown['zh-Hant'], cantoneseBody, { skipTitle: true, idPrefix: `article-zh-${article.slug}` });
  articleContent.replaceChildren(englishBody, cantoneseBody);
  const suggestions = article.suggested.map((suggestedSlug) => {
    const suggested = articleBySlug.get(suggestedSlug);
    const button = document.createElement('button');
    button.type = 'button';
    button.append(createArticleLocalizedCopy(suggested.title));
    setLocalizedAttribute(button, 'aria-label', 'Open article: {title}', { title: suggested.title });
    button.addEventListener('click', () => openArticle(suggestedSlug));
    return button;
  });
  query('#suggested-list').replaceChildren(...suggestions);
  if (updateHash) history.replaceState(null, '', `#docs/${article.slug}`);
  view.scrollIntoView({ block: 'start' });
  if (focus) query('#article-title')?.focus?.({ preventScroll: true });
  return true;
}

function closeArticle({ updateHash = true } = {}) {
  currentArticle = null;
  query('#docs-heading').hidden = false;
  query('#article-grid').hidden = false;
  query('#article-view').hidden = true;
  filterArticles?.apply({ immediate: true });
  if (updateHash) history.replaceState(null, '', '#docs');
  query('#docs-search')?.focus({ preventScroll: true });
}

query('#article-back')?.addEventListener('click', () => closeArticle());
queryAll('[data-article]').forEach((control) => control.addEventListener('click', () => openArticle(control.dataset.article)));

async function loadArticles(config) {
  const articleUrl = new URL(config.articles || './articles.json', config.base);
  const response = await fetch(articleUrl, { cache: 'no-store' });
  if (!response.ok) throw new Error('Feature article catalog is unavailable');
  articles = validateArticleCatalog(await response.json());
  articleBySlug = new Map(articles.map((article) => [article.slug, article]));
  renderArticleCards();
  query('#article-status').hidden = true;
  filterArticles = wireSearch({
    search: query('#docs-search'),
    pattern: query('#docs-pattern'),
    toggle: query('#docs-regex'),
    flags: query('#docs-flags'),
    sample: query('#docs-sample'),
    feedback: query('#docs-feedback'),
    captures: query('#docs-captures'),
    records: () => queryAll('#article-grid .article-card'),
    text: (card) => card.dataset.search || card.textContent,
    empty: query('#docs-empty'),
  });
  addArticlesToPalette();
  handleLocation();
}

const palette = query('#command-palette');
commandPalette = palette;
const paletteSearch = query('#palette-search');
const palettePattern = query('#palette-pattern');
const paletteRegex = query('#palette-regex');
const paletteFlags = query('#palette-flags');
const paletteFeedback = query('#palette-feedback');
const paletteResults = query('#palette-results');
const paletteItems = [
  ['Home', 'Open home page', 'home', '#home'],
  ['Features', 'Browse the complete feature inventory', 'features', '#features'],
  ['Documentation', 'Browse every bundled feature article', 'docs', '#article-grid'],
  ['Guides', 'Open installation and workflow guides', 'guides', '#guides'],
  ['Community', 'Open community links', 'community', '#community'],
  ['Settings', 'Edit shell language, funny levels, theme, density, and accent', 'settings', '#settings'],
  ['Reset site settings', 'Restore persisted site preferences', 'settings', '#reset-site-settings'],
];

function englishText(element, fallback) {
  return (element ? query('[lang="en"]', element)?.textContent?.trim() : '') || element?.textContent?.trim() || fallback;
}

queryAll('#feature-grid .feature-card').forEach((card, index) => {
  const title = englishText(query('h2', card), `Feature ${index + 1}`);
  paletteItems.push([title, englishText(query('p', card), 'Open feature details'), 'features', `#feature-grid .feature-card:nth-of-type(${index + 1})`]);
});
queryAll('#settings-grid .setting-card').forEach((card, index) => {
  const title = englishText(query(':scope > span', card), `Setting ${index + 1}`);
  paletteItems.push([title, englishText(query('.setting-help', card), 'Open setting'), 'settings', `#settings-grid .setting-card:nth-of-type(${index + 1})`]);
});

function addArticlesToPalette() {
  articles.forEach((article) => paletteItems.push([article.title.en, article.summary.en, 'docs', `article:${article.slug}`, article]));
  if (palette?.open) paletteSearchController?.apply({ immediate: true });
}

let paletteActiveIndex = 0;
let paletteOpener = null;
let paletteDestination = null;
let currentPaletteMatches = paletteItems;

function focusablePaletteDestination(target) {
  if (!target) return null;
  if (target.matches('.page-section, #article-title')) return target;
  const control = query('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), [tabindex="0"]', target);
  if (control) return control;
  target.tabIndex = -1;
  return target;
}

function activatePaletteItem(item) {
  if (item[3].startsWith('article:')) {
    openArticle(item[3].slice(8), { focus: false });
    paletteDestination = query('#article-title');
  } else {
    if (item[0] === 'Reset site settings') query('#reset-site-settings')?.click();
    showTab(item[2], { focus: false });
    const target = query(item[3]);
    const ownerController = [...searchControllers.values()].find(
      (controller) => controller.search.closest('.page-section')?.dataset.page === item[2],
    );
    ownerController?.cancel();
    if (target && 'hidden' in target) target.hidden = false;
    target?.scrollIntoView({ block: 'center' });
    paletteDestination = focusablePaletteDestination(target);
  }
  palette.close();
}

function renderPalette(matches = currentPaletteMatches, { focusResult = false } = {}) {
  currentPaletteMatches = matches;
  paletteActiveIndex = Math.min(paletteActiveIndex, Math.max(0, matches.length - 1));
  const buttons = matches.map((item, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.id = `palette-result-${index}`;
    button.className = 'palette-result';
    button.setAttribute('role', 'option');
    button.setAttribute('aria-selected', String(index === paletteActiveIndex));
    button.tabIndex = index === paletteActiveIndex ? 0 : -1;
    const text = document.createElement('span');
    const strong = document.createElement('strong');
    if (item[4]) strong.append(createArticleLocalizedCopy(item[4].title));
    else if (Object.prototype.hasOwnProperty.call(messages, item[0])) setLocalizedContent(strong, item[0]);
    else { strong.textContent = item[0]; strong.lang = 'en'; }
    const small = document.createElement('small');
    if (item[4]) small.append(createArticleLocalizedCopy(item[4].summary));
    else if (Object.prototype.hasOwnProperty.call(messages, item[1])) setLocalizedContent(small, item[1]);
    else { small.textContent = item[1]; small.lang = 'en'; }
    text.append(strong, document.createElement('br'), small);
    button.append(text, document.createTextNode('↗'));
    const actionKey = item[3].startsWith('article:')
      ? 'Open article: {title}'
      : item[3].includes('.feature-card')
        ? 'Open feature: {title}'
        : item[3].includes('.setting-card') || item[3] === '#reset-site-settings'
          ? 'Open setting: {title}'
          : 'Open page: {title}';
    setLocalizedAttribute(button, 'aria-label', actionKey, { title: item[4]?.title || item[0] });
    button.addEventListener('click', () => activatePaletteItem(item));
    button.addEventListener('keydown', (event) => {
      if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      if (event.key === 'ArrowDown') paletteActiveIndex = (index + 1) % buttons.length;
      if (event.key === 'ArrowUp') paletteActiveIndex = (index + buttons.length - 1) % buttons.length;
      if (event.key === 'Home') paletteActiveIndex = 0;
      if (event.key === 'End') paletteActiveIndex = buttons.length - 1;
      renderPalette(currentPaletteMatches, { focusResult: true });
    });
    return button;
  });
  paletteResults.replaceChildren(...buttons);
  const active = buttons[paletteActiveIndex];
  if (active) {
    paletteSearch.setAttribute('aria-activedescendant', active.id);
    paletteResults.setAttribute('aria-activedescendant', active.id);
    active.scrollIntoView({ block: 'nearest' });
    if (focusResult) active.focus();
  } else {
    paletteSearch.removeAttribute('aria-activedescendant');
    paletteResults.removeAttribute('aria-activedescendant');
  }
}

paletteSearchController = wireSearch({
  search: paletteSearch,
  pattern: palettePattern,
  toggle: paletteRegex,
  flags: paletteFlags,
  sample: query('#palette-sample'),
  feedback: paletteFeedback,
  captures: query('#palette-captures'),
  records: () => paletteItems,
  text: (item) => item[4]
    ? `${item[4].title.en} ${item[4].title['zh-Hant']} ${item[4].summary.en} ${item[4].summary['zh-Hant']} ${item[4].markdown.en} ${item[4].markdown['zh-Hant']}`
    : `${item[0]} ${messages[item[0]] || ''} ${item[1]} ${messages[item[1]] || ''}`,
  onMatches: (matches) => { paletteActiveIndex = 0; renderPalette(matches); },
});

function openPalette() {
  if (!palette || palette.open) return;
  paletteOpener = document.activeElement;
  paletteDestination = null;
  palette.showModal();
  paletteSearch.setAttribute('aria-expanded', 'true');
  paletteActiveIndex = 0;
  paletteSearchController.apply({ immediate: true });
  queueMicrotask(() => {
    paletteSearch.focus();
    paletteSearch.select();
  });
}

palette?.addEventListener('close', () => {
  paletteSearch.setAttribute('aria-expanded', 'false');
  paletteSearchController.cancel();
  const destination = paletteDestination;
  const opener = paletteOpener;
  paletteDestination = null;
  paletteOpener = null;
  const restoreFocus = () => {
    const target = destination?.isConnected ? destination : opener;
    target?.scrollIntoView?.({ block: 'center' });
    target?.focus?.({ preventScroll: true });
  };
  if (destination) requestAnimationFrame(() => requestAnimationFrame(restoreFocus));
  else queueMicrotask(restoreFocus);
});
paletteSearch?.addEventListener('keydown', (event) => {
  const buttons = queryAll('.palette-result', paletteResults);
  if (!buttons.length) return;
  if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
    event.preventDefault();
    if (event.key === 'ArrowDown') paletteActiveIndex = (paletteActiveIndex + 1) % buttons.length;
    if (event.key === 'ArrowUp') paletteActiveIndex = (paletteActiveIndex + buttons.length - 1) % buttons.length;
    if (event.key === 'Home') paletteActiveIndex = 0;
    if (event.key === 'End') paletteActiveIndex = buttons.length - 1;
    renderPalette(currentPaletteMatches);
  }
  if (event.key === 'Enter') {
    event.preventDefault();
    buttons[paletteActiveIndex]?.click();
  }
});

document.addEventListener('keydown', (event) => {
  const active = document.activeElement;
  const typing = active && ['INPUT', 'TEXTAREA', 'SELECT'].includes(active.tagName);
  if (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === 'f') {
    event.preventDefault();
    openPalette();
  } else if (event.key === '/' && !typing && !palette?.open) {
    event.preventDefault();
    showTab('features');
    featureSearch?.focus();
  }
});

function handleLocation() {
  const route = location.hash.slice(1);
  if (route.startsWith('docs/')) {
    if (articles.length) openArticle(route.slice(5), { updateHash: false });
    else showTab('docs', { updateHash: false });
    return;
  }
  if (currentArticle) closeArticle({ updateHash: false });
  showTab(tabs.some((tab) => tab.dataset.tab === route) ? route : 'home', { updateHash: false, focus: false });
}

window.addEventListener('hashchange', handleLocation);
handleLocation();

loadSiteConfig()
  .then((config) => Promise.allSettled([loadPublicationManifest(config), loadArticles(config)]))
  .then((results) => {
    if (results[1]?.status === 'rejected') {
      setLocalizedContent(query('#article-status'), 'The bundled article catalog could not be loaded. The rest of the site remains available.');
    }
  })
  .catch(() => {
    setLocalizedContent(query('#article-status'), 'Site configuration could not be loaded. The static shell remains available.');
    query('#release-download').hidden = true;
    query('#release-code-name').hidden = true;
  });
