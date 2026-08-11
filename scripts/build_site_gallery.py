"""Rebuild the site's screenshot gallery from the real capture manifest.

The gallery used to be twelve legacy images, several of them from 2020 and none
of them of the interface the page describes. The capture harness now produces a
manifest of the built application at a named commit, so the page can show what
the software actually looks like instead.

Nothing here invents, retouches, or reorders for effect. Every row is copied
from the manifest, including the commit it was verified at, so the page can say
which build each picture is of rather than implying one build produced all of
them. A manifest row whose file is missing on disk is reported and dropped
rather than rendered as a broken image.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "docs" / "site"
SHOTS = SITE / "assets" / "shots"

#: Rendered above each group in the gallery. Ordered so a reader meets the
#: application before its parts, rather than opening on 113 dialogs.
GROUP_ORDER = (
    "Backstage",
    "Workspace",
    "Ribbon tabs",
    "Surfaces",
    "Dropdowns",
    "Context menus",
    "Overlays",
)


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_rows(manifest: dict, source: Path, missing: List[str]) -> List[Dict[str, object]]:
    commit = str(manifest.get("commit", ""))
    captured = str(manifest.get("captured", ""))
    short = commit[:8]
    rows: List[Dict[str, object]] = []
    for entry in manifest.get("captures", []):
        filename = str(entry.get("filename", ""))
        if not filename or not (source / filename).is_file():
            missing.append(filename or "<unnamed>")
            continue
        rows.append(
            {
                "src": f"assets/shots/{filename}",
                "title": str(entry.get("surface", filename)),
                "group": str(entry.get("group", "Surfaces")),
                "px": str(entry.get("viewport", "")),
                "theme": str(entry.get("theme", "")),
                "density": str(entry.get("density", "")),
                "colours": entry.get("colours"),
                "verified": commit,
                "provenance": (
                    f"Captured {captured} from commit {short} on an isolated "
                    "hidden Windows desktop"
                ),
                "boundary": str(entry.get("alt", "")),
                "alt": str(entry.get("alt", "")),
            }
        )
    order = {name: index for index, name in enumerate(GROUP_ORDER)}
    rows.sort(key=lambda row: (order.get(str(row["group"]), len(order)), row["title"]))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=ROOT / "docs" / "huishots")
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    missing: List[str] = []
    rows = build_rows(manifest, args.source, missing)
    if not rows:
        raise SystemExit("the manifest produced no usable rows; refusing to empty the gallery")

    # Replace the gallery wholesale: a mixture of current captures and legacy
    # images with no way to tell them apart is worse than either alone.
    if SHOTS.exists():
        shutil.rmtree(SHOTS)
    SHOTS.mkdir(parents=True)
    for row in rows:
        name = str(row["src"]).split("/")[-1]
        shutil.copy2(args.source / name, SHOTS / name)

    data_path = SITE / "site-data.js"
    text = data_path.read_text(encoding="utf-8")
    header, _, payload = text.partition("window.AMULET_SITE_DATA =")
    data = json.loads(payload.strip().rstrip(";"))
    data["shots"] = rows
    data["shotsCommit"] = manifest.get("commit", "")
    data_path.write_text(
        header + "window.AMULET_SITE_DATA = "
        + json.dumps(data, indent=2, ensure_ascii=False)
        + ";\n",
        encoding="utf-8",
    )

    groups: Dict[str, int] = {}
    for row in rows:
        groups[str(row["group"])] = groups.get(str(row["group"]), 0) + 1
    print(f"gallery rebuilt: {len(rows)} captures at {manifest.get('commit', '')[:8]}")
    for name in GROUP_ORDER:
        if name in groups:
            print(f"  {groups[name]:4}  {name}")
    if missing:
        print(f"  {len(missing)} manifest row(s) had no file and were dropped:")
        for name in missing[:10]:
            print(f"      {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
