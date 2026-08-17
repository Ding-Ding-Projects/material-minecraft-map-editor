"""Contract coverage for the static GitHub Pages deployment workflow."""

from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import re
import subprocess
import unittest
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pages.yml"
SITE = ROOT / "docs" / "site"


def _contract_errors(source: str) -> list[str]:
    errors: list[str] = []
    try:
        trigger = source.split("\non:\n", 1)[1].split("\npermissions:\n", 1)[0]
    except IndexError:
        trigger = ""
    build = source.split("  deploy-pages:", 1)[0]
    deploy = source.split("  deploy-pages:", 1)[1]
    build_job = source.split("  build-pages:", 1)[1].split("  deploy-pages:", 1)[0]

    expected_trigger = "  push:\n    branches:\n      - main\n  workflow_dispatch:\n"
    if trigger != expected_trigger:
        errors.append("workflow triggers are not exactly main push and manual dispatch")

    for permission in ("  contents: read", "  pages: write", "  id-token: write"):
        if permission not in source:
            errors.append(f"missing permission: {permission.strip()}")
    permission_lines = {
        line.strip()
        for line in source.split("permissions:", 1)[1]
        .split("# A Pages publication", 1)[0]
        .splitlines()
        if line.strip()
    }
    if permission_lines != {"contents: read", "pages: write", "id-token: write"}:
        errors.append("top-level permissions are not least-privileged")
    if "\n    permissions:\n      contents: read\n" not in build_job:
        errors.append("build job does not override permissions to contents read only")
    if "pages: write" in build_job or "id-token: write" in build_job:
        errors.append("build job inherits deployment permissions")
    if "\n    permissions:\n      pages: write\n      id-token: write\n" not in deploy:
        errors.append("deployment job does not declare Pages and OIDC permissions")
    if "contents: read" in deploy:
        errors.append("deployment job has unnecessary source-read permission")

    try:
        concurrency = source.split("\nconcurrency:\n", 1)[1].split("\n\njobs:\n", 1)[0]
    except IndexError:
        concurrency = ""
    expected_concurrency = "  group: pages\n  cancel-in-progress: false"
    if concurrency != expected_concurrency:
        errors.append("concurrency must use exactly one non-cancelling Pages group")
    if "  cancel-in-progress: false" not in concurrency:
        errors.append("deployment cancellation must be disabled")
    if "cancel-in-progress: true" in source:
        errors.append("deployment cancellation is enabled")

    expected_actions = {
        "actions/checkout@v4": 1,
        "actions/configure-pages@v5": 1,
        "actions/setup-node@v4": 1,
        "actions/setup-python@v6": 1,
        "actions/upload-pages-artifact@v3": 1,
        "actions/deploy-pages@v4": 1,
        "actions/upload-artifact@v4": 2,
    }
    used_actions = [
        line.split("uses:", 1)[1].strip()
        for line in source.splitlines()
        if "uses:" in line
    ]
    if Counter(used_actions) != expected_actions:
        errors.append("workflow actions differ from the reviewed official action set")
    if any(not action.startswith("actions/") for action in used_actions):
        errors.append("workflow uses a non-official action")
    if "actions/configure-pages@v5" in build_job:
        errors.append("build job configures Pages with elevated permissions")
    if "actions/configure-pages@v5" not in deploy:
        errors.append("deployment job does not configure Pages")

    for marker in (
        "runs-on: ubuntu-24.04",
        "Windows remains the sole application build and release target.",
        "Require the main branch for publication",
        'REQUESTED_REF" != "refs/heads/main',
        "permissions:\n      contents: read",
        "index_symlinks = [",
        "runtime_symlinks = []",
        "site source must not contain symlinks",
        "python -m unittest -v \\",
        "tests.test_pages_workflow_contract",
        "tests.test_site_publication_contract",
        "test_site_cards_and_search_fields_use_semantic_surface_tokens",
        "test_site_palette_indexes_every_feature_and_setting_card",
        "scripts/prepare_site_bundle.py",
        "--source docs/site",
        "--output build/pages",
        "scripts/verify_site_release_manifest.py build/pages",
        "node --check docs/site/app.js",
        "git rev-parse HEAD",
        'actual_commit" != "$EXPECTED_COMMIT',
        "remote resource or unsafe link is forbidden",
        "missing bundled target",
        'values.get("srcset")',
        "self.inline_styles = []",
        "for stylesheet in sorted(stylesheet_paths):",
        "url_tokens = list(",
        "contains a non-local resource URL",
        "parsed_resource.scheme\n                      or parsed_resource.netloc",
    ):
        if marker not in build:
            errors.append(f"missing static-site validation marker: {marker}")
    for network_installer in ("curl ", "wget ", "pip install", "npm install"):
        if network_installer in build:
            errors.append(
                f"site build uses a network installer: {network_installer.strip()}"
            )

    for marker in (
        "deployment-evidence.json",
        '"commit": commit',
        '"runId": int(run_id)',
        '"runAttempt": int(run_attempt)',
        '"sourceUrl"',
        "actions/upload-pages-artifact@v3",
        "actions/deploy-pages@v4",
        "environment:",
        "name: github-pages",
        "url: ${{ steps.deployment.outputs.page_url }}",
        "if: ${{ github.ref == 'refs/heads/main' }}",
        "permissions:\n      pages: write\n      id-token: write",
    ):
        if marker not in source:
            errors.append(f"missing deployment marker: {marker}")
    if source.index("actions/upload-pages-artifact@v3") > source.index(
        "actions/deploy-pages@v4"
    ):
        errors.append("deployment runs before the Pages artifact is uploaded")

    for marker in (
        "Verify the deployed commit evidence",
        "range(1, 13)",
        "timeout=10",
        "response.read(65537)",
        "urlencode(",
        '"Cache-Control": "no-cache"',
        "TimeoutError",
        "response.geturl()",
        "canonical_url = urlsplit(evidence_path)",
        "redirected away from the Pages origin or path",
        'evidence.get("schemaVersion") != 1',
        'evidence.get("commit") != os.environ["EXPECTED_COMMIT"]',
        'evidence.get("repository") != os.environ["EXPECTED_REPOSITORY"]',
        'evidence.get("runId") != int(os.environ["EXPECTED_RUN_ID"])',
        'evidence.get("runAttempt") != int(',
        'evidence.get("sourceUrl") != expected_source_url',
    ):
        if marker not in deploy:
            errors.append(f"missing hosted verification marker: {marker}")

    if source.count("if: ${{ always() }}") < 4:
        errors.append("build and deployment evidence are not collected on failure")
    if source.count("continue-on-error: true") != 2:
        errors.append("diagnostic uploads can mask the original failure")
    if source.count("if-no-files-found: warn") != 2:
        errors.append("diagnostic uploads are not defensive")
    if source.count("retention-days: 14") != 2:
        errors.append("diagnostic artifact retention is not bounded")

    for side_effect in (
        "gh release",
        "gh api",
        "git tag",
        "git push",
        "docker build",
        "twine upload",
    ):
        if side_effect in source:
            errors.append(f"unrelated publication side effect: {side_effect}")
    return errors


