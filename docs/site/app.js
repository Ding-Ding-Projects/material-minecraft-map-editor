import {
  applyThemeRoles,
  contrastRatio,
  hexRgb,
  hslRgb,
  normaliseHex,
  rgbHex,
  rgbHsl,
} from './theme.mjs';

const query = (selector, root = document) => root.querySelector(selector);
const queryAll = (selector, root = document) => [...root.querySelectorAll(selector)];
const tabs = queryAll('.nav-tab');
const pages = queryAll('.page-section');

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
    if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) return null;
    if (!url.pathname.endsWith(`/${assetName}`) || !url.pathname.includes(`/download/${releaseTag}/`)) return null;
    return url.href;
  } catch (_error) {
    return null;
  }
}

function verifiedManifest(manifest) {
  if (manifest?.schemaVersion !== 1 || manifest.verified !== true || !/^[0-9a-f]{40}$/i.test(String(manifest.commit || ''))) return false;
  const tag = String(manifest.releaseTag || '');
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(tag)) return false;
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
    query('#release-eyebrow').textContent = `VERIFIED WINDOWS BUILD · ${tag}`;
    query('#release-title').textContent = localized('release', settings.language?.value || 'english');
    query('#release-copy').textContent = 'This immutable unsigned Squirrel.Windows installer is backed by the verified tag, commit, asset path, and SHA-256 release manifest. Windows may show an unknown-publisher warning because signing is intentionally disabled.';
    releaseDownload.hidden = false;
    releaseDownload.href = url;
    releaseDownload.removeAttribute('data-tab-link');
    releaseDownload.target = '_blank';
    releaseDownload.rel = 'noreferrer';
    releaseDownload.textContent = `Download Setup.exe · ${tag} · Windows x64 ↗`;
  } catch (_error) {
    releaseDownload.hidden = true;
  }
}

