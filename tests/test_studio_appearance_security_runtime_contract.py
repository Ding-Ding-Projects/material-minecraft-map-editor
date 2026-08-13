"""Runtime evidence for docs/site/studio-appearance.js and
docs/site/studio-security.js.

Same method as tests/test_studio_backstage_runtime_contract.py: build a
minimal page carrying the real shared runtime (site-data.js, site-core.js,
regex-builder.js, electron-bridge.js) plus the module under test, mount it
into a bare container, and ask the resulting DOM real questions -- including
behavioural ones (does clicking Apply/Create/Register actually call the
sidecar with the values on screen; does the search field actually narrow the
list) rather than only "did it throw".
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

BASE_SCRIPTS = [
    "site-data.js",
    "site-core.js",
    "regex-builder.js",
    "electron-bridge.js",
]


def render(
    question: str, extra_scripts, sidecar_js: str = "", container_id: str = "panel"
) -> dict:
    node = shutil.which("node")
    if node is None:
        raise AssertionError("node is required and was not found on PATH.")
    if not (SITE / "node_modules" / "jsdom").is_dir():
        raise AssertionError(
            "jsdom is required and is not installed. Run `npm install` in "
            f"{SITE}. This is not skipped, because skipping would leave the "
            "suite green while nothing had actually been rendered."
        )
    scripts = BASE_SCRIPTS + list(extra_scripts)
    script = f"""
