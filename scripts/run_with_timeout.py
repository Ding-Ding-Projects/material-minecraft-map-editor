"""Run a Python tool with a bounded timeout and useful failure output."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.seconds <= 0 or not args.command or args.command[0] != "--":
        parser.error("use --seconds N -- <python arguments>")
    command = [sys.executable, *args.command[1:]]
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = subprocess.Popen(command, creationflags=creationflags)
    try:
        return process.wait(timeout=args.seconds)
    except subprocess.TimeoutExpired:
        print(
            f"Timed out after {args.seconds:.0f}s: {' '.join(command)}",
            file=sys.stderr,
        )
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        process.wait(timeout=30)
        return 124


if __name__ == "__main__":
    raise SystemExit(main())