function escaped(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function safeRegExp(raw, sourceFlags = 'i') {
  const value = String(raw || '');
  if (value.length > 256) throw new Error('Pattern is limited to 256 characters');
  if (!/^[dgimsuvy]*$/.test(sourceFlags)) throw new Error('Unsupported regular-expression flag');
  if (/\([^()]*[+*][^()]*\)[+*{]/.test(value)) throw new Error('Nested quantifiers are disabled');
  return new RegExp(value || '(?!)', sourceFlags);
}

function buildMatcher(raw, regex, sourceFlags = 'i') {
  const value = String(raw || '');
  if (value.length > 256) throw new Error('Pattern is limited to 256 characters');
  return safeRegExp(regex ? value : escaped(value), sourceFlags);
}

function wireSearch({ search, pattern, toggle, flags, feedback, records, text, empty }) {
  const apply = () => {
    const regex = Boolean(toggle?.checked);
    const raw = (regex ? pattern?.value : search?.value) || '';
    let matcher;
    try {
      matcher = buildMatcher(raw, regex, regex ? (flags?.value || 'i') : 'i');
      if (feedback) feedback.textContent = regex ? 'Valid JavaScript regular expression' : 'Plain-text mode';
    } catch (error) {
      if (feedback) feedback.textContent = `Invalid pattern: ${error.message}`;
      records().forEach((record) => { record.hidden = true; });
      if (empty) empty.hidden = false;
      return;
    }
    let count = 0;
    records().forEach((record) => {
      matcher.lastIndex = 0;
      const match = !raw || matcher.test(text(record));
      record.hidden = !match;
      if (match) count += 1;
    });
    if (empty) empty.hidden = count !== 0;
  };
  search?.addEventListener('input', () => {
    if (toggle && !toggle.checked) pattern.value = search.value;
    apply();
  });
  toggle?.addEventListener('change', () => {
    pattern.value = search.value;
    apply();
  });
  pattern?.addEventListener('input', apply);
  flags?.addEventListener('change', apply);
  return apply;
}

const featureSearch = query('#feature-search');
const featurePattern = query('#feature-pattern');
const featureToggle = query('#feature-regex');
const featureFlags = query('#feature-flags');
const featureFeedback = query('#regex-feedback');
const featureCaptures = query('#regex-captures');
const featureSample = query('#feature-sample');
const filterFeatures = wireSearch({
  search: featureSearch,
  pattern: featurePattern,
  toggle: featureToggle,
  flags: featureFlags,
  feedback: featureFeedback,
  records: () => queryAll('#feature-grid .feature-card'),
  text: (card) => `${card.dataset.search || ''} ${card.textContent}`,
  empty: query('#feature-empty'),
});

function updateFeatureSample() {
  if (!featureCaptures) return;
  try {
    const raw = (featureToggle?.checked ? featurePattern?.value : featureSearch?.value) || '';
    const matcher = buildMatcher(raw, Boolean(featureToggle?.checked), featureToggle?.checked ? featureFlags?.value : 'i');
    const match = raw ? matcher.exec(featureSample?.value || '') : null;
    featureCaptures.textContent = match?.length > 1 ? `Captures: ${match.slice(1).join(' · ')}` : 'No capture groups in sample';
  } catch (_error) {
    featureCaptures.textContent = '';
  }
}

[featureSearch, featurePattern, featureToggle, featureFlags, featureSample].forEach((control) => control?.addEventListener('input', () => {
  filterFeatures();
  updateFeatureSample();
}));

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
const languageCopy = {
  english: {
    home: 'Home', features: 'Features', docs: 'Documentation', guides: 'Guides', community: 'Community', settings: 'Settings',
    source: 'View source ↗', install: 'Open the install guide', explore: 'Explore features →',
    release: 'Install the verified unsigned Squirrel package', close: 'Close', reset: 'Reset site settings',
    back: 'Back to all articles', suggested: 'Suggested articles',
  },
  cantonese: {
    home: '首頁', features: '功能', docs: '說明文件', guides: '指南', community: '社群', settings: '設定',
    source: '睇原始碼 ↗', install: '開啟安裝指南', explore: '探索功能 →',
    release: '安裝已核實但未簽署嘅 Squirrel 套件', close: '關閉', reset: '重設網站設定',
    back: '返回所有文章', suggested: '建議文章',
  },
};

function localized(key, language) {
  const english = languageCopy.english[key] || key;
  const cantonese = languageCopy.cantonese[key] || english;
  if (language === 'bilingual') return `${english} · ${cantonese}`;
  return language === 'cantonese' ? cantonese : english;
}

function applyLanguage(language) {
  const mode = ['english', 'cantonese', 'bilingual'].includes(language) ? language : 'english';
  document.documentElement.lang = mode === 'cantonese' ? 'zh-Hant' : 'en';
  tabs.forEach((tab) => {
    tab.textContent = localized(tab.dataset.tab, mode);
    tab.setAttribute('aria-label', localized(tab.dataset.tab, mode));
  });
  query('.top-app-bar > .button')?.replaceChildren(document.createTextNode(localized('source', mode)));
  query('[data-tab-link="guides"]')?.replaceChildren(document.createTextNode(localized('install', mode)));
  query('[data-tab-link="features"]')?.replaceChildren(document.createTextNode(localized('explore', mode)));
  query('#release-title')?.replaceChildren(document.createTextNode(localized('release', mode)));
  query('#reset-site-settings')?.replaceChildren(document.createTextNode(localized('reset', mode)));
  query('#command-palette .button')?.replaceChildren(document.createTextNode(localized('close', mode)));
  query('#article-back')?.replaceChildren(document.createTextNode(localized('back', mode)));
  query('#suggested-title')?.replaceChildren(document.createTextNode(localized('suggested', mode)));
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
  query('#accent-contrast')?.replaceChildren(`Derived primary/surface: ${primarySurface}:1 · On-primary/primary: ${onPrimary}:1`);
  query('#site-scale-value')?.replaceChildren(`${value.scale}%`);
  query('#funny-en-value')?.replaceChildren(String(value.funnyEn));
  query('#funny-yue-value')?.replaceChildren(String(value.funnyYue));
  applyLanguage(value.language);
  const copy = query('#settings-copy');
  if (copy) {
    const english = value.funnyEn >= 4
      ? 'Shell preferences apply immediately; the buttons may now grin a little, while canonical article text keeps its serious shoes on.'
      : 'Preferences persist in this browser and apply immediately. Language and funny-level controls style the site shell; canonical article text remains unchanged.';
    const cantonese = value.funnyYue >= 4
      ? '介面設定即時生效，啲掣可以笑少少；技術文章繼續著住正經鞋。'
      : '設定會保存在此瀏覽器並即時生效；語言同玩味程度只改介面，技術文章保持原文。';
    copy.textContent = value.language === 'bilingual' ? `${english} · ${cantonese}` : value.language === 'cantonese' ? cantonese : english;
  }
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
  feedback: query('#settings-feedback'),
  records: () => queryAll('#settings-grid .setting-card'),
  text: (card) => `${card.dataset.search || ''} ${card.textContent}`,
  empty: query('#settings-empty'),
});

let articles = [];
let articleBySlug = new Map();
let currentArticle = null;
let filterArticles = () => {};

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

function renderMarkdown(markdown, target) {
  target.replaceChildren();
  const lines = String(markdown || '').split(/\r?\n/);
  let paragraph = [];
  let list = null;
  let fence = null;
  let fenceLanguage = '';

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
      element.id = `article-${label.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')}`;
      if (heading[1].length === 1) {
        element.id = 'article-title';
        element.tabIndex = -1;
      }
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
  if (catalog?.schemaVersion !== 1 || !Array.isArray(catalog.articles) || catalog.articleCount !== catalog.articles.length) throw new Error('Invalid article catalog');
  const slugs = new Set(catalog.articles.map((article) => article.slug));
  catalog.articles.forEach((article) => {
    if (!/^[a-z0-9-]{1,80}$/.test(article.slug) || typeof article.title !== 'string' || typeof article.markdown !== 'string') throw new Error('Invalid article record');
    if (!/^docs\/features\/[a-z0-9-]+\/README\.md$/.test(article.sourcePath) || !/^[0-9a-f]{64}$/.test(article.sha256)) throw new Error('Invalid article provenance');
    if (!Array.isArray(article.suggested) || article.suggested.length < 2 || article.suggested.some((slug) => !slugs.has(slug) || slug === article.slug)) throw new Error('Invalid suggested-article navigation');
  });
  return catalog.articles;
}

function renderArticleCards() {
  const cards = articles.map((article) => {
    const card = document.createElement('article');
    card.className = 'article-card';
    card.dataset.search = `${article.title} ${article.summary} ${article.markdown}`;
    const eyebrow = document.createElement('span');
    eyebrow.className = 'eyebrow';
    eyebrow.textContent = 'FEATURE ARTICLE';
    const title = document.createElement('h2');
    title.textContent = article.title;
    const summary = document.createElement('p');
    summary.textContent = article.summary;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'inline-link';
    button.textContent = 'Read on this site →';
    button.dataset.article = article.slug;
    button.addEventListener('click', () => openArticle(article.slug));
    card.append(eyebrow, title, summary, button);
    return card;
  });
  query('#article-grid').replaceChildren(...cards);
}

function openArticle(slug, { updateHash = true } = {}) {
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
  query('#article-source').textContent = `${article.sourcePath} · SHA-256 ${article.sha256.slice(0, 12)}…`;
  renderMarkdown(article.markdown, query('#article-content'));
  const suggestions = article.suggested.map((suggestedSlug) => {
    const suggested = articleBySlug.get(suggestedSlug);
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = suggested.title;
    button.addEventListener('click', () => openArticle(suggestedSlug));
    return button;
  });
  query('#suggested-list').replaceChildren(...suggestions);
  if (updateHash) history.replaceState(null, '', `#docs/${article.slug}`);
  view.scrollIntoView({ block: 'start' });
  query('#article-title')?.focus?.({ preventScroll: true });
  return true;
}

function closeArticle({ updateHash = true } = {}) {
  currentArticle = null;
  query('#docs-heading').hidden = false;
  query('#article-grid').hidden = false;
  query('#article-view').hidden = true;
  filterArticles();
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
    feedback: query('#docs-feedback'),
    records: () => queryAll('#article-grid .article-card'),
    text: (card) => card.dataset.search || card.textContent,
    empty: query('#docs-empty'),
  });
  addArticlesToPalette();
  handleLocation();
}

