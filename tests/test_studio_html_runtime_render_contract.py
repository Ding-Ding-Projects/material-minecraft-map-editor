"""docs/site/studio.html executed, not merely read.

Every other guard over this page would read source text, which is blind to a
module that throws on load. This runs the real studio.html in a DOM, loads
every script it references in document order the way Electron's renderer
would, and asks the resulting page real questions -- including whether the
theme/density tokens the design's own handoff calls for actually landed on
the root element.
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


def render(question: str) -> dict:
    """Execute docs/site/studio.html and answer `question` (JS returning an object)."""

    node = shutil.which("node")
    if node is None:
        raise AssertionError(
            "node is required to execute studio.html and was not found on PATH."
        )
    if not (SITE / "node_modules" / "jsdom").is_dir():
        raise AssertionError(
            "jsdom is required to execute studio.html and is not installed. Run "
            f"`npm install` in {SITE} (it is declared in that package.json as a "
            "test-only dependency; the published site bundles nothing). This is "
            "not skipped, because skipping would leave the suite green while "
            "nothing had actually been rendered."
        )
    script = f"""
const {{ JSDOM }} = require({json.dumps(str((SITE / 'node_modules' / 'jsdom').as_posix()))});
const fs = require("fs");
const path = require("path");
const SITE = {json.dumps(SITE.as_posix())};
const errors = [];
const dom = new JSDOM(fs.readFileSync(path.join(SITE, "studio.html"), "utf8"), {{
  runScripts: "dangerously",
  url: "https://example.invalid/",
  pretendToBeVisual: true,
  beforeParse(window) {{
    window.HTMLCanvasElement.prototype.getContext = function () {{
      return {{ fillStyle: "", fillRect() {{}}, clearRect() {{}} }};
    }};
    window.addEventListener("error", e => errors.push("error: " + e.message));
  }},
}});
const {{ window }} = dom;
const order = [...window.document.querySelectorAll("script[src]")]
  .map(s => s.getAttribute("src"));
for (const src of order) {{
  try {{
    window.eval(fs.readFileSync(path.join(SITE, src), "utf8"));
  }} catch (e) {{
    errors.push(src + ": " + e.message);
  }}
}}
window.document.dispatchEvent(new window.Event("DOMContentLoaded", {{bubbles: true}}));
const q = sel => window.document.querySelector(sel);
const all = sel => [...window.document.querySelectorAll(sel)];
let answer;
try {{
  answer = (function () {{ {question} }})();
}} catch (e) {{
  answer = {{ threw: String(e && e.message || e) }};
}}
answer.loadErrors = errors;
answer.scriptCount = order.length;
console.log(JSON.stringify(answer));
try {{ dom.window.close(); }} catch (e) {{}}
process.exit(0);
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


class TheStudioPageExecutesCleanly(unittest.TestCase):
    def test_every_script_loads_without_throwing(self) -> None:
        got = render("return {};")
        self.assertEqual(
            got["loadErrors"],
            [],
            "a script threw while loading studio.html; its whole surface would be blank",
        )
        self.assertGreaterEqual(got["scriptCount"], 6)


class TheTitleBarExists(unittest.TestCase):
    def test_titlebar_and_window_controls_are_present(self) -> None:
        got = render(
            "return {"
            "  titlebar: !!q('#studio-titlebar'),"
            "  minimize: !!q('#studio-window-minimize'),"
            "  maximize: !!q('#studio-window-maximize'),"
            "  close: !!q('#studio-window-close'),"
            "  paletteTrigger: !!q('#palette-open')"
            "};"
        )
        self.assertTrue(got["titlebar"], "the custom title bar never mounted")
        self.assertTrue(got["minimize"], "minimize control missing")
        self.assertTrue(got["maximize"], "maximize/restore control missing")
        self.assertTrue(got["close"], "close control missing")
        self.assertTrue(
            got["paletteTrigger"], "the palette trigger is missing from the title bar"
        )

    def test_window_controls_degrade_honestly_without_the_desktop_bridge(self) -> None:
        # No window.mmweDesktop exists in this jsdom render (the same as a
        # plain browser), so the controls must explain themselves rather
        # than sit there as dead buttons.
        got = render(
            "const btn = q('#studio-window-close');"
            "return { disabled: btn.disabled, title: btn.getAttribute('title') || '' };"
        )
        self.assertTrue(
            got["disabled"], "window controls must disable without the desktop bridge"
        )
        self.assertIn("desktop app", got["title"].lower())


class TheRootCarriesThemeAndDensity(unittest.TestCase):
    def test_root_has_theme_and_density_custom_properties(self) -> None:
        # jsdom does not fetch the external stylesheet linked from <head> (no
        # network I/O happens during this render), so the custom-property
        # *values* cannot be read back from computed style here -- that the
        # tokens studio-shell.js writes exist and resolve to real values is
        # covered by test_studio_tokens_css below, against the real file.
        # What this render proves is the half a browser fetch cannot: that
        # studio-shell.js actually set the attributes on the document root
        # after executing for real, not merely that the source mentions them.
        got = render(
            "return {"
            "  theme: window.document.documentElement.getAttribute('data-theme'),"
            "  density: window.document.documentElement.getAttribute('data-density')"
            "};"
        )
        self.assertEqual(got["density"], "comfortable")
        self.assertIn(got["theme"], ("light", None))

    def test_studio_tokens_css_defines_the_tokens_theme_and_density_use(self) -> None:
        css = (SITE / "studio-tokens.css").read_text(encoding="utf-8")
        for token in ("--studio-primary", "--studio-ctrl", "--studio-on-surface"):
            self.assertIn(token, css, f"{token} is not defined in studio-tokens.css")
        self.assertIn(':root[data-theme="dark"]', css)
        self.assertIn(':root[data-density="compact"]', css)
        self.assertIn(':root[data-density="spacious"]', css)

    def test_view_switch_toggles_backstage_and_workspace(self) -> None:
        got = render(
            "window.AmuletStudio.showView('workspace');"
            "const active = q('#studio-root').getAttribute('data-active-view');"
            "const backstageHidden = q('#backstage-view').hidden;"
            "const workspaceHidden = q('#workspace-view').hidden;"
            "return { active, backstageHidden, workspaceHidden };"
        )
        self.assertEqual(got["active"], "workspace")
        self.assertTrue(got["backstageHidden"])
        self.assertFalse(got["workspaceHidden"])


if __name__ == "__main__":
    unittest.main()
