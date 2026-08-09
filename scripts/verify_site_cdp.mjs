import { readFile, writeFile } from 'node:fs/promises';

import { dprMatches } from './site_runtime_math.mjs';

function argument(name, fallback = null) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : fallback;
}

const origin = new URL(argument('--origin', 'http://127.0.0.1:8000'));
const endpoint = new URL(argument('--cdp', 'http://127.0.0.1:9222'));
const reportPath = argument('--report');
const expectedManifestPath = argument('--expected-manifest', 'docs/site/release-manifest.json');
const expectedManifest = JSON.parse(await readFile(expectedManifestPath, 'utf8'));
const expectedSetupUrl = expectedManifest.assets?.['Setup.exe']?.url;
const expectedPhotoUrl = expectedManifest.codeName?.photoUrl;
if (!expectedManifest.verified || !expectedSetupUrl || !expectedPhotoUrl) {
  throw new Error(`Expected release manifest is incomplete: ${expectedManifestPath}`);
}
if (!['127.0.0.1', 'localhost'].includes(origin.hostname) || origin.protocol !== 'http:') {
  throw new Error('CDP site verification is limited to a loopback HTTP origin');
}
if (!['127.0.0.1', 'localhost'].includes(endpoint.hostname) || endpoint.protocol !== 'http:') {
  throw new Error('Chrome DevTools verification is limited to a loopback endpoint');
}

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

class DevToolsClient {
  constructor(socket) {
    this.socket = socket;
    this.nextId = 1;
    this.pending = new Map();
    this.waiters = new Map();
    socket.addEventListener('message', (event) => {
      const message = JSON.parse(String(event.data));
      if (message.id) {
        const pending = this.pending.get(message.id);
        if (!pending) return;
        this.pending.delete(message.id);
        if (message.error) pending.reject(new Error(`${pending.method}: ${message.error.message}`));
        else pending.resolve(message.result || {});
        return;
      }
      const waiters = this.waiters.get(message.method) || [];
      this.waiters.delete(message.method);
      waiters.forEach((resolve) => resolve(message.params || {}));
    });
  }

  send(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { method, resolve, reject });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  event(method, timeout = 15000) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(`Timed out waiting for ${method}`)), timeout);
      const wrapped = (value) => {
        clearTimeout(timer);
        resolve(value);
      };
      this.waiters.set(method, [...(this.waiters.get(method) || []), wrapped]);
    });
  }

  async evaluate(expression) {
    const response = await this.send('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (response.exceptionDetails) {
      throw new Error(response.exceptionDetails.exception?.description || response.exceptionDetails.text);
    }
    return response.result?.value;
  }
}

async function connect() {
  const response = await fetch(new URL('/json/list', endpoint));
  if (!response.ok) throw new Error(`Chrome DevTools target list returned ${response.status}`);
  const targets = await response.json();
  const target = targets.find((entry) => entry.type === 'page' && entry.webSocketDebuggerUrl);
  if (!target) throw new Error('Chrome DevTools has no page target');
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, { once: true });
    socket.addEventListener('error', () => reject(new Error('Chrome DevTools WebSocket failed')), { once: true });
  });
  return new DevToolsClient(socket);
}

const cdp = await connect();
await Promise.all([
  cdp.send('Page.enable'),
  cdp.send('Runtime.enable'),
  cdp.send('Network.enable'),
]);

async function navigate(url) {
  await cdp.send('Page.navigate', { url });
  await waitFor(`location.href === ${JSON.stringify(url)} && document.readyState === 'complete'`, `navigation to ${url}`);
}

async function reload() {
  const previousTimeOrigin = await cdp.evaluate('performance.timeOrigin');
  await cdp.send('Page.reload', { ignoreCache: true });
  await waitFor(`performance.timeOrigin !== ${JSON.stringify(previousTimeOrigin)} && document.readyState === 'complete'`, 'page reload');
}

async function waitFor(expression, label, timeout = 20000) {
  const deadline = Date.now() + timeout;
  let last;
  while (Date.now() < deadline) {
    try {
      last = await cdp.evaluate(expression);
    } catch (_error) {
      last = null;
    }
    if (last) return last;
    await delay(100);
  }
  throw new Error(`Timed out waiting for ${label}; last value: ${JSON.stringify(last)}`);
}