const palette = query('#command-palette');
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

queryAll('#feature-grid .feature-card').forEach((card, index) => {
  const title = query('h2', card)?.textContent?.trim() || `Feature ${index + 1}`;
  paletteItems.push([title, query('p', card)?.textContent?.trim() || 'Open feature details', 'features', `#feature-grid .feature-card:nth-of-type(${index + 1})`]);
});
queryAll('#settings-grid .setting-card').forEach((card, index) => {
  const title = query('span', card)?.textContent?.trim() || `Setting ${index + 1}`;
  paletteItems.push([title, query('.setting-help', card)?.textContent?.trim() || 'Open setting', 'settings', `#settings-grid .setting-card:nth-of-type(${index + 1})`]);
});

function addArticlesToPalette() {
  articles.forEach((article) => paletteItems.push([article.title, article.summary, 'docs', `article:${article.slug}`]));
  if (palette?.open) renderPalette();
}

let paletteActiveIndex = 0;
let paletteOpener = null;

function activatePaletteItem(item) {
  if (item[3].startsWith('article:')) openArticle(item[3].slice(8));
  else {
    if (item[0] === 'Reset site settings') query('#reset-site-settings')?.click();
    showTab(item[2]);
    const target = query(item[3]);
    target?.scrollIntoView({ block: 'center' });
    target?.focus?.({ preventScroll: true });
  }
  palette.close();
}

