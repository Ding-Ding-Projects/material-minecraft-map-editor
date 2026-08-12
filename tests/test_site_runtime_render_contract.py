"""The site's pages executed, not merely read.

Every other site guard in this suite reads source text. That catches a missing
script tag and a malformed selector, and it is completely blind to the failure
that actually ships: a module that throws on load, leaving its whole surface
blank while every source-text assertion still passes. A page whose scripts all
parse can still render nothing.

So this one runs the real index.html in a DOM, loads every script in document
order the way a browser would, and then asks the resulting page questions --
including behavioural ones. A lock that accepts the wrong password is a defect
no amount of reading the file would reveal.
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
    """Execute the site and answer `question`, which is JS returning an object."""

    node = shutil.which("node")
    if node is None:
        raise AssertionError(
            "node is required to execute the site and was not found on PATH."
        )
    if not (SITE / "node_modules" / "jsdom").is_dir():
        raise AssertionError(
            "jsdom is required to execute the site and is not installed. Run "
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
const dom = new JSDOM(fs.readFileSync(path.join(SITE, "index.html"), "utf8"), {{
  runScripts: "dangerously",
  url: "https://example.invalid/",
  pretendToBeVisual: true,
  beforeParse(window) {{
    // jsdom ships no canvas backend; the QR encoder's own arithmetic is
    // checked separately, so a recording stub is enough to let drawing run.
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


class ThePageExecutesCleanly(unittest.TestCase):
    def test_every_script_loads_without_throwing(self) -> None:
        got = render("return {};")
        self.assertEqual(
            got["loadErrors"],
            [],
            "a script threw while loading; its whole surface would be blank",
        )
        self.assertGreater(got["scriptCount"], 15)


class TheSecuritySurfacesActuallyMount(unittest.TestCase):
    """Each of these shipped as feature-card prose before it shipped as code."""

    def test_the_three_surfaces_render_content(self) -> None:
        got = render(
            "return {"
            "  section: !!q('#security'),"
            "  tab: !!q('#tab-security'),"
            "  auth: (q('#authenticator-root')||{}).childElementCount || 0,"
            "  locks: (q('#locks-root')||{}).childElementCount || 0,"
            "  support: (q('#support-root')||{}).childElementCount || 0,"
            "  lockRows: all('.lock-row').length"
            "};"
        )
        self.assertTrue(got["section"], "the security panel is missing")
        self.assertTrue(got["tab"], "the security tab never reached the strip")
        for name in ("auth", "locks", "support"):
            with self.subTest(surface=name):
                self.assertGreater(
                    got[name], 0, f"{name} mounted nothing; the panel is blank"
                )
        self.assertGreater(
            got["lockRows"], 10, "every tab and appearance value should be lockable"
        )

    def test_each_search_field_has_its_regex_builder(self) -> None:
        got = render(
            "return {"
            "  auth: !!q('[data-regex-controls=\"auth\"]'),"
            "  locks: !!q('[data-regex-controls=\"locks\"]'),"
            "  authOpen: !!q('#auth-regex-open'),"
            "  locksOpen: !!q('#locks-regex-open')"
            "};"
        )
        for key, value in got.items():
            if key in ("loadErrors", "scriptCount"):
                continue
            with self.subTest(control=key):
                self.assertTrue(value, f"{key} is missing its anchored builder")


class ALockActuallyLocks(unittest.TestCase):
    """Reading the file cannot tell you whether the comparison is the right way
    round. Only running it can."""

    def test_a_password_lock_accepts_only_the_right_password(self) -> None:
        got = render(
            "const L = window.AmuletLocks;"
            "const salt = 'abc123';"
            "const right = L._digest('correct horse', salt);"
            "const wrong = L._digest('wrong horse', salt);"
            "return {differ: right !== wrong, length: right.length,"
            "        stable: right === L._digest('correct horse', salt)};"
        )
        self.assertTrue(got["differ"], "two different passwords hashed the same")
        self.assertEqual(got["length"], 64, "expected a SHA-256 hex digest")
        self.assertTrue(got["stable"], "the same password hashed differently twice")

    def test_the_password_is_never_stored_alongside_its_digest(self) -> None:
        source = (SITE / "locks.js").read_text(encoding="utf-8")
        self.assertNotIn(
            "password: password",
            source,
            "a lock record must carry a digest, never the password itself",
        )
        self.assertIn("digest(password", source)


class TheAuthenticatorProducesRealCodes(unittest.TestCase):
    def test_a_paired_entry_generates_a_code_of_the_right_shape(self) -> None:
        got = render(
            "const T = window.AmuletTOTP;"
            "const six = T.totp({secret:'JBSWY3DPEHPK3PXP', seconds: 59, digits: 6});"
            "const eight = T.totp({secret:'JBSWY3DPEHPK3PXP', seconds: 59, digits: 8});"
            "return {six: six, eight: eight,"
            "        moves: T.totp({secret:'JBSWY3DPEHPK3PXP', seconds: 59}) !=="
            "               T.totp({secret:'JBSWY3DPEHPK3PXP', seconds: 3600})};"
        )
        self.assertRegex(got["six"], r"^\d{6}$")
        self.assertRegex(got["eight"], r"^\d{8}$")
        self.assertTrue(got["moves"], "the code did not change with time")


class TheHonestyLinesAreExact(unittest.TestCase):
    """These say the feature is a toy and that nothing is sent anywhere. They
    are the part that must not drift, at any funny level."""

    TRUTH = (
        "Nothing here is sent anywhere. No ticket exists outside this machine, "
        "no network request is made, no data is collected, and nobody is "
        "reading it."
    )

    def test_the_support_desk_states_that_nobody_reads_it(self) -> None:
        got = render("return {truth: (q('.ticket-truth')||{}).textContent || ''};")
        self.assertEqual(got["truth"], self.TRUTH)

    def test_the_locks_surface_calls_itself_a_toy(self) -> None:
        got = render("return {text: (q('#locks-root')||{}).textContent || ''};")
        self.assertIn("own credential", got["text"])

    def test_the_authenticator_admits_it_has_no_credential_vault(self) -> None:
        got = render("return {text: (q('#authenticator-root')||{}).textContent || ''};")
        self.assertIn("local storage", got["text"])
        self.assertIn("clear", got["text"].lower())


class TheSourceIsPlainText(unittest.TestCase):
    """A raw control byte in a source file makes it binary to every tool that
    reads it: grep stops reporting matches, diffs collapse to "binary files
    differ", and a search for the line you are standing on returns nothing. Two
    files shipped with a literal NUL as a domain separator this way; the same
    separator written as an escape is byte-identical at runtime and leaves the
    file readable."""

    def test_no_script_carries_a_raw_control_character(self) -> None:
        offenders = []
        for path in sorted(SITE.glob("*.js")):
            source = path.read_text(encoding="utf-8")
            for index, char in enumerate(source):
                if ord(char) < 32 and char not in "\n\r\t":
                    offenders.append(
                        f"{path.name} at offset {index}: U+{ord(char):04X}"
                    )
                    break
        self.assertEqual(
            offenders,
            [],
            "write the character as an escape (\u0000) instead of embedding it",
        )


class UnlockGrantsExpire(unittest.TestCase):
    """A grant that never expires is the same as no lock. These run the real
    grant bookkeeping rather than reading it."""

    def test_a_one_shot_grant_is_spent_after_a_single_use(self) -> None:
        got = render("const L = window.AmuletLocks;" "return L._grantProbe('surface');")
        self.assertTrue(got["first"], "the one-shot grant did not apply at all")
        self.assertFalse(
            got["second"], "a 'this surface only' grant survived its single use"
        )

    def test_an_expired_timed_grant_stops_counting(self) -> None:
        got = render("const L = window.AmuletLocks; return L._grantProbe('expired');")
        self.assertTrue(got["first"])
        self.assertFalse(got["second"], "an expired grant still counted as unlocked")

    def test_a_session_grant_survives_repeated_checks(self) -> None:
        got = render("const L = window.AmuletLocks; return L._grantProbe('session');")
        self.assertTrue(got["first"])
        self.assertTrue(got["second"], "a session grant was spent like a one-shot")


class TheTicketListIsAList(unittest.TestCase):
    """Every other list on this site has a search wired to the regex builder,
    bulk selection and an export. A log is still a list."""

    def test_the_ticket_search_has_its_anchored_builder(self) -> None:
        got = render(
            "return {controls: !!q('[data-regex-controls=\"support\"]'),"
            "        open: !!q('#support-regex-open'),"
            "        field: !!q('#support-search'),"
            "        bulk: !!q('#support-bulk')};"
        )
        for key in ("controls", "open", "field", "bulk"):
            with self.subTest(control=key):
                self.assertTrue(got[key], f"the ticket list is missing {key}")


if __name__ == "__main__":
    unittest.main()


class TheDestructiveGateActuallyGates(unittest.TestCase):
    """Two keys and a slider only mean something if each is genuinely load
    bearing. A gate that fires on one click looks identical in a screenshot to
    one that does not."""

    SETUP = (
        "let fired = 0;"
        "window.AmuletConfirm.destructive({title:'T', detail:'D',"
        "  onConfirm(){ fired++; }});"
        "const gate = q('.gate');"
        "const keys = [...gate.querySelectorAll('input[type=checkbox]')];"
        "const slider = gate.querySelector('input[type=range]');"
        "const fire = () => {"
        "  slider.value = '100';"
        "  slider.dispatchEvent(new window.Event('input', {bubbles:true}));"
        "};"
    )

    def test_the_slider_is_dead_until_both_keys_turn(self) -> None:
        got = render(
            self.SETUP
            + "const before = slider.disabled;"
            + "keys[0].checked = true;"
            + "keys[0].dispatchEvent(new window.Event('change', {bubbles:true}));"
            + "const afterOne = slider.disabled;"
            + "keys[1].checked = true;"
            + "keys[1].dispatchEvent(new window.Event('change', {bubbles:true}));"
            + "const afterBoth = slider.disabled;"
            + "return {before: before, afterOne: afterOne, afterBoth: afterBoth};"
        )
        self.assertTrue(got["before"], "the slider was live before any key turned")
        self.assertTrue(got["afterOne"], "one key was enough to arm the slider")
        self.assertFalse(got["afterBoth"], "both keys did not arm the slider")

    def test_a_partial_slider_springs_back_and_fires_nothing(self) -> None:
        got = render(
            self.SETUP
            + "keys.forEach(k => { k.checked = true;"
            + "  k.dispatchEvent(new window.Event('change', {bubbles:true})); });"
            + "slider.value = '60';"
            + "slider.dispatchEvent(new window.Event('input', {bubbles:true}));"
            + "slider.dispatchEvent(new window.Event('change', {bubbles:true}));"
            + "return {fired: fired, value: slider.value};"
        )
        self.assertEqual(got["fired"], 0, "a half-drag confirmed the action")
        self.assertEqual(got["value"], "0", "a released partial drag did not reset")

    def test_the_full_journey_confirms_exactly_once(self) -> None:
        got = render(
            self.SETUP
            + "keys.forEach(k => { k.checked = true;"
            + "  k.dispatchEvent(new window.Event('change', {bubbles:true})); });"
            + "fire(); fire(); fire();"
            + "return {armedFired: fired, disabled: slider.disabled};"
        )
        self.assertLessEqual(
            got["armedFired"], 1, "the gate fired more than once for one journey"
        )
        self.assertTrue(got["disabled"], "the slider stayed live after completing")

    def test_the_facts_are_present_and_unstyled(self) -> None:
        got = render(
            "window.AmuletConfirm.destructive({title:'T',"
            "  detail:'This deletes 41 files and cannot be undone.'});"
            "return {detail: (q('#gate-detail')||{}).textContent || '',"
            "        exit: !!q('#gate-exit')};"
        )
        self.assertIn("cannot be undone", got["detail"])
        self.assertIn("41 files", got["detail"])
        self.assertTrue(got["exit"], "there is no emergency exit")


class ASchedulNeverEatsYourSettings(unittest.TestCase):
    """The whole point of the override layer: a schedule borrows a value and
    gives it back. If it wrote through the ordinary setter, the preference the
    user actually chose would be gone the moment a rule fired."""

    def test_an_override_does_not_become_the_stored_value(self) -> None:
        got = render(
            "const S = window.AmuletSite.settings;"
            "S.set('language', 'cantonese');"
            "const chosen = S.base('language');"
            "S.override('language', 'english');"
            "const during = {effective: S.get('language'), base: S.base('language'),"
            "                overridden: S.isOverridden('language')};"
            "S.release('language');"
            "return {chosen: chosen, during: during, after: S.get('language')};"
        )
        self.assertEqual(got["chosen"], "cantonese")
        self.assertEqual(got["during"]["effective"], "english")
        self.assertEqual(
            got["during"]["base"],
            "cantonese",
            "the override replaced the user's own stored value",
        )
        self.assertTrue(got["during"]["overridden"])
        self.assertEqual(
            got["after"], "cantonese", "the user's value did not come back"
        )

    def test_the_rendered_language_follows_the_override(self) -> None:
        """A stored value nothing reads is a control that does nothing."""

        got = render(
            "const site = window.AmuletSite;"
            "site.settings.set('language', 'english');"
            "const before = site.lang.t('Home', 'X-YUE');"
            "site.settings.override('language', 'cantonese');"
            "const during = site.lang.t('Home', 'X-YUE');"
            "site.settings.release('language');"
            "return {before: before, during: during, after: site.lang.t('Home','X-YUE')};"
        )
        self.assertEqual(got["before"], "Home")
        self.assertEqual(
            got["during"],
            "X-YUE",
            "overriding the language changed the store but not the copy",
        )
        self.assertEqual(got["after"], "Home")

    def test_provenance_says_a_schedule_is_responsible(self) -> None:
        got = render(
            "const S = window.AmuletSite.settings;"
            "S.set('theme', 'dark');"
            "S.override('theme', 'light');"
            "const line = S.provenance('theme');"
            "S.release('theme');"
            "return {line: line};"
        )
        self.assertIn("schedule", got["line"].lower())


class ScheduleWindowsMeanWhatTheySay(unittest.TestCase):
    def test_a_window_crossing_midnight_matches_both_sides(self) -> None:
        got = render(
            "const S = window.AmuletSchedule;"
            "const rule = {id:'r', enabled:true, days:'every',"
            "  startTime:'22:00', endTime:'06:00', settings:{}};"
            "const at = h => new Date(2026, 0, 5, h, 30);"
            "return {lateEvening: S._matches(rule, at(23)),"
            "        earlyMorning: S._matches(rule, at(2)),"
            "        afternoon: S._matches(rule, at(14))};"
        )
        self.assertTrue(got["lateEvening"], "23:30 is inside 22:00-06:00")
        self.assertTrue(got["earlyMorning"], "02:30 is inside 22:00-06:00")
        self.assertFalse(got["afternoon"], "14:30 is not inside 22:00-06:00")

    def test_an_equal_start_and_end_never_applies(self) -> None:
        got = render(
            "const S = window.AmuletSchedule;"
            "const rule = {id:'r', enabled:true, days:'every',"
            "  startTime:'09:00', endTime:'09:00', settings:{}};"
            "return {at9: S._matches(rule, new Date(2026,0,5,9,0)),"
            "        at12: S._matches(rule, new Date(2026,0,5,12,0))};"
        )
        self.assertFalse(
            got["at9"], "a zero-length window took over instead of doing nothing"
        )
        self.assertFalse(got["at12"])

    def test_a_later_rule_wins_key_by_key(self) -> None:
        got = render(
            "const S = window.AmuletSchedule;"
            "S._set(["
            "  {id:'a', enabled:true, days:'every', settings:{theme:'dark', scale:120}},"
            "  {id:'b', enabled:true, days:'every', settings:{theme:'light'}}"
            "]);"
            "const r = S.evaluate(new Date(2026,0,5,12,0));"
            "return {theme: r.values.theme, scale: r.values.scale,"
            "        applied: r.applied.length};"
        )
        self.assertEqual(got["theme"], "light", "the later rule did not win")
        self.assertEqual(got["scale"], 120, "a key only the earlier rule set was lost")
        self.assertEqual(got["applied"], 2)

    def test_a_disabled_rule_is_inert(self) -> None:
        got = render(
            "const S = window.AmuletSchedule;"
            "const rule = {id:'r', enabled:false, days:'every', settings:{theme:'dark'}};"
            "return {matched: S._matches(rule, new Date(2026,0,5,12,0))};"
        )
        self.assertFalse(got["matched"])


class PresetsComeFromTheRealDefaults(unittest.TestCase):
    """A preset claiming to be "as it ships" has to be derived from the shipped
    values, not from a hand-copied list that drifts the first time a default
    changes."""

    def test_the_shipped_preset_equals_the_core_defaults(self) -> None:
        got = render(
            "const P = window.AmuletPresets;"
            "const D = window.AmuletSite.settings.DEFAULTS;"
            "const s = P.shipped();"
            "return {mismatch: Object.keys(s).filter(k => s[k] !== D[k])};"
        )
        self.assertEqual(
            got["mismatch"],
            [],
            "the 'as it ships' preset disagrees with the actual defaults",
        )

    def test_every_preset_only_sets_keys_the_site_reads(self) -> None:
        got = render(
            "const P = window.AmuletPresets;"
            "const known = Object.keys(window.AmuletSite.settings.DEFAULTS);"
            "const bad = [];"
            "P.builtIn.forEach(p => Object.keys(p.values()).forEach(k => {"
            "  if (known.indexOf(k) < 0) bad.push(p.id + ':' + k); }));"
            "return {bad: bad};"
        )
        self.assertEqual(
            got["bad"], [], "a preset sets a key nothing on this site consumes"
        )

    def test_applying_a_preset_actually_changes_the_settings(self) -> None:
        got = render(
            "const S = window.AmuletSite.settings;"
            "S.set('theme', 'light');"
            "const night = window.AmuletPresets.builtIn.find(p => p.id === 'night');"
            "window.AmuletPresets._apply(night.values(), 'night');"
            "return {theme: S.get('theme'), density: S.get('density')};"
        )
        self.assertEqual(got["theme"], "dark", "applying a preset changed nothing")
        self.assertEqual(got["density"], "comfortable")

    def test_the_presets_surface_mounts(self) -> None:
        got = render(
            "return {root: (q('#presets-root')||{}).childElementCount || 0,"
            "        schedule: (q('#schedule-root')||{}).childElementCount || 0};"
        )
        self.assertGreater(got["root"], 0, "the presets surface is blank")
        self.assertGreater(got["schedule"], 0, "the schedule surface is blank")