async function key(key, code, windowsVirtualKeyCode, modifiers = 0) {
  await cdp.send('Input.dispatchKeyEvent', {
    type: 'rawKeyDown', key, code, windowsVirtualKeyCode, nativeVirtualKeyCode: windowsVirtualKeyCode, modifiers,
  });
  await cdp.send('Input.dispatchKeyEvent', {
    type: 'keyUp', key, code, windowsVirtualKeyCode, nativeVirtualKeyCode: windowsVirtualKeyCode, modifiers,
  });
}

async function openPalette(openerSelector = '#tab-home') {
  await cdp.evaluate(`document.querySelector(${JSON.stringify(openerSelector)}).focus()`);
  await key('F', 'KeyF', 70, 2 | 8);
  await waitFor("document.querySelector('#command-palette').open", 'command palette to open');
}

async function activatePalette(query) {
  await cdp.evaluate(`(() => {
    const search = document.querySelector('#palette-search');
    search.value = ${JSON.stringify(query)};
    search.dispatchEvent(new Event('input', { bubbles: true }));
    search.focus();
  })()`);
  await waitFor(
    `(() => {
      const strong = document.querySelector('.palette-result:first-child strong');
      const english = strong?.matches('[lang="en"]') ? strong : strong?.querySelector('[lang="en"]');
      return english?.textContent.trim() === ${JSON.stringify(query)};
    })()`,
    `exact first palette result for ${query}`,
  );
  await cdp.evaluate("document.querySelector('#palette-search').focus()");
  await key('Enter', 'Enter', 13);
  await waitFor("!document.querySelector('#command-palette').open", 'command palette to close');
  await delay(50);
  return cdp.evaluate(`(() => {
    const active = document.activeElement;
    return {
      id: active?.id || '',
      tag: active?.tagName || '',
      hash: location.hash,
      article: document.querySelector('#article-title [lang="en"]')?.textContent?.trim() || '',
      feature: active?.closest?.('.feature-card')?.querySelector('h2 [lang="en"]')?.textContent?.trim() || '',
      setting: active?.closest?.('.setting-card')?.querySelector(':scope > span [lang="en"]')?.textContent?.trim() || '',
    };
  })()`);
}

const initialUrl = new URL('/', origin);
initialUrl.searchParams.set('cdp-run', String(Date.now()));
initialUrl.hash = 'home';
await navigate(initialUrl.href);
await waitFor(
  "document.querySelectorAll('#article-grid .article-card').length === 18 && !document.querySelector('#release-download').hidden",
  '18 article cards and verified release link',
);

const verified = await cdp.evaluate(`(() => {
  const link = document.querySelector('#release-download');
  return {
    hidden: link.hidden,
    display: getComputedStyle(link).display,
    href: link.href,
    photoHref: document.querySelector('#release-code-name-link').href,
    cards: document.querySelectorAll('#article-grid .article-card').length,
    palette: Boolean(document.querySelector('#command-palette')),
  };
})()`);
if (
  verified.hidden
  || verified.display === 'none'
  || verified.cards !== 18
  || !verified.palette
  || verified.href !== expectedSetupUrl
  || verified.photoHref !== expectedPhotoUrl
) {
  throw new Error(`Verified runtime state is wrong: ${JSON.stringify(verified)}`);
}

const unverifiedScript = await cdp.send('Page.addScriptToEvaluateOnNewDocument', {
  source: `(() => {
    const realFetch = window.fetch.bind(window);
    window.fetch = (input, init) => {
      const url = new URL(input instanceof Request ? input.url : input, document.baseURI);
      if (url.pathname.endsWith('/release-manifest.json')) {
        return Promise.resolve(new Response(JSON.stringify({ schemaVersion: 1, verified: false, assets: {} }), {
          status: 200, headers: { 'Content-Type': 'application/json' },
        }));
      }
      return realFetch(input, init);
    };
  })();`,
});
await reload();
await waitFor("document.documentElement.dataset.baseUrl", 'unverified manifest load');
const unverified = await cdp.evaluate(`(() => {
  const link = document.querySelector('#release-download');
  return { hidden: link.hidden, display: getComputedStyle(link).display };
})()`);
if (!unverified.hidden || unverified.display !== 'none') {
  throw new Error(`Unverified release link is not computed-hidden: ${JSON.stringify(unverified)}`);
}
await cdp.send('Page.removeScriptToEvaluateOnNewDocument', { identifier: unverifiedScript.identifier });