function renderPalette({ focusResult = false } = {}) {
  const regex = Boolean(paletteRegex?.checked);
  const raw = (regex ? palettePattern?.value : paletteSearch?.value) || '';
  let matcher;
  try {
    matcher = buildMatcher(raw, regex, regex ? (paletteFlags?.value || 'i') : 'i');
    paletteFeedback.textContent = regex ? 'Valid JavaScript regular expression' : 'Plain-text mode';
  } catch (error) {
    paletteFeedback.textContent = `Invalid pattern: ${error.message}`;
    paletteResults.replaceChildren();
    paletteSearch.removeAttribute('aria-activedescendant');
    return;
  }
  const matches = paletteItems.filter((item) => {
    matcher.lastIndex = 0;
    return !raw || matcher.test(`${item[0]} ${item[1]}`);
  });
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
    strong.textContent = item[0];
    const small = document.createElement('small');
    small.textContent = item[1];
    text.append(strong, document.createElement('br'), small);
    button.append(text, document.createTextNode('↗'));
    button.addEventListener('click', () => activatePaletteItem(item));
    button.addEventListener('keydown', (event) => {
      if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      if (event.key === 'ArrowDown') paletteActiveIndex = (index + 1) % buttons.length;
      if (event.key === 'ArrowUp') paletteActiveIndex = (index + buttons.length - 1) % buttons.length;
      if (event.key === 'Home') paletteActiveIndex = 0;
      if (event.key === 'End') paletteActiveIndex = buttons.length - 1;
      renderPalette({ focusResult: true });
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

function openPalette() {
  if (!palette || palette.open) return;
  paletteOpener = document.activeElement;
  palette.showModal();
  paletteSearch.setAttribute('aria-expanded', 'true');
  paletteActiveIndex = 0;
  renderPalette();
  queueMicrotask(() => {
    paletteSearch.focus();
    paletteSearch.select();
  });
}

palette?.addEventListener('close', () => {
  paletteSearch.setAttribute('aria-expanded', 'false');
  paletteOpener?.focus?.();
});
paletteSearch?.addEventListener('input', () => {
  if (paletteRegex && !paletteRegex.checked) palettePattern.value = paletteSearch.value;
  paletteActiveIndex = 0;
  renderPalette();
});
paletteRegex?.addEventListener('change', () => { palettePattern.value = paletteSearch.value; renderPalette(); });
palettePattern?.addEventListener('input', renderPalette);
paletteFlags?.addEventListener('change', renderPalette);
paletteSearch?.addEventListener('keydown', (event) => {
  const buttons = queryAll('.palette-result', paletteResults);
  if (!buttons.length) return;
  if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
    event.preventDefault();
    if (event.key === 'ArrowDown') paletteActiveIndex = (paletteActiveIndex + 1) % buttons.length;
    if (event.key === 'ArrowUp') paletteActiveIndex = (paletteActiveIndex + buttons.length - 1) % buttons.length;
    if (event.key === 'Home') paletteActiveIndex = 0;
    if (event.key === 'End') paletteActiveIndex = buttons.length - 1;
    renderPalette();
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
      query('#article-status').textContent = 'The bundled article catalog could not be loaded. The rest of the site remains available.';
    }
  })
  .catch(() => {
    query('#article-status').textContent = 'Site configuration could not be loaded. The static shell remains available.';
    query('#release-download').hidden = true;
  });
