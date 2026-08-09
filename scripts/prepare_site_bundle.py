"""Create a static publication bundle with an explicit deployment base URL."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from verify_site_release_manifest import validate_bundle, validate_site_config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default="./")
    args = parser.parse_args()

    source = args.source.resolve()
    output = args.output.resolve()
    if output == source or source in output.parents:
        raise SystemExit("output must not be the source directory or inside it")
    if output.exists():
        shutil.rmtree(output)
    shutil.copytree(source, output)
    config_path = output / "site-config.json"
    config = validate_site_config(config_path)
    config["baseUrl"] = args.base_url
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    validate_bundle(output)
    print(f"Prepared static site bundle at {output} with base URL {args.base_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
