"""Every site surface resolves through a semantic Material 3 role.

This replaced a guard that asserted literal minified CSS:

    assert ":root{--surface-card:#f7f5fc}" in css

That pinned a spelling rather than a contract. It failed on a reformat that
changed nothing, passed on a page that hard-coded colours everywhere else, and
named a token (``--surface-card``) that no longer exists. Both halves of the
check are now expressed against what actually has to be true: the role tokens
are defined for both themes, and every surface-bearing component resolves its
colours through them instead of a literal.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "docs" / "site" / "styles.css"

#: Hand-written on purpose. A rule that only inspects the components which
#: happen to be present passes on a stylesheet that dropped half of them, so the
#: enumeration is what makes a missing surface fail rather than quietly vanish.
#: Add to it when a surface-bearing component is added.
SURFACE_COMPONENTS = (
    ".top-app-bar",
    ".search-field",
    ".feature-card",
    ".community-card",
    ".setting-card",
    ".shot",
    ".palette-card",
    ".drawer",
    ".context-menu",
    ".toast",
    ".empty-state",
)

#: The Material 3 roles the whole sheet is built on.
REQUIRED_ROLES = (
    "--surface",
    "--surface-container",
    "--surface-bright",
    "--on-surface",
    "--on-surface-variant",
    "--outline",
    "--primary",
    "--primary-container",
    "--on-primary-container",
)

#: A literal colour anywhere except the token definitions defeats theming.
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def _iter_rules(css: str):
    """Yield ``(selector, body)`` for every rule, including inside at-blocks.

    Written as a brace scanner rather than a regular expression: a pattern like
    ``([^{}]+)\\{([^{}]*)\\}`` silently skips every rule nested inside a
    ``@media`` block, which made this guard report that ``.top-app-bar`` had no
    rule at all while the stylesheet plainly declared one.
    """
    # Comments have to go first. Left in, the text between the previous rule's
    # closing brace and this rule's opening one includes the comment above it,
    # so the selector reads as "/* header */ .top-app-bar" and matches nothing
    # -- which is how this guard managed to report that a rule it could see in
    # the file did not exist.
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    depth = 0
    start = 0
    stack = []
    for index, char in enumerate(css):
        if char == "{":
            selector = css[start:index].strip()
            stack.append((selector, index + 1, depth))
            depth += 1
            start = index + 1
        elif char == "}":
            if stack:
                selector, body_start, _ = stack.pop()
                body = css[body_start:index]
                # An at-block holds rules, not declarations; its own body is not
                # a rule body, and its children are yielded on their own.
                if not selector.startswith("@"):
                    yield selector, body
            depth = max(0, depth - 1)
            start = index + 1


def _rule_bodies(css: str, selector: str):
    """Yield the body of every rule that styles ``selector`` *itself*.

    Deliberately not matching descendants: ``.shot img`` is a rule about an
    image, not about ``.shot``. Counting it meant renaming ``.shot`` away
    entirely still satisfied "this component has a rule", so the guard passed
    on a stylesheet that had lost the component.
    """
    for selectors, body in _iter_rules(css):
        parts = [part.strip() for part in selectors.split(",")]
        if any(
            part == selector
            or part.startswith(selector + ":")
            or part.startswith(selector + "[")
            for part in parts
        ):
            # Nested rules leave their children's text in the parent body; only
            # the declarations directly before the first nested brace matter.
            yield selectors, body.split("{")[0]


class SiteSurfaceTokenContractTests(unittest.TestCase):
    def setUp(self):
        self.css = CSS.read_text(encoding="utf-8")

    def test_every_material_role_is_defined_for_both_themes(self):
        light = self.css.split('html[data-theme="dark"]')[0]
        dark_index = self.css.find('html[data-theme="dark"]')
        self.assertNotEqual(dark_index, -1, "the sheet defines no dark theme")
        dark = self.css[dark_index : dark_index + 2000]
        for role in REQUIRED_ROLES:
            with self.subTest(role=role):
                self.assertIn(f"{role}:", light, f"{role} is not defined for light")
        # Dark does not have to redefine every role, but it must redefine the
        # grounds and the ink, or the second theme is decoration.
        for role in ("--surface", "--surface-container", "--on-surface", "--outline"):
            with self.subTest(role=role, theme="dark"):
                self.assertIn(f"{role}:", dark, f"{role} is not redefined for dark")

    def test_every_surface_component_exists_and_resolves_through_a_role(self):
        for selector in SURFACE_COMPONENTS:
            with self.subTest(component=selector):
                bodies = list(_rule_bodies(self.css, selector))
                self.assertTrue(
                    bodies, f"{selector} has no rule at all in the stylesheet"
                )
                coloured = [
                    (sel, body)
                    for sel, body in bodies
                    if "background" in body or "color:" in body
                ]
                self.assertTrue(
                    coloured,
                    f"{selector} never sets a background or colour, so it cannot "
                    "carry a surface role",
                )
                for sel, body in coloured:
                    literals = [
                        found
                        for line in body.split(";")
                        if ("background" in line or "color:" in line)
                        for found in HEX.findall(line)
                    ]
                    self.assertFalse(
                        literals,
                        f"{sel} hard-codes {literals}; a themed surface must "
                        "resolve through a var(--role)",
                    )

    def test_the_sheet_does_not_reintroduce_the_retired_token(self):
        # --surface-card was a bespoke token standing outside the M3 roles.
        self.assertNotIn("--surface-card", self.css)


if __name__ == "__main__":
    unittest.main()
