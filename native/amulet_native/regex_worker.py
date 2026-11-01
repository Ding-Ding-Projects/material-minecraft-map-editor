"""One bounded regex task in an isolated, cancelable child process."""

import json
import os
import re
import sys


def evaluate(request):
    pattern = request["pattern"]
    sample = request["sample"]
    items = request["items"]
    if (not isinstance(pattern, str) or len(pattern) > 512 or not isinstance(sample, str)
            or len(sample) > 4096 or not isinstance(items, list) or len(items) > 256
            or any(not isinstance(s, str) or len(s) > 256 for s in items)):
        raise ValueError("Regex input exceeds supported bounds")
    flags = (re.IGNORECASE if request.get("ignoreCase") is True else 0) | (re.MULTILINE if request.get("multiline") is True else 0)
    compiled = re.compile(pattern, flags)
    matches = []
    for match in compiled.finditer(sample):
        matches.append({"start": match.start(), "end": match.end(), "text": match.group(0)[:160]})
        if len(matches) == 64:
            break
    return {"indices": [i for i, item in enumerate(items) if compiled.search(item)],
            "matches": matches, "engine": "Python re " + sys.version.split()[0]}


def main():
    # No regex input is accepted before the parent validates this identity.
    print(json.dumps({"event": "ready", "pid": os.getpid(), "executable": sys.executable,
                      "version": list(sys.version_info[:3])}), flush=True)
    try:
        payload = sys.stdin.buffer.read(65537)
        if len(payload) > 65536:
            raise ValueError("Regex request exceeds byte limit")
        result = evaluate(json.loads(payload))
    except (ValueError, KeyError, TypeError, re.error) as error:
        result = {"error": str(error)[:300]}
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__": main()