const publishedManifest = await (await fetch(new URL('release-manifest.json', origin))).json();
const publishedArticles = await (await fetch(new URL('articles.json', origin))).json();
const setupUrl = publishedManifest.assets['Setup.exe'].url;
const invalidReleaseUrls = {
  wrongHost: setupUrl.replace('github.com', 'downloads.example.test'),
  wrongRepository: setupUrl.replace(
    'Ding-Ding-Projects/material-minecraft-map-editor',
    'Ding-Ding-Projects/wrong-repository',
  ),
  query: `${setupUrl}?candidate=true`,
  credentials: setupUrl.replace('https://', 'https://user:secret@'),
};
const invalidUrlVisibility = {};
for (const [name, url] of Object.entries(invalidReleaseUrls)) {
  const invalidManifest = JSON.parse(JSON.stringify(publishedManifest));
  invalidManifest.assets['Setup.exe'].url = url;
  const script = await cdp.send('Page.addScriptToEvaluateOnNewDocument', {
    source: `(() => {
      const realFetch = window.fetch.bind(window);
      window.fetch = (input, init) => {
        const url = new URL(input instanceof Request ? input.url : input, document.baseURI);
        if (url.pathname.endsWith('/release-manifest.json')) {
          return Promise.resolve(new Response(${JSON.stringify(JSON.stringify(invalidManifest))}, {
            status: 200, headers: { 'Content-Type': 'application/json' },
          }));
        }
        return realFetch(input, init);
      };
    })();`,
  });
  await reload();
  await waitFor('document.documentElement.dataset.baseUrl', `${name} manifest load`);
  const state = await cdp.evaluate(`(() => {
    const link = document.querySelector('#release-download');
    return { hidden: link.hidden, display: getComputedStyle(link).display };
  })()`);
  if (!state.hidden || state.display !== 'none') {
    throw new Error(`${name} release URL is not computed-hidden: ${JSON.stringify(state)}`);
  }
  invalidUrlVisibility[name] = state;
  await cdp.send('Page.removeScriptToEvaluateOnNewDocument', { identifier: script.identifier });
}

const failureScript = await cdp.send('Page.addScriptToEvaluateOnNewDocument', {
  source: `(() => {
    const realFetch = window.fetch.bind(window);
    window.fetch = (input, init) => {
      const url = new URL(input instanceof Request ? input.url : input, document.baseURI);
      if (url.pathname.endsWith('/release-manifest.json')) {
        return Promise.resolve(new Response('unavailable', { status: 503 }));
      }
      return realFetch(input, init);
    };
  })();`,
});
await reload();
await waitFor("document.documentElement.dataset.baseUrl", 'failed manifest load');
const failure = await cdp.evaluate(`(() => {
  const link = document.querySelector('#release-download');
  return { hidden: link.hidden, display: getComputedStyle(link).display };
})()`);
if (!failure.hidden || failure.display !== 'none') {
  throw new Error(`Failed release link is not computed-hidden: ${JSON.stringify(failure)}`);
}
await cdp.send('Page.removeScriptToEvaluateOnNewDocument', { identifier: failureScript.identifier });
await reload();
await waitFor("!document.querySelector('#release-download').hidden", 'verified manifest restore');