class _ReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.references: list[tuple[str, str, str, bool]] = []
        self.inline_styles: list[str] = []
        self._style_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(values["id"])
        if values.get("style"):
            self.inline_styles.append(values["style"])
        if tag == "style":
            self._style_depth += 1
        if tag == "a" and values.get("href"):
            self.references.append((tag, "href", values["href"], False))
        if tag == "link" and values.get("href"):
            self.references.append((tag, "href", values["href"], True))
        for attribute in ("src", "poster"):
            if values.get(attribute):
                self.references.append((tag, attribute, values[attribute], True))
        if values.get("srcset"):
            for candidate in values["srcset"].split(","):
                parts = candidate.strip().split()
                if not parts:
                    raise ValueError("srcset contains an empty candidate")
                self.references.append((tag, "srcset", parts[0], True))

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self._style_depth = max(0, self._style_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._style_depth:
            self.inline_styles.append(data)


def _css_resource_errors(css: str, root: Path) -> list[str]:
    errors: list[str] = []
    without_comments = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    if "\\" in without_comments:
        errors.append("unsupported escaped token")
    if re.search(r"@import\b", without_comments, re.IGNORECASE):
        errors.append("forbidden import")
    starts = re.findall(r"url\s*\(", without_comments, re.IGNORECASE)
    tokens = list(
        re.finditer(r"url\s*\(\s*([^)]*?)\s*\)", without_comments, re.IGNORECASE)
    )
    if len(tokens) != len(starts):
        errors.append("malformed url token")
    for match in tokens:
        value = match.group(1).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1].strip()
        if not value or "\\" in value:
            errors.append("empty or escaped resource URL")
            continue
        parsed = urlsplit(value)
        if (
            parsed.scheme
            or parsed.netloc
            or parsed.path.startswith("/")
            or parsed.query
            or parsed.fragment
        ):
            errors.append("non-local resource URL")
            continue
        target = (root / unquote(parsed.path)).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            errors.append("resource escapes site root")
            continue
        if not target.is_file():
            errors.append("missing local resource")
    return errors


