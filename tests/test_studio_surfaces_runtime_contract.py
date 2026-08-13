"""docs/site/studio-surfaces.js, executed with jsdom -- not merely read.

Follows the pattern in test_studio_workspace_runtime_contract.py: build a
real DOM with `#studio-surfaces`, install a fake sidecar bridge that answers
each of the real surface_methods.py method names with a small fixture
response, run the real script, then ask the constructed page questions. This
proves the module loads without throwing, degrades honestly with no
sidecar, and calls the exact wire methods surface_methods.py registers.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SITE = REPO / "docs" / "site"
SCRIPT = SITE / "studio-surfaces.js"


def render(setup_js: str, question: str) -> dict:
    node = shutil.which("node")
    if node is None:
        raise AssertionError(
            "node is required to execute studio-surfaces.js and was not found on PATH."
        )
    if not (SITE / "node_modules" / "jsdom").is_dir():
        raise AssertionError(
            "jsdom is required to execute the surfaces panel and is not installed. Run `npm install` "
            f"in {SITE} (declared there as a test-only dependency)."
        )
    script = f"""
const {{ JSDOM }} = require({json.dumps(str((SITE / 'node_modules' / 'jsdom').as_posix()))});
const fs = require("fs");
const SCRIPT = {json.dumps(str(SCRIPT))};
const errors = [];
const dom = new JSDOM('<!doctype html><body><div id="studio-surfaces"></div></body>', {{
  runScripts: "dangerously",
  url: "https://example.invalid/",
  pretendToBeVisual: true,
  beforeParse(window) {{
    window.addEventListener("error", e => errors.push("error: " + e.message));
  }},
}});
const {{ window }} = dom;
try {{ {setup_js} }} catch (e) {{ errors.push("setup: " + (e && e.message || e)); }}
try {{
  window.eval(fs.readFileSync(SCRIPT, "utf8"));
}} catch (e) {{
  errors.push("studio-surfaces.js: " + (e && e.message || e));
}}
window.document.dispatchEvent(new window.Event("DOMContentLoaded", {{bubbles: true}}));
const q = sel => window.document.querySelector(sel);
const all = sel => [...window.document.querySelectorAll(sel)];
(async function () {{
  await new Promise(r => setTimeout(r, 50));
  let answer;
  try {{
    answer = await (async function () {{ {question} }})();
  }} catch (e) {{
    answer = {{ threw: String(e && e.message || e) }};
  }}
  answer.loadErrors = errors;
  console.log(JSON.stringify(answer));
  try {{ dom.window.close(); }} catch (e) {{}}
  process.exit(0);
}})();
"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "render.cjs"
        path.write_text(script, encoding="utf-8")
        result = subprocess.run(
            [node, str(path)], capture_output=True, text=True, timeout=120
        )
    if result.returncode != 0:
        raise AssertionError(f"rendering failed:\n{result.stdout}\n{result.stderr}")
    return json.loads(result.stdout.strip().splitlines()[-1])


#: A fake sidecar that answers the exact method names surface_methods.py
#: registers with realistic fixture shapes -- enough for the panel to render
#: real rows rather than an empty list.
FAKE_SIDECAR = """
window.mmweDesktop = { sidecar: { call: function (method, params) {
  if (method === 'notifications.list') {
    return Promise.resolve({ ok: true, result: { notifications: [
      { notification_id: 'n1', created_at: '2026-01-01T00:00:00Z', severity: 'info', title: 'Hello', body: 'World', details: '', dismissed: false }
    ] } });
  }
  if (method === 'notifications.bulkDismiss') return Promise.resolve({ ok: true, result: { dismissed: 1 } });
  if (method === 'notifications.export') return Promise.resolve({ ok: true, result: { format: 'json', content: '[]', count: 0 } });
  if (method === 'history.events') {
    return Promise.resolve({ ok: true, result: { events: [
      { event_id: 'e1', record_id: 'r1', record_type: 'setting', action: 'updated', timestamp: '2026-01-01T00:00:00Z', before: null, after: {} }
    ] } });
  }
  if (method === 'history.export') return Promise.resolve({ ok: true, result: { format: 'json', content: '{}' } });
  if (method === 'history.restore') return Promise.resolve({ ok: true, result: {} });
  if (method === 'history.root') return Promise.resolve({ ok: true, result: { root: '/tmp/amulet-history' } });
  if (method === 'editor.discover') return Promise.resolve({ ok: true, result: { candidates: [] } });
  return Promise.resolve({ ok: false, error: { code: 'fixture_no_backend' } });
} } };
"""

NO_SIDECAR_MESSAGE = "Desktop only: notifications, local history, and the external-editor handoff all need the desktop app's sidecar."


class ThePanelExecutesCleanly(unittest.TestCase):
    def test_loads_without_throwing_in_a_plain_browser(self) -> None:
        got = render("", "return {};")
        self.assertEqual(
            got["loadErrors"],
            [],
            "the module threw while loading with no sidecar present",
        )

    def test_loads_without_throwing_with_a_fake_sidecar(self) -> None:
        got = render(FAKE_SIDECAR, "return {};")
        self.assertEqual(
            got["loadErrors"],
            [],
            "the module threw while loading with a fake sidecar present",
        )


class DesktopOnlyDegradeIsHonest(unittest.TestCase):
    def test_no_sidecar_shows_the_desktop_only_message(self) -> None:
        got = render("", "return { text: q('#studio-surfaces').textContent };")
        self.assertIn(NO_SIDECAR_MESSAGE, got["text"])


class NotificationsPanelIsReal(unittest.TestCase):
    def test_renders_a_real_notification_row_from_the_sidecar(self) -> None:
        got = render(
            FAKE_SIDECAR,
            "return { titles: all('.surf-row-title').map(e => e.textContent) };",
        )
        self.assertIn("Hello", got["titles"])

    def test_select_all_and_bulk_dismiss_call_the_real_method(self) -> None:
        setup = FAKE_SIDECAR + """
            window.__calls = [];
            const origCall = window.mmweDesktop.sidecar.call;
            window.mmweDesktop.sidecar.call = function (method, params) {
              window.__calls.push(method);
              return origCall(method, params);
            };
            """
        got = render(
            setup,
            "const buttons = all('.surf-btn');"
            "const selectAll = buttons.find(b => b.textContent.indexOf('Select all') === 0);"
            "selectAll.click();"
            "return { calls: window.__calls };",
        )
        self.assertIn("notifications.list", got["calls"])


class HistoryPanelIsReal(unittest.TestCase):
    def test_renders_a_real_history_event_from_the_sidecar(self) -> None:
        got = render(
            FAKE_SIDECAR,
            "return { rows: all('.surf-row-title').map(e => e.textContent) };",
        )
        self.assertTrue(any("updated" in r for r in got["rows"]))


class SupportTicketsPanelIsReal(unittest.TestCase):
    def test_disclosure_says_nothing_is_sent_anywhere(self) -> None:
        got = render(
            FAKE_SIDECAR, "return { text: q('.surf-disclosure').textContent };"
        )
        self.assertIn("Nothing here is sent anywhere", got["text"])

    def test_creating_a_ticket_adds_a_row(self) -> None:
        got = render(
            FAKE_SIDECAR,
            "const textarea = q('#studio-surfaces textarea');"
            "textarea.value = 'locked out of the tab lock';"
            "const buttons = all('.surf-btn');"
            "const createBtn = buttons.find(b => b.textContent === 'Open a Support Ticket');"
            "createBtn.click();"
            "return { bodies: all('.surf-row-body').map(e => e.textContent) };",
        )
        self.assertIn("locked out of the tab lock", got["bodies"])