const articleLanguageChecks = [];
for (const mode of ['english', 'cantonese', 'bilingual']) {
  await cdp.evaluate(`(() => {
    const select = document.querySelector('#site-language');
    select.value = ${JSON.stringify(mode)};
    select.dispatchEvent(new Event('change', { bubbles: true }));
  })()`);
  for (const article of publishedArticles.articles) {
    await cdp.evaluate(`document.querySelector(${JSON.stringify(`[data-article="${article.slug}"]`)}).click()`);
    const route = await cdp.evaluate(`(() => {
      const visible = (element) => element && getComputedStyle(element).display !== 'none' && getComputedStyle(element).visibility !== 'hidden';
      const title = document.querySelector('#article-title');
      const titleNodes = [...title.querySelectorAll(':scope .article-localized-copy > [lang]')];
      const bodyNodes = [...document.querySelectorAll('#article-content > .article-language-copy[lang]')];
      const suggestions = [...document.querySelectorAll('#suggested-list > button')];
      const ids = [...document.querySelectorAll('[id]')].map((element) => element.id);
      return {
        hash: location.hash,
        titleText: titleNodes.filter(visible).map((node) => node.textContent.trim()),
        titleLanguages: titleNodes.filter(visible).map((node) => node.lang),
        bodyLanguages: bodyNodes.filter(visible).map((node) => node.lang),
        bodyTextLengths: Object.fromEntries(bodyNodes.map((node) => [node.lang, node.textContent.trim().length])),
        titleNodeCount: titleNodes.length,
        bodyNodeCount: bodyNodes.length,
        suggestionCount: suggestions.length,
        suggestionNames: suggestions.map((button) => button.getAttribute('aria-label') || ''),
        duplicateIds: ids.filter((id, index) => ids.indexOf(id) !== index),
      };
    })()`);
    const expectedLanguages = mode === 'english' ? ['en'] : mode === 'cantonese' ? ['zh-Hant'] : ['en', 'zh-Hant'];
    const expectedTitles = expectedLanguages.map((language) => article.title[language]);
    if (
      route.hash !== `#docs/${article.slug}`
      || JSON.stringify(route.titleLanguages) !== JSON.stringify(expectedLanguages)
      || JSON.stringify(route.bodyLanguages) !== JSON.stringify(expectedLanguages)
      || JSON.stringify(route.titleText) !== JSON.stringify(expectedTitles)
      || route.titleNodeCount !== 2
      || route.bodyNodeCount !== 2
      || route.bodyTextLengths.en <= 0
      || route.bodyTextLengths['zh-Hant'] <= 0
      || route.suggestionCount !== article.suggested.length
      || route.suggestionNames.some((name) => !name.trim())
      || route.duplicateIds.length
    ) {
      throw new Error(`Article language route failed: ${JSON.stringify({ mode, slug: article.slug, route })}`);
    }
    articleLanguageChecks.push({ mode, slug: article.slug, ...route });
  }
}

await waitFor("document.documentElement.dataset.searchInventoryReady === 'true'", 'four full regex builders');
const builders = await cdp.evaluate(`(() => ({
  count: document.querySelectorAll('.regex-builder').length,
  guided: [...document.querySelectorAll('.regex-builder')].map((builder) => builder.querySelectorAll('.regex-guide button').length),
  actions: [...document.querySelectorAll('.regex-builder')].map((builder) => builder.querySelectorAll('.regex-actions button').length),
  samples: ['feature-sample','docs-sample','settings-sample','palette-sample'].every((id) => document.getElementById(id)),
}))()`);
if (builders.count !== 4 || builders.guided.some((count) => count !== 6) || builders.actions.some((count) => count !== 2) || !builders.samples) {
  throw new Error(`Full regex builder inventory failed: ${JSON.stringify(builders)}`);
}