class PagesWorkflowContractTests(unittest.TestCase):
    def test_release_independent_deployment_contract(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(_contract_errors(source), [])

    def test_contract_watches_unsafe_cancellation(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        unsafe = source.replace("cancel-in-progress: false", "cancel-in-progress: true")
        errors = _contract_errors(unsafe)
        self.assertIn("deployment cancellation must be disabled", errors)
        self.assertIn("deployment cancellation is enabled", errors)

    def test_contract_watches_extra_push_branch(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        unsafe = source.replace(
            "      - main\n  workflow_dispatch:",
            "      - main\n      - extra\n  workflow_dispatch:",
        )
        self.assertIn(
            "workflow triggers are not exactly main push and manual dispatch",
            _contract_errors(unsafe),
        )

    def test_contract_watches_concurrency_group_drift(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        unsafe = source.replace("  group: pages\n", "  group: pages-extra\n")
        self.assertIn(
            "concurrency must use exactly one non-cancelling Pages group",
            _contract_errors(unsafe),
        )

    def test_contract_watches_duplicate_deployment_action(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        unsafe = source.replace(
            "        uses: actions/deploy-pages@v4\n",
            "        uses: actions/deploy-pages@v4\n"
            "\n"
            "      - name: Duplicate deployment\n"
            "        uses: actions/deploy-pages@v4\n",
        )
        self.assertIn(
            "workflow actions differ from the reviewed official action set",
            _contract_errors(unsafe),
        )

    def test_contract_watches_css_predicate_weakening(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        unsafe = source.replace(
            "parsed_resource.scheme\n                      or parsed_resource.netloc",
            "False\n                      or parsed_resource.netloc",
        )
        errors = _contract_errors(unsafe)
        self.assertTrue(
            any("parsed_resource.scheme" in error for error in errors), errors
        )

    def test_contract_watches_job_permission_drift(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        unsafe_build = source.replace(
            "    permissions:\n      contents: read\n    steps:\n",
            "    steps:\n",
            1,
        )
        self.assertIn(
            "build job does not override permissions to contents read only",
            _contract_errors(unsafe_build),
        )
        unsafe_deploy = source.replace(
            "    permissions:\n      pages: write\n      id-token: write\n",
            "",
            1,
        )
        self.assertIn(
            "deployment job does not declare Pages and OIDC permissions",
            _contract_errors(unsafe_deploy),
        )

    def test_site_has_only_local_resources_and_resolvable_local_links(self):
        parser = _ReferenceParser()
        parser.feed((SITE / "index.html").read_text(encoding="utf-8"))
        parser.close()
        root = SITE.resolve()
        for _tag, _attribute, raw, resource in parser.references:
            parsed = urlsplit(raw)
            if parsed.scheme or parsed.netloc:
                self.assertFalse(resource, f"remote resource dependency: {raw}")
                continue
            self.assertFalse(
                parsed.path.startswith("/"), f"root-absolute site link: {raw}"
            )
            if not parsed.path:
                self.assertTrue(
                    not parsed.fragment or parsed.fragment in parser.ids, raw
                )
                continue
            target = (root / unquote(parsed.path)).resolve()
            target.relative_to(root)
            self.assertTrue(target.is_file(), raw)

        css = (SITE / "styles.css").read_text(encoding="utf-8")
        self.assertEqual(_css_resource_errors(css, root), [])
        for inline_style in parser.inline_styles:
            self.assertEqual(_css_resource_errors(inline_style, root), [])

    def test_reference_parser_covers_srcset_and_inline_css(self):
        parser = _ReferenceParser()
        parser.feed(
            '<style>.hero{background:url("local.png")}</style>'
            '<img srcset="small.png 1x, large.png 2x" style="background: none">'
        )
        parser.close()
        self.assertIn(("img", "srcset", "small.png", True), parser.references)
        self.assertIn(("img", "srcset", "large.png", True), parser.references)
        self.assertIn("background: none", parser.inline_styles)
        self.assertTrue(
            any("local.png" in style for style in parser.inline_styles),
            parser.inline_styles,
        )

    def test_site_source_has_no_tracked_or_runtime_symlinks(self):
        index = subprocess.run(
            ["git", "ls-files", "-s", "--", "docs/site"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        self.assertFalse([entry for entry in index if entry.startswith("120000 ")])
        self.assertFalse([path for path in SITE.rglob("*") if path.is_symlink()])

    def test_css_remote_resource_guard_rejects_quoted_and_spaced_urls(self):
        for css in (
            '@import url("https://cdn.example.test/theme.css");',
            ".hero { background: url( 'https://cdn.example.test/hero.png' ); }",
            '.hero { background: URL("http://cdn.example.test/hero.png") }',
            ".hero { background: url(//cdn.example.test/hero.png) }",
            r".hero { background: url(\68ttps://cdn.example.test/hero.png) }",
        ):
            self.assertTrue(_css_resource_errors(css, SITE.resolve()), css)

        self.assertEqual(
            _css_resource_errors(".hero { background: url('app.js') }", SITE.resolve()),
            [],
        )


if __name__ == "__main__":
    unittest.main()
