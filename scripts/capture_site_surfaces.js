/**
 * Photograph the published site's surfaces from a real browser, headlessly.
 *
 * The site had every other kind of evidence and no pictures. Its runtime
 * contract test executes the real scripts in jsdom, which proves the page does
 * not throw on load -- and jsdom has no renderer at all, so it can say nothing
 * about whether anything is visible. A surface can pass every one of those
 * assertions while rendering as a blank column.
 *
 * So this drives an actual browser. Two deliberate choices:
 *
 * 1. It uses the browser already installed on the machine (Edge ships with
 *    Windows; Chrome is taken if present) rather than downloading one. A
 *    capture harness that needs a 150 MB install is a harness nobody runs.
 * 2. It speaks the DevTools protocol over Node's own global WebSocket, which
 *    Node has carried since 22. No dependency is added to this repository for
 *    it, which matters because the published site bundles nothing and must
 *    keep bundling nothing.
 *
 * Headless is not an optimisation here, it is the requirement: a capture run
 * must never take the foreground window or the pointer away from whoever is
 * using the machine.
 *
 * Usage:
 *   node scripts/capture_site_surfaces.js [--out docs/huishots/site]
 */

const fs = require("fs");
const path = require("path");
const os = require("os");
const { spawn } = require("child_process");

const REPO = path.resolve(__dirname, "..");
const SITE = path.join(REPO, "docs", "site");

/** Where a browser might be, most preferred first. */
const CANDIDATES = [
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
];

/**
 * The surfaces to photograph.
 *
 * `open` is evaluated in the page before the shot and must return once the
 * surface is on screen. It drives the site through its own controls rather
 * than reaching into its internals, because a capture taken by calling a
 * private function proves the function draws, not that a user can get there.
 */
/**
 * Every tab panel the site has, activated through its own tab button.
 *
 * These are read off the page rather than invented. The first version of this
 * list guessed at `[data-route="settings"]` and `a[href="#settings"]`, neither
 * of which exists here: the site is a tab strip over nine `role="tabpanel"`
 * sections, and a panel is HIDDEN until its tab is chosen. Scrolling to a
 * hidden section moves nothing, which is why those captures came back as the
 * home page again.
 */
const TAB_PANELS = [
  ["features", "The features tab"],
  ["docs", "The documentation tab with its article index"],
  ["screenshots", "The screenshots tab"],
  ["guides", "The guides tab"],
  ["community", "The community tab"],
  ["changelog", "The changelog tab with its date filter and search"],
  ["history", "The history tab"],
  ["settings", "The settings tab: its search field and its grid of live controls"],
  ["security", "The security tab: the built-in authenticator and the per-surface locks"],
];

const SURFACES = [
  { name: "home", alt: "The site's home page as it first loads", open: null },
  ...TAB_PANELS.map(([id, alt]) => ({
    name: `tab-${id}`,
    alt: `${alt}, reached through the site's own tab strip`,
    open: `document.getElementById('tab-${id}').click()`,
  })),
  {
    name: "command-palette",
    alt: "The command palette open over the site, its results carrying live inline controls",
    open: `document.getElementById('palette-open').click()`,
  },
  {
    name: "regex-builder",
    alt: "The regex builder anchored beside the settings search field",
    open: `document.getElementById('tab-settings').click();
           document.getElementById('settings-regex-open').click()`,
  },
  {
    name: "tab-search-regex-builder",
    alt: "The tab strip's own search field with its anchored regex builder open",
    open: `document.getElementById('tab-regex-open').click()`,
  },
];

const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900 },
  // A phone width, because most people who open a documentation link open it
  // on one, and a side tab strip is exactly what breaks there.
  { name: "mobile", width: 390, height: 844 },
];

function findBrowser() {
  for (const candidate of CANDIDATES) {
    if (fs.existsSync(candidate)) return candidate;
  }
  throw new Error(
    "No installed browser found. Looked for Edge and Chrome in their usual " +
      "locations:\n  " +
      CANDIDATES.join("\n  ")
  );
}