await cdp.evaluate(`(() => {
  document.querySelector('#tab-features').click();
  const search = document.querySelector('#feature-search');
  const pattern = document.querySelector('#feature-pattern');
  const toggle = document.querySelector('#feature-regex');
  const sample = document.querySelector('#feature-sample');
  search.value = '(a|aa)+$';
  pattern.value = search.value;
  sample.value = 'a'.repeat(511) + '!';
  toggle.checked = true;
  toggle.dispatchEvent(new Event('change', { bubbles: true }));
  sample.dispatchEvent(new Event('input', { bubbles: true }));
})()`);
await waitFor(
  "document.querySelector('#regex-feedback').textContent.includes('timed out')",
  'adversarial regex hard timeout',
  5000,
);
await cdp.evaluate(`(() => {
  const search = document.querySelector('#feature-search');
  const pattern = document.querySelector('#feature-pattern');
  const sample = document.querySelector('#feature-sample');
  search.value = 'world';
  pattern.value = 'world';
  sample.value = 'world editing';
  pattern.dispatchEvent(new Event('input', { bubbles: true }));
  sample.dispatchEvent(new Event('input', { bubbles: true }));
})()`);
await waitFor(
  "document.querySelector('#regex-feedback').textContent.includes('Live matches')",
  'fresh regex generation after timeout',
  5000,
);
await delay(350);
const generationFeedback = await cdp.evaluate("document.querySelector('#regex-feedback').textContent");
if (!generationFeedback.includes('Live matches') || generationFeedback.includes('timed out')) {
  throw new Error(`Stale regex result replaced the current generation: ${generationFeedback}`);
}
await cdp.evaluate(`(() => {
  const search = document.querySelector('#feature-search');
  const pattern = document.querySelector('#feature-pattern');
  const sample = document.querySelector('#feature-sample');
  search.value = '(a|aa)+$';
  pattern.value = search.value;
  sample.value = 'a'.repeat(511) + '!';
  sample.dispatchEvent(new Event('input', { bubbles: true }));
  document.querySelector('#tab-settings').click();
})()`);
await delay(350);
const navigationFeedback = await cdp.evaluate("document.querySelector('#regex-feedback').textContent");
if (navigationFeedback.includes('timed out')) {
  throw new Error('A cancelled regex result was delivered after page navigation');
}

const interactions = {};
await openPalette('#tab-home');
await key('Escape', 'Escape', 27);
await waitFor("!document.querySelector('#command-palette').open", 'palette Escape close');
await delay(0);
interactions.cancel = await cdp.evaluate("document.activeElement?.id");
if (interactions.cancel !== 'tab-home') throw new Error(`Escape restored ${interactions.cancel}, expected tab-home`);

await openPalette('#tab-home');
await cdp.evaluate(`(() => {
  const search = document.querySelector('#palette-search');
  const pattern = document.querySelector('#palette-pattern');
  const toggle = document.querySelector('#palette-regex');
  const sample = document.querySelector('#palette-sample');
  search.value = '(a|aa)+$';
  pattern.value = search.value;
  sample.value = 'a'.repeat(511) + '!';
  toggle.checked = true;
  toggle.dispatchEvent(new Event('change', { bubbles: true }));
  sample.dispatchEvent(new Event('input', { bubbles: true }));
})()`);
await cdp.evaluate("document.querySelector('#command-palette').close('cancel')");
await waitFor("!document.querySelector('#command-palette').open", 'palette regex cancellation close');
await delay(350);
const closedPaletteFeedback = await cdp.evaluate("document.querySelector('#palette-feedback').textContent");
if (closedPaletteFeedback.includes('timed out')) {
  throw new Error('A cancelled regex result was delivered after the palette closed');
}
await cdp.evaluate(`(() => {
  document.querySelector('#palette-regex').checked = false;
  document.querySelector('#palette-search').value = '';
  document.querySelector('#palette-pattern').value = '';
})()`);

await openPalette('#tab-home');
interactions.page = await activatePalette('Guides');
if (interactions.page.id !== 'guides' || interactions.page.hash !== '#guides') {
  throw new Error(`Page palette activation focus failed: ${JSON.stringify(interactions.page)}`);
}

await openPalette('#tab-features');
interactions.card = await activatePalette('Windows one-click builds');
if (interactions.card.feature !== 'Windows one-click builds' || interactions.card.id !== '') {
  const activeArticle = await cdp.evaluate("document.activeElement?.dataset?.article || ''");
  if (activeArticle !== 'build-scripts') {
    throw new Error(`Card palette activation focus failed: ${JSON.stringify(interactions.card)}`);
  }
}

await openPalette('#tab-settings');
interactions.setting = await activatePalette('Language mode');
if (interactions.setting.id !== 'site-language') {
  throw new Error(`Setting palette activation focus failed: ${JSON.stringify(interactions.setting)}`);
}

