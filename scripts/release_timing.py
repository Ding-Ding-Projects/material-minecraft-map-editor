#!/usr/bin/env python3
"""Calculate a verified UTC workflow duration for release notes."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("release timing values must include a timezone")
    return parsed.astimezone(timezone.utc)


def release_duration(started: str, completed: str) -> str:
    start = parse_utc(started)
    end = parse_utc(completed)
    elapsed = int((end - start).total_seconds())
    if elapsed < 0:
        raise ValueError("release completion cannot precede the first job start")
    return f"{elapsed // 3600:02d}:{(elapsed % 3600) // 60:02d}:{elapsed % 60:02d}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--started", required=True)
    parser.add_argument("--completed", required=True)
    args = parser.parse_args()
    print(release_duration(args.started, args.completed))


if __name__ == "__main__":
    main()