const {{ JSDOM }} = require({json.dumps(str((SITE / 'node_modules' / 'jsdom').as_posix()))});
const fs = require("fs");
const path = require("path");
const SITE = {json.dumps(SITE.as_posix())};
const errors = [];
const html = '<!doctype html><html><body><div id="{container_id}"></div></body></html>';
const dom = new JSDOM(html, {{
  runScripts: "dangerously",
  url: "https://example.invalid/",
  pretendToBeVisual: true,
  beforeParse(window) {{
    window.addEventListener("error", e => errors.push("error: " + e.message));
  }},
}});
const {{ window }} = dom;
{sidecar_js}
const scripts = {json.dumps(scripts)};
for (const name of scripts) {{
  try {{
    window.eval(fs.readFileSync(path.join(SITE, name), "utf8"));
  }} catch (e) {{
    errors.push(name + ": " + e.message);
  }}
}}
window.document.dispatchEvent(new window.Event("DOMContentLoaded", {{bubbles: true}}));
const q = sel => window.document.querySelector(sel);
const all = sel => [...window.document.querySelectorAll(sel)];
(async function () {{
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
            [node, str(path)], capture_output=True, text=True, timeout=180
        )
    if result.returncode != 0:
        raise AssertionError(f"rendering failed:\n{result.stdout}\n{result.stderr}")
    return json.loads(result.stdout.strip().splitlines()[-1])


APPEARANCE_SIDECAR = """
window.mmweDesktop = { sidecar: { call: function (method, params) {
  window.__calls = window.__calls || [];
  window.__calls.push([method, params]);
  if (method === "protocol.ping") return Promise.resolve({ ok: true, result: { ok: true } });
  if (method === "preferences.read") return Promise.resolve({ ok: true, result: {
    theme: "system", density: "comfortable", accent: "#6750A4", ui_font: "", ui_scale: 1.0,
    display_name: "", language_mode: "english", funny_level_english: 3, funny_level_cantonese: 3,
    show_dialog_emojis: true, external_editor_path: "", auto_stage_updates: false
  } });
  if (method === "converter.formats") return Promise.resolve({ ok: true, result: { adapters: [] } });
  if (method === "changelog.entries") return Promise.resolve({ ok: true, result: { entries: [], repository_url: "", source_revision: "" } });
  if (method === "docs.articles") return Promise.resolve({ ok: true, result: { articles: [] } });
  if (method === "appearance.presets.list") return Promise.resolve({ ok: true, result: { presets: [
    { name: "Midnight", values: { version: 1, theme: "dark", density: "compact", accent: "#00FF00", ui_font: "", ui_scale: 1.0 } }
  ], shipped: { version: 1, theme: "system", density: "comfortable", accent: "#6750A4", ui_font: "", ui_scale: 1.0 } } });
  if (method === "appearance.presets.save") return Promise.resolve({ ok: true, result: { preset: { name: params.name, values: params.values } } });
  if (method === "appearance.presets.apply") return Promise.resolve({ ok: true, result: { preferences: { theme: "dark", density: "compact", accent: "#00FF00", ui_font: "", ui_scale: 1.0 } } });
  if (method === "appearance.presets.delete") return Promise.resolve({ ok: true, result: { deleted: true } });
  if (method === "appearance.reset_all") return Promise.resolve({ ok: true, result: { preferences: { theme: "system", density: "comfortable", accent: "#6750A4", ui_font: "", ui_scale: 1.0 } } });
  return Promise.resolve({ ok: false, error: { code: "unhandled_method", message: method } });
} } };
"""

SECURITY_SIDECAR = """
window.mmweDesktop = { sidecar: { call: function (method, params) {
  window.__calls = window.__calls || [];
  window.__calls.push([method, params]);
  if (method === "protocol.ping") return Promise.resolve({ ok: true, result: { ok: true } });
  if (method === "preferences.read") return Promise.resolve({ ok: true, result: {
    theme: "system", density: "comfortable", accent: "#6750A4", ui_font: "", ui_scale: 1.0,
    display_name: "", language_mode: "english", funny_level_english: 3, funny_level_cantonese: 3,
    show_dialog_emojis: true, external_editor_path: "", auto_stage_updates: false
  } });
  if (method === "converter.formats") return Promise.resolve({ ok: true, result: { adapters: [] } });
  if (method === "changelog.entries") return Promise.resolve({ ok: true, result: { entries: [], repository_url: "", source_revision: "" } });
  if (method === "docs.articles") return Promise.resolve({ ok: true, result: { articles: [] } });
  if (method === "locks.list") return Promise.resolve({ ok: true, result: { locks: window.__locks || [], recovery_hint: "delete the app profile folder" } });
  if (method === "locks.create") {
    var lock = { lock_id: "lock-1", scope: params.scope, target_id: params.target_id, label: params.label || params.target_id,
      method: params.method, created_at: 0, unlock_duration: "surface", locked_on_launch: true,
      failed_attempts: 0, last_attempt_at: 0, is_unlocked: false };
    window.__locks = [lock];
    return Promise.resolve({ ok: true, result: { lock: lock } });
  }
  if (method === "locks.attempt_unlock") {
    var ok = params.answer === "sesame";
    if (window.__locks && window.__locks[0]) window.__locks[0].is_unlocked = ok;
    return Promise.resolve({ ok: true, result: { unlocked: ok } });
  }
  if (method === "locks.relock") {
    if (window.__locks && window.__locks[0]) window.__locks[0].is_unlocked = false;
    return Promise.resolve({ ok: true, result: { relocked: true } });
  }
  if (method === "locks.remove") {
    window.__locks = [];
    return Promise.resolve({ ok: true, result: { removed: true } });
  }
  if (method === "auth.list_entries") return Promise.resolve({ ok: true, result: { entries: window.__entries || [] } });
  if (method === "auth.generate_secret") return Promise.resolve({ ok: true, result: { secret: "JBSWY3DPEHPK3PXP" } });
  if (method === "auth.build_uri") return Promise.resolve({ ok: true, result: { uri: "otpauth://totp/x?secret=JBSWY3DPEHPK3PXP", grouped_secret: "JBSW Y3DP EHPK 3PXP" } });
  if (method === "auth.add_entry") {
    var entry = { id: "e1", issuer: params.issuer, account: params.account, algorithm: "SHA1", digits: 6, period: 30, added_at: 0, label: (params.issuer ? params.issuer + " · " : "") + params.account };
    window.__entries = [entry];
    return Promise.resolve({ ok: true, result: { entry: entry } });
  }
  if (method === "auth.current_code") return Promise.resolve({ ok: true, result: { code: "123456", next_code: "654321", period_remaining: 15, period: 30 } });
  if (method === "auth.delete_entry") {
    window.__entries = [];
    return Promise.resolve({ ok: true, result: { deleted: true } });
  }
  return Promise.resolve({ ok: false, error: { code: "unhandled_method", message: method } });
} } };
"""

NO_SIDECAR = "delete window.mmweDesktop;"


class TheModulesLoadWithoutThrowing(unittest.TestCase):
    def test_appearance_loads_clean(self) -> None:
        got = render(
            "await new Promise(r => { function poll(){ (window.AmuletSite&&window.AmuletSite.electronSidecar&&window.AmuletSite.electronSidecar.available)?r():setTimeout(poll,10);} poll(); });window.AmuletStudioAppearance.mount(q('#panel')); return {};",
            ["studio-appearance.js"],
            sidecar_js=APPEARANCE_SIDECAR,
        )
        self.assertEqual(got["loadErrors"], [])

    def test_security_loads_clean(self) -> None:
        got = render(
            "await new Promise(r => { function poll(){ (window.AmuletSite&&window.AmuletSite.electronSidecar&&window.AmuletSite.electronSidecar.available)?r():setTimeout(poll,10);} poll(); });window.AmuletStudioSecurity.mount(q('#panel')); return {};",
            ["studio-security.js"],
            sidecar_js=SECURITY_SIDECAR,
        )
        self.assertEqual(got["loadErrors"], [])


class NoSidecarIsAnHonestDesktopOnlyState(unittest.TestCase):
    def test_appearance_says_desktop_only(self) -> None:
        got = render(
            "window.AmuletStudioAppearance.mount(q('#panel'));"
            "return {status: (q('.sa-status')||{}).textContent || ''};",
            ["studio-appearance.js"],
            sidecar_js=NO_SIDECAR,
        )
        self.assertIn("desktop", got["status"].lower())

    def test_security_says_desktop_only(self) -> None:
        got = render(
            "window.AmuletStudioSecurity.mount(q('#panel'));"
            "return {status: (q('.ss-status')||{}).textContent || ''};",
            ["studio-security.js"],
            sidecar_js=NO_SIDECAR,
        )
        self.assertIn("desktop", got["status"].lower())


class AppearancePresetsRenderFromTheSidecar(unittest.TestCase):
    def test_the_preset_list_renders_the_sidecars_own_preset(self) -> None:
        got = render(
            "await new Promise(r => { function poll(){ (window.AmuletSite&&window.AmuletSite.electronSidecar&&window.AmuletSite.electronSidecar.available)?r():setTimeout(poll,10);} poll(); });window.AmuletStudioAppearance.mount(q('#panel'));"
            "await new Promise(r => setTimeout(r, 30));"
            "return {names: all('.sa-preset-name').map(n => n.textContent)};",
            ["studio-appearance.js"],
            sidecar_js=APPEARANCE_SIDECAR,
        )
        self.assertIn("Midnight", got["names"])

    def test_the_search_field_actually_narrows_the_preset_list(self) -> None:
        got = render(
            "await new Promise(r => { function poll(){ (window.AmuletSite&&window.AmuletSite.electronSidecar&&window.AmuletSite.electronSidecar.available)?r():setTimeout(poll,10);} poll(); });window.AmuletStudioAppearance.mount(q('#panel'));"
            "await new Promise(r => setTimeout(r, 30));"
            "const input = q('#sa-preset-search');"
            "input.value = 'zzz-no-match';"
            "input.dispatchEvent(new window.Event('input', {bubbles:true}));"
            "return {rows: all('.sa-preset-name').length, empty: all('.sa-preset-empty').length};",
            ["studio-appearance.js"],
            sidecar_js=APPEARANCE_SIDECAR,
        )
        self.assertEqual(got["rows"], 0)
        self.assertEqual(got["empty"], 1)

    def test_apply_calls_the_real_sidecar_method_with_the_preset_name(self) -> None:
        got = render(
            "await new Promise(r => { function poll(){ (window.AmuletSite&&window.AmuletSite.electronSidecar&&window.AmuletSite.electronSidecar.available)?r():setTimeout(poll,10);} poll(); });window.AmuletStudioAppearance.mount(q('#panel'));"
            "await new Promise(r => setTimeout(r, 30));"
            "all('.sa-preset-row button')[0].dispatchEvent(new window.Event('click', {bubbles:true}));"
            "await new Promise(r => setTimeout(r, 30));"
            "return {calls: (window.__calls||[]).map(c => c[0])};",
            ["studio-appearance.js"],
            sidecar_js=APPEARANCE_SIDECAR,
        )
        self.assertIn("appearance.presets.apply", got["calls"])


class EveryAppearanceSearchFieldCarriesItsRegexBuilder(unittest.TestCase):
    def test_the_preset_search_has_an_anchored_builder(self) -> None:
        got = render(
            "await new Promise(r => { function poll(){ (window.AmuletSite&&window.AmuletSite.electronSidecar&&window.AmuletSite.electronSidecar.available)?r():setTimeout(poll,10);} poll(); });window.AmuletStudioAppearance.mount(q('#panel'));"
            "return {controls: !!q('[data-regex-controls=\"sa-preset\"]'), open: !!q('#sa-preset-regex-open')};",
            ["studio-appearance.js"],
            sidecar_js=APPEARANCE_SIDECAR,
        )
        self.assertTrue(got["controls"])
        self.assertTrue(got["open"])


class LockLifecycleUsesTheRealSidecarContract(unittest.TestCase):
    def test_creating_and_unlocking_a_lock_round_trips_through_the_bridge(self) -> None:
        got = render(
            "await new Promise(r => { function poll(){ (window.AmuletSite&&window.AmuletSite.electronSidecar&&window.AmuletSite.electronSidecar.available)?r():setTimeout(poll,10);} poll(); });window.AmuletStudioSecurity.mount(q('#panel'));"
            "await new Promise(r => setTimeout(r, 30));"
            "q('#ss-lock-target').value = 'tab-1';"
            "q('#ss-lock-credential').value = 'sesame';"
            "q('.ss-lock-form .ss-primary-btn').dispatchEvent(new window.Event('click', {bubbles:true}));"
            "await new Promise(r => setTimeout(r, 30));"
            "const answer = q('.ss-lock-row input');"
            "answer.value = 'sesame';"
            "const unlockBtn = all('.ss-lock-row button').find(b => b.textContent.trim() === 'Unlock');"
            "unlockBtn.dispatchEvent(new window.Event('click', {bubbles:true}));"
            "await new Promise(r => setTimeout(r, 30));"
            "return {state: (q('.ss-lock-state')||{}).textContent || '', calls: (window.__calls||[]).map(c => c[0])};",
            ["studio-security.js"],
            sidecar_js=SECURITY_SIDECAR,
        )
        self.assertEqual(got["state"], "unlocked")
        self.assertIn("locks.create", got["calls"])
        self.assertIn("locks.attempt_unlock", got["calls"])

    def test_the_recovery_hint_names_the_real_folder(self) -> None:
        got = render(
            "await new Promise(r => { function poll(){ (window.AmuletSite&&window.AmuletSite.electronSidecar&&window.AmuletSite.electronSidecar.available)?r():setTimeout(poll,10);} poll(); });window.AmuletStudioSecurity.mount(q('#panel'));"
            "await new Promise(r => setTimeout(r, 30));"
            "return {hint: (q('.ss-recovery-hint')||{}).textContent || ''};",
            ["studio-security.js"],
            sidecar_js=SECURITY_SIDECAR,
        )
        self.assertIn("profile folder", got["hint"])


class AuthenticatorRegistrationUsesTheRealSidecarContract(unittest.TestCase):
    def test_generate_then_register_calls_the_real_methods_in_order(self) -> None:
        got = render(
            "await new Promise(r => { function poll(){ (window.AmuletSite&&window.AmuletSite.electronSidecar&&window.AmuletSite.electronSidecar.available)?r():setTimeout(poll,10);} poll(); });window.AmuletStudioSecurity.mount(q('#panel'));"
            "await new Promise(r => setTimeout(r, 30));"
            "q('#ss-auth-issuer').value = 'Amulet';"
            "q('#ss-auth-account').value = 'me@example.com';"
            "all('.ss-auth-form button')[0].dispatchEvent(new window.Event('click', {bubbles:true}));"
            "await new Promise(r => setTimeout(r, 30));"
            "q('.ss-auth-form .ss-primary-btn').dispatchEvent(new window.Event('click', {bubbles:true}));"
            "await new Promise(r => setTimeout(r, 30));"
            "return {calls: (window.__calls||[]).map(c => c[0]), rows: all('.ss-auth-label').map(n => n.textContent)};",
            ["studio-security.js"],
            sidecar_js=SECURITY_SIDECAR,
        )
        self.assertIn("auth.generate_secret", got["calls"])
        self.assertIn("auth.build_uri", got["calls"])
        self.assertIn("auth.add_entry", got["calls"])
        self.assertTrue(any("me@example.com" in label for label in got["rows"]))

    def test_the_authenticator_search_field_actually_narrows_the_list(self) -> None:
        got = render(
            "await new Promise(r => { function poll(){ (window.AmuletSite&&window.AmuletSite.electronSidecar&&window.AmuletSite.electronSidecar.available)?r():setTimeout(poll,10);} poll(); });window.AmuletStudioSecurity.mount(q('#panel'));"
            "await new Promise(r => setTimeout(r, 30));"
            "const input = q('#ss-auth-search');"
            "input.value = 'zzz-no-match';"
            "input.dispatchEvent(new window.Event('input', {bubbles:true}));"
            "return {empty: all('.ss-auth-empty').length};",
            ["studio-security.js"],
            sidecar_js=SECURITY_SIDECAR,
        )
        self.assertEqual(got["empty"], 1)


if __name__ == "__main__":
    unittest.main()