await openPalette('#tab-docs');
interactions.article = await activatePalette('Windows release delivery contract');
if (interactions.article.id !== 'article-title' || interactions.article.article !== 'Windows release delivery contract') {
  throw new Error(`Article palette activation focus failed: ${JSON.stringify(interactions.article)}`);
}

await cdp.send('Emulation.setDeviceMetricsOverride', {
  width: 1424, height: 900, deviceScaleFactor: 1, mobile: false,
  screenWidth: 1424, screenHeight: 900,
});
await cdp.evaluate(`(() => {
  localStorage.setItem('amulet-site-settings-v2', JSON.stringify({
    language: 'bilingual', funnyEn: 1, funnyYue: 1, theme: 'light',
    density: 'comfortable', accent: '#4d5f92', font: 'system-ui', scale: 100,
  }));
  location.hash = '#home';
})()`);
await reload();
await waitFor("!document.querySelector('#release-download').hidden", 'bilingual release card at capture width');
const bilingualHeader = await cdp.evaluate(`(() => {
  const nav = document.querySelector('.primary-nav');
  const source = document.querySelector('.top-app-bar > .button').getBoundingClientRect();
  const overlap = (first, second) => (
    first.left < second.right && first.right > second.left
    && first.top < second.bottom && first.bottom > second.top
  );
  const tabs = [...document.querySelectorAll('.primary-nav .nav-tab')].map((tab) => {
    const rect = tab.getBoundingClientRect();
    const style = getComputedStyle(tab);
    return {
      id: tab.id,
      label: tab.textContent.trim(),
      visible: style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0,
      clipped: tab.scrollWidth > tab.clientWidth,
      overlapsSource: overlap(rect, source),
      left: rect.left,
      right: rect.right,
      top: rect.top,
      bottom: rect.bottom,
    };
  });
  return {
    navOverflow: nav.scrollWidth - nav.clientWidth,
    sourceLeft: source.left,
    sourceRight: source.right,
    viewport: innerWidth,
    tabs,
  };
})()`);
if (
  bilingualHeader.navOverflow > 0
  || bilingualHeader.sourceLeft < 0
  || bilingualHeader.sourceRight > bilingualHeader.viewport
  || bilingualHeader.tabs.length !== 6
  || bilingualHeader.tabs.some((tab) => (
    !tab.visible || !tab.label || tab.clipped || tab.overlapsSource
    || tab.left < 0 || tab.right > bilingualHeader.viewport
  ))
) {
  throw new Error(`Bilingual header clips at capture width: ${JSON.stringify(bilingualHeader)}`);
}