async function cdp(wsUrl) {
  const socket = new WebSocket(wsUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  let nextId = 1;
  const waiting = new Map();
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    const pending = waiting.get(message.id);
    if (!pending) return;
    waiting.delete(message.id);
    if (message.error) pending.reject(new Error(JSON.stringify(message.error)));
    else pending.resolve(message.result);
  });
  return {
    send(method, params = {}) {
      const id = nextId++;
      socket.send(JSON.stringify({ id, method, params }));
      return new Promise((resolve, reject) =>
        waiting.set(id, { resolve, reject })
      );
    },
    close: () => socket.close(),
  };
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function main() {
  const outIndex = process.argv.indexOf("--out");
  const outDir = path.resolve(
    REPO,
    outIndex >= 0 ? process.argv[outIndex + 1] : "docs/huishots/site"
  );
  fs.mkdirSync(outDir, { recursive: true });

  const browser = findBrowser();
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "site-capture-"));
  const port = 9223;
  const child = spawn(
    browser,
    [
      "--headless=new",
      `--remote-debugging-port=${port}`,
      `--user-data-dir=${profile}`,
      // A fresh profile with no synced session, so nothing restores a tab over
      // the page we asked for -- a real failure mode with an ordinary profile.
      "--no-first-run",
      "--no-default-browser-check",
      "--disable-extensions",
      "--hide-scrollbars",
      "--force-device-scale-factor=1",
      "about:blank",
    ],
    { stdio: "ignore", detached: false }
  );

  const seen = new Map();
  const manifest = { captures: [], failures: [], browser, generatedBy: path.basename(__filename) };
  try {
    // Wait for the debugging endpoint rather than sleeping a guessed amount.
    let target = null;
    for (let attempt = 0; attempt < 60 && !target; attempt++) {
      try {
        const response = await fetch(`http://127.0.0.1:${port}/json/list`);
        const targets = await response.json();
        target = targets.find((t) => t.type === "page");
      } catch {
        await sleep(250);
      }
    }
    if (!target) throw new Error("the browser never exposed a debugging target");

    const client = await cdp(target.webSocketDebuggerUrl);
    await client.send("Page.enable");
    await client.send("Runtime.enable");

    for (const viewport of VIEWPORTS) {
      await client.send("Emulation.setDeviceMetricsOverride", {
        width: viewport.width,
        height: viewport.height,
        deviceScaleFactor: 1,
        mobile: viewport.width < 768,
      });

      for (const surface of SURFACES) {
        const file = `site-${surface.name}-${viewport.name}.png`;
        try {
          await client.send("Page.navigate", {
            url: "file:///" + path.join(SITE, "index.html").replace(/\\/g, "/"),
          });
          await sleep(700);
          if (surface.open) {
            const result = await client.send("Runtime.evaluate", {
              expression: surface.open,
              awaitPromise: true,
            });
            if (result.exceptionDetails) {
              throw new Error(
                "the opener threw: " +
                  (result.exceptionDetails.exception?.description ||
                    result.exceptionDetails.text)
              );
            }
            await sleep(500);
          }
          const shot = await client.send("Page.captureScreenshot", {
            format: "png",
            captureBeyondViewport: false,
          });
          const bytes = Buffer.from(shot.data, "base64");
          // A capture harness that trusts its own success is how a blank image
          // ships as evidence. A real rendered page is never this small.
          if (bytes.length < 5000) {
            throw new Error(
              `the capture is only ${bytes.length} bytes, which is a blank or ` +
                "near-blank page rather than a rendered surface"
            );
          }
          // A surface whose opener silently did nothing photographs the page
          // that was already there. The first run of this harness reported
          // "10 captured, 0 failed" while four of the ten were byte-identical
          // copies of the home page, because every selector in it was
          // invented rather than read out of the site. Nothing in a count of
          // files can see that, so the bytes are compared.
          const digest = require("crypto")
            .createHash("sha256")
            .update(bytes)
            .digest("hex");
          const twin = seen.get(digest);
          if (twin && twin.viewport === viewport.name) {
            throw new Error(
              `identical to ${twin.file} -- the opener ran without changing ` +
                "anything on screen, so this is the previous surface " +
                "photographed again rather than a new one"
            );
          }
          seen.set(digest, { file, viewport: viewport.name });
          fs.writeFileSync(path.join(outDir, file), bytes);
          manifest.captures.push({
            surface: surface.name,
            viewport: viewport.name,
            filename: file,
            bytes: bytes.length,
            alt: `${surface.alt} (${viewport.name})`,
          });
          console.log(`captured ${file} (${bytes.length} bytes)`);
        } catch (error) {
          // Recorded, never omitted. A gap nobody mentions reads as coverage.
          manifest.failures.push({
            surface: surface.name,
            viewport: viewport.name,
            reason: String(error.message || error),
          });
          console.log(`FAILED  ${file}: ${error.message || error}`);
        }
      }
    }
    client.close();
  } finally {
    child.kill();
    try {
      fs.rmSync(profile, { recursive: true, force: true });
    } catch {
      /* a locked profile directory is not worth failing a capture run over */
    }
  }

  fs.writeFileSync(
    path.join(outDir, "manifest.json"),
    JSON.stringify(manifest, null, 2) + "\n"
  );
  console.log(
    `\n${manifest.captures.length} captured, ${manifest.failures.length} failed`
  );
  // A run that captured nothing at all is a broken harness, not an empty site.
  process.exit(manifest.captures.length === 0 ? 1 : 0);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
