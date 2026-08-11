"""Write the README's capture matrix from a real capture manifest.

The matrix is generated rather than hand-written for one reason: a hand-written
list of images drifts from the images that exist, and it drifts silently.  A
README that shows a screenshot of a screen that no longer looks like that is
worse than one with no screenshots, because a reader has no way to tell.

Every row here comes from the manifest a capture run wrote, so an image in the
README exists on disk, was produced by that run, and carries the commit it was
taken at.  Nothing is retouched and nothing is invented: a surface that failed
to capture is listed as missing, with the reason, rather than quietly omitted.

Usage:
    py -3.11 scripts/build_readme_captures.py --manifest docs/huishots/<file>.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

#: The README region this script owns, start and end. Everything between the
#: markers is replaced; everything outside is left exactly as it was, so a
#: person can edit the rest of the README without this clobbering them.
START = "<!-- BEGIN CAPTURES -->"
END = "<!-- END CAPTURES -->"

#: Groups in the order a reader wants them: the shell first, then the places
#: work happens, then the menus and overlays that sit on top of them, then the
#: long tail of surfaces.
GROUP_ORDER = (
    "Backstage",
    "Workspace",
    "Ribbon tabs",
    "Context menus",
    "Overlays",
    "Dropdowns",
    "Surfaces",
)


def _row(entry: Dict, out_dir: Path, root: Path) -> str:
    """Return one image, with alt text that says what it shows."""
    # Resolve both sides: the manifest path may arrive relative while the root
    # is absolute, and relative_to() compares text rather than filesystem
    # position, so it refuses a pairing that is perfectly valid on disk.
    relative = (
        (out_dir / entry["filename"]).resolve().relative_to(root.resolve()).as_posix()
    )
    alt = entry["alt"].replace("]", ")").replace("[", "(")
    return f"![{alt}]({relative})"


def build(manifest_path: Path, root: Path) -> str:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    out_dir = manifest_path.parent
    captures: List[Dict] = manifest["captures"]
    failures: List[Dict] = manifest.get("failures", [])
    not_opened: List[Dict] = manifest.get("notOpened", [])

    by_group: Dict[str, List[Dict]] = {}
    for entry in captures:
        by_group.setdefault(entry["group"], []).append(entry)

    commit = manifest["commit"]
    lines = [
        START,
        "",
        "### The current interface",
        "",
        f"Every image below is a real capture of the built interface as it stood "
        f"at commit `{commit[:8]}` — that is the checkout the run photographed — "
        "taken by `scripts/capture_studio_surfaces.py` as it stands in the commit "
        "that ships this matrix. None is a mockup, a design file, or a retouched "
        "image.",
        "",
        "Those two can be different commits, and saying so is the point. A "
        "capture has to exist before the commit that contains it, so the stamp "
        "names the tree that was photographed rather than the tree the pictures "
        "landed in; and when a run is what proves a change to the harness, the "
        "harness that took the pictures is newer than the stamp on them. An "
        "earlier matrix stamped every row with a commit whose copy of the "
        "harness could not produce 129 of the images in it, which is the same "
        "sentence read as a promise it never made.",
        "",
        (
            f"This run went out over a checkout carrying "
            f"**{manifest['workingTreeChanges']} uncommitted change(s)**, so the "
            f"pictures show `{commit[:8]}` plus that work rather than the commit "
            "on its own. A run on a tree several people are landing in cannot "
            "say anything narrower than that, and saying nothing is how a stamp "
            "comes to mean more than it can."
            if manifest.get("workingTreeChanges")
            else "This run went out over a clean checkout of that commit."
        ),
        "",
        f"**{len(captures)} surfaces captured.**"
        + (
            f" **{len(failures)} could not be captured** — listed at the end, with why."
            if failures
            else ""
        ),
        "",
        "The capture asks each widget to draw itself rather than reading the "
        "screen, so the run needs no visible desktop and cannot photograph a "
        "window someone happened to drag over it. A surface whose controls "
        "could not draw is reported as a failure and its file deleted, because "
        "a blank capture is worse than none: it looks like evidence.",
        "",
        "Menus, dropdowns and popovers are photographed **open, with their rows "
        "drawn**. They are opened through the application's own openers and "
        "shown where no display covers them, because a popup grabs the mouse "
        "and the keyboard and a capture run must not take those from the "
        "machine it runs on.",
        "",
    ]

    ordered = [g for g in GROUP_ORDER if g in by_group]
    ordered += [g for g in sorted(by_group) if g not in GROUP_ORDER]

    for group in ordered:
        entries = sorted(by_group[group], key=lambda e: e["surface"])
        lines.append(f"<details>")
        lines.append(
            f"<summary><b>{group}</b> — {len(entries)} "
            f"{'surface' if len(entries) == 1 else 'surfaces'}</summary>"
        )
        lines.append("")
        for entry in entries:
            lines.append(
                f"**`{entry['surface']}`** — {entry['viewport']}, "
                f"{entry['theme']} theme, {entry['density']} density"
            )
            # One popover opened from four hosts is one picture. Shipping four
            # byte-identical files and counting them four times is a coverage
            # number inflated by a factor of four, so a row that resolved to a
            # picture already shown says which one and why.
            twin = entry.get("sameImageAs")
            if twin:
                lines.append("")
                lines.append(
                    f"Pixel-identical to `{twin}`: the same popover, opened from "
                    "a different host. One file, shown again rather than counted "
                    "again."
                )
            lines.append("")
            lines.append(_row(entry, out_dir, root))
            lines.append("")
        lines.append("</details>")
        lines.append("")

    if failures:
        lines.append("<details>")
        lines.append(f"<summary><b>Not captured</b> — {len(failures)}</summary>")
        lines.append("")
        lines.append(
            "These are recorded rather than omitted. A gap nobody mentions "
            "reads as coverage."
        )
        lines.append("")
        lines.append("| Surface | Why not |")
        lines.append("| --- | --- |")
        for failure in sorted(failures, key=lambda f: f["name"]):
            reason = failure["reason"].replace("|", "/").strip()
            lines.append(f"| `{failure['name']}` | {reason} |")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    if not_opened:
        lines.append("<details>")
        lines.append(
            f"<summary><b>Menus and overlays not opened</b> — {len(not_opened)}</summary>"
        )
        lines.append("")
        lines.append(
            "A menu that a run could not raise is written down here rather "
            "than left out. A gap nobody mentions reads as coverage."
        )
        lines.append("")
        lines.append("| Surface | Why not |")
        lines.append("| --- | --- |")
        for entry in sorted(not_opened, key=lambda f: f["name"]):
            reason = entry["reason"].replace("|", "/").strip()
            lines.append(f"| `{entry['name']}` | {reason} |")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    lines.append(END)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--readme", type=Path, default=Path("README.md"))
    args = parser.parse_args()

    root = args.readme.resolve().parent
    section = build(args.manifest, root)

    readme = args.readme.read_text(encoding="utf-8")
    if START in readme and END in readme:
        head, _, rest = readme.partition(START)
        _, _, tail = rest.partition(END)
        readme = head + section + tail
    else:
        readme = readme.rstrip() + "\n\n" + section + "\n"
    args.readme.write_text(readme, encoding="utf-8")

    count = section.count("![")
    print(f"README capture matrix written: {count} images")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