const matrices = [];
for (const width of [360, 390, 414]) {
  const height = width === 360 ? 720 : width === 390 ? 844 : 896;
  for (const scale of [100, 120]) {
    for (const dpr of [1, 2]) {
      await cdp.send('Emulation.setDeviceMetricsOverride', {
        width, height, deviceScaleFactor: dpr, mobile: false,
        screenWidth: width, screenHeight: height,
      });
      await cdp.evaluate(`(() => {
        localStorage.setItem('amulet-site-settings-v2', JSON.stringify({
          language: 'bilingual', funnyEn: 1, funnyYue: 1, theme: 'light',
          density: 'comfortable', accent: '#4d5f92', font: 'system-ui', scale: ${scale},
        }));
        location.hash = '#docs/release-delivery';
      })()`);
      await reload();
      await waitFor(
        "document.querySelectorAll('#article-grid .article-card').length === 18 && !document.querySelector('#article-view').hidden && document.querySelector('#article-title')",
        `article layout at ${width}px ${scale}% DPR ${dpr}`,
      );
      const metrics = await cdp.evaluate(`(() => {
        const visible = (element) => {
          const style = getComputedStyle(element);
          return !element.hidden && style.display !== 'none' && style.visibility !== 'hidden';
        };
        const roots = [...document.querySelectorAll('#article-view, #article-view .article-toolbar, #article-view .article-content, #article-view .article-content > *, #article-view .suggested-articles, #article-view .suggested-list, #article-view .suggested-list > *')];
        const offenders = roots.filter(visible).filter((element) => {
          const rect = element.getBoundingClientRect();
          return rect.left < -0.75 || rect.right > innerWidth + 0.75;
        }).map((element) => ({ tag: element.tagName, id: element.id, className: element.className, rect: element.getBoundingClientRect().toJSON() }));
        const controls = [...document.querySelectorAll('#article-view button:not([hidden]), #article-view input:not([hidden]), #article-view select:not([hidden])')]
          .filter(visible)
          .map((element) => ({ label: element.getAttribute('aria-label') || element.textContent.trim(), width: element.getBoundingClientRect().width, height: element.getBoundingClientRect().height }))
          .filter((control) => control.width < 44 || control.height < 44);
        const bilingual = [...document.querySelectorAll('#suggested-title .localized-copy')].some((pair) => {
          const en = pair.querySelector('[lang="en"]');
          const yue = pair.querySelector('[lang="zh-Hant"]');
          return en && yue && getComputedStyle(en).display !== 'none' && getComputedStyle(yue).display !== 'none';
        });
        return {
          innerWidth, dpr: devicePixelRatio,
          htmlOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          bodyOverflow: document.body.scrollWidth - document.body.clientWidth,
          offenders, undersizedControls: controls, bilingual,
          articleCards: document.querySelectorAll('#article-grid .article-card').length,
        };
      })()`);
      await cdp.evaluate(`(() => {
        document.querySelector('#tab-features').click();
        document.querySelector('#feature-regex-builder').open = true;
      })()`);
      await delay(50);
      const builderMetrics = await cdp.evaluate(`(() => {
        const builder = document.querySelector('#feature-regex-builder');
        const rect = builder.getBoundingClientRect();
        const controls = [...builder.querySelectorAll('button')].map((button) => ({
          label: button.getAttribute('aria-label') || button.textContent.trim(),
          width: button.getBoundingClientRect().width,
          height: button.getBoundingClientRect().height,
        })).filter((control) => control.width < 44 || control.height < 44);
        const pair = builder.querySelector('.regex-guide-title .localized-copy');
        return {
          htmlOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          bodyOverflow: document.body.scrollWidth - document.body.clientWidth,
          outside: rect.left < -0.75 || rect.right > innerWidth + 0.75,
          guidedCount: builder.querySelectorAll('.regex-guide button').length,
          actionCount: builder.querySelectorAll('.regex-actions button').length,
          undersizedControls: controls,
          bilingual: pair && [...pair.children].every((node) => getComputedStyle(node).display !== 'none'),
        };
      })()`);
      if (
        metrics.innerWidth !== width
        || !dprMatches(metrics.dpr, dpr)
        || metrics.htmlOverflow > 0
        || metrics.bodyOverflow > 0
        || metrics.offenders.length
        || metrics.undersizedControls.length
        || !metrics.bilingual
        || metrics.articleCards !== 18
        || builderMetrics.htmlOverflow > 0
        || builderMetrics.bodyOverflow > 0
        || builderMetrics.outside
        || builderMetrics.guidedCount !== 6
        || builderMetrics.actionCount !== 2
        || builderMetrics.undersizedControls.length
        || !builderMetrics.bilingual
      ) {
        throw new Error(`Overflow/accessibility matrix failed: ${JSON.stringify({ width, scale, dpr, metrics, builderMetrics })}`);
      }
      matrices.push({ width, scale, dpr, article: metrics, builder: builderMetrics });
    }
  }
}

await cdp.send('Emulation.clearDeviceMetricsOverride');
const report = {
  schemaVersion: 1,
  origin: origin.href,
  releaseVisibility: { verified, unverified, invalidUrls: invalidUrlVisibility, failure },
  interactions,
  articleLanguageChecks,
  bilingualHeader,
  matrices,
};
if (reportPath) await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
console.log(`Chromium site contract verified: ${articleLanguageChecks.length} article/language routes, ${matrices.length} overflow cases, 4 palette destinations, Escape restoration, and 7 release states`);
cdp.socket.close();
