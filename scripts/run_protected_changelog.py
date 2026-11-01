"""Forward an Actions-managed protected input over a private child stdin pipe."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

KEY = "PUBLICATION_LANGUAGE_DATA"
MAX_INPUT_BYTES = 262_144
CHILD_ENVIRONMENT = {"PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "LANG", "LC_ALL"}


def main() -> int:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        print("This wrapper is for trusted automation; local callers must use --policy-stdin.", file=sys.stderr)
        return 2
    protected = os.environ.pop(KEY, None)
    if not protected:
        print("Protected publication input is unavailable.", file=sys.stderr)
        return 2
    try:
        payload = protected.encode("utf-8", errors="strict")
    except UnicodeError:
        print("Protected publication input is invalid.", file=sys.stderr)
        return 2
    if len(payload) > MAX_INPUT_BYTES:
        print("Protected publication input exceeds its bound.", file=sys.stderr)
        return 2
    interpreter = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
    if not interpreter.is_file():
        print("Python interpreter is unavailable.", file=sys.stderr)
        return 2
    script = Path(__file__).resolve().with_name("generate_changelog.py")
    environment = {key: value for key, value in os.environ.items() if key.upper() in CHILD_ENVIRONMENT}
    try:
        result = subprocess.run(
            [str(interpreter), "-I", "-S", str(script), "--policy-stdin"],
            cwd=script.parent.parent,
            input=payload,
            env=environment,
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except OSError:
        print("Protected changelog generation could not start.", file=sys.stderr)
        return 2
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
