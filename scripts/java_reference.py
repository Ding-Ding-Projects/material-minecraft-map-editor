"""Acquire pinned official Java reference metadata without executing any code.

Binaries stay in a verified ignored cache. Reading version metadata does not
prove world-format, editing, runtime or license acceptance compatibility.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import re
import subprocess
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

MAX_METADATA = 2 * 1024 * 1024
MAX_SERVER = 256 * 1024 * 1024
MAX_VERSION = 64 * 1024
MAX_MEMBERS = 60_000
ALLOWED_HOSTS = frozenset({"piston-meta.mojang.com", "piston-data.mojang.com", "launcher.mojang.com", "launchermeta.mojang.com"})

class ReferenceError(ValueError):
    pass


def validate_url(url: object) -> str:
    if not isinstance(url, str) or len(url) > 2048 or any(ord(c) < 33 for c in url):
        raise ReferenceError("Invalid official reference URL")
    try:
        parts = urllib.parse.urlsplit(url)
        valid = parts.scheme == "https" and parts.hostname in ALLOWED_HOSTS and parts.port in (None, 443) and not parts.username and not parts.password and not parts.query and not parts.fragment
    except ValueError:
        valid = False
    if not valid:
        raise ReferenceError("Reference URL is outside the official HTTPS allowlist")
    return url


class OfficialRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        validate_url(new_url)
        return super().redirect_request(request, response, code, message, headers, new_url)


def fetch(url: str, limit: int) -> bytes:
    validate_url(url)
    started = time.monotonic()
    try:
        with urllib.request.build_opener(OfficialRedirects()).open(url, timeout=30) as response:
            validate_url(response.geturl())
            length = response.headers.get("Content-Length")
            if length is not None and (not length.isdecimal() or int(length) > limit):
                raise ReferenceError("Official reference exceeds download limit")
            chunks = []
            total = 0
            while True:
                if time.monotonic() - started > 180:
                    raise ReferenceError("Official reference download exceeded time limit")
                block = response.read(min(1024 * 1024, limit + 1 - total))
                if not block:
                    break
                chunks.append(block)
                total += len(block)
                if total > limit:
                    raise ReferenceError("Official reference exceeds download limit")
            return b"".join(chunks)
    except (OSError, urllib.error.URLError) as exc:
        raise ReferenceError("Official reference download unavailable") from None


def parse_json(data: bytes, limit: int) -> dict:
    if len(data) > limit:
        raise ReferenceError("Reference JSON exceeds limit")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ReferenceError("Duplicate reference JSON field")
            result[key] = value
        return result
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=unique)
    except (ValueError, UnicodeError, RecursionError):
        raise ReferenceError("Invalid reference JSON") from None
    if not isinstance(value, dict):
        raise ReferenceError("Reference JSON must be an object")
    return value


def digest(value: object, length: int) -> str:
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{" + str(length) + "}", value):
        raise ReferenceError("Invalid pinned digest")
    return value


def pinned(data: bytes, expected: str, algorithm: str, size: int | None = None) -> None:
    if size is not None and len(data) != size:
        raise ReferenceError("Pinned reference size mismatch")
    if hashlib.new(algorithm, data).hexdigest() != expected:
        raise ReferenceError("Pinned reference digest mismatch")


def read_member(archive: zipfile.ZipFile, name: str, limit: int) -> bytes:
    matches = [entry for entry in archive.infolist() if entry.filename == name]
    if len(matches) != 1:
        raise ReferenceError("Required ZIP member is missing or ambiguous")
    member = matches[0]
    if member.is_dir() or member.file_size > limit or member.flag_bits & 1 or member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
        raise ReferenceError("Unsupported or oversized ZIP member")
    with archive.open(member) as stream:
        data = stream.read(limit + 1)
    if len(data) > limit or len(data) != member.file_size:
        raise ReferenceError("ZIP member size mismatch")
    return data


def version_fields(data: bytes, expected_id: str) -> dict:
    fields = parse_json(data, MAX_VERSION)
    if fields.get("id") != expected_id or not isinstance(fields.get("id"), str) or type(fields.get("world_version")) is not int or not 0 <= fields["world_version"] <= 2**31-1:
        raise ReferenceError("Reference version identity or world version is invalid")
    return {"id": fields["id"], "worldVersion": fields["world_version"], "versionJsonSha256": hashlib.sha256(data).hexdigest()}


def open_archive(data: bytes) -> zipfile.ZipFile:
    """Bound directory expansion before zipfile allocates its member objects."""
    if len(data) > MAX_SERVER:
        raise ReferenceError("Server archive exceeds limit")
    end = data.rfind(b"PK\x05\x06", max(0, len(data) - 65557))
    if end < 0 or len(data) - end < 22:
        raise ReferenceError("ZIP directory is unavailable")
    _, disk, directory_disk, disk_count, count, size, offset, comment = struct.unpack_from("<4s4H2IH", data, end)
    if disk != 0 or directory_disk != 0 or disk_count != count or count == 65535 or count > MAX_MEMBERS or size > MAX_MEMBERS * 512 or offset + size > end or end + 22 + comment != len(data):
        raise ReferenceError("Unsupported or oversized ZIP directory")
    return zipfile.ZipFile(io.BytesIO(data))

def inspect_server(data: bytes, expected_id: str) -> dict:
    if len(data) > MAX_SERVER:
        raise ReferenceError("Server archive exceeds limit")
    try:
        with open_archive(data) as outer:
            if len(outer.infolist()) > MAX_MEMBERS:
                raise ReferenceError("ZIP member budget exceeded")
            if any(member.filename == "version.json" for member in outer.infolist()):
                return {**version_fields(read_member(outer, "version.json", MAX_VERSION), expected_id), "versionSource": "version.json"}
            listing = read_member(outer, "META-INF/versions.list", MAX_VERSION).decode("utf-8")
            rows = []
            for line in listing.splitlines():
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) != 3:
                    raise ReferenceError("Invalid bundled version list")
                sha, version, path = parts
                digest(sha, 64)
                if not path or len(path) > 256 or "\\" in path or path.startswith("/") or any(part in ("", ".", "..") for part in path.split("/")) or ":" in path:
                    raise ReferenceError("Unsafe bundled version member")
                if version == expected_id:
                    rows.append((sha, path))
            if len(rows) != 1:
                raise ReferenceError("Bundled version is missing or ambiguous")
            sha, path = rows[0]
            nested = read_member(outer, "META-INF/versions/" + path, MAX_SERVER)
            pinned(nested, sha, "sha256")
        with open_archive(nested) as inner:
            if len(inner.infolist()) > MAX_MEMBERS:
                raise ReferenceError("ZIP member budget exceeded")
            return {**version_fields(read_member(inner, "version.json", MAX_VERSION), expected_id), "versionSource": "bundled-version.json", "nestedJarSha256": sha}
    except (zipfile.BadZipFile, RuntimeError, UnicodeError, OSError):
        raise ReferenceError("Invalid server reference archive") from None


def ignored_cache(repo: Path, version: str) -> Path:
    cache = repo / "build" / "java-reference" / version
    for path in (cache, cache / "metadata.json", cache / "server.jar", cache / "receipt.json"):
        relative = path.relative_to(repo).as_posix()
        result = subprocess.run(["git", "check-ignore", "--quiet", "--", relative], cwd=repo, capture_output=True)
        if result.returncode != 0:
            raise ReferenceError("Reference cache is not ignored")
    # Refuse an existing symlink or redirected cache ancestor before writing.
    for path in (repo / "build", repo / "build/java-reference", cache):
        if path.is_symlink() or (path.exists() and path.resolve() != repo.resolve() / path.relative_to(repo)):
            raise ReferenceError("Reference cache escapes its repository")
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def acquire(manifest_path: Path, repo: Path, version: str = "1.20.1") -> dict:
    if version != "1.20.1":
        raise ReferenceError("Only the selected reference version is supported")
    with manifest_path.open("rb") as stream:
        manifest = parse_json(stream.read(MAX_METADATA + 1), MAX_METADATA)
    entries = manifest.get("versions")
    if manifest.get("schemaVersion") != 1 or not isinstance(entries, list) or len(entries) > 1000:
        raise ReferenceError("Invalid frozen release manifest")
    matches = [item for item in entries if isinstance(item, dict) and item.get("id") == version]
    if len(matches) != 1:
        raise ReferenceError("Selected release is missing or ambiguous")
    entry = matches[0]
    metadata_url = validate_url(entry.get("metadataUrl"))
    metadata_sha1 = digest(entry.get("metadataSha1"), 40)
    cache = ignored_cache(repo, version)
    def load(name, url, sha1, limit, size=None):
        target = cache / name
        if target.is_symlink() or (target.exists() and (not target.is_file() or target.stat().st_nlink != 1 or target.stat().st_size > limit)):
            raise ReferenceError("Invalid reference cache entry")
        data = target.read_bytes() if target.exists() else fetch(url, limit)
        pinned(data, sha1, "sha1", size)
        if not target.exists():
            with target.open("xb") as stream:
                stream.write(data)
        return data
    metadata = load("metadata.json", metadata_url, metadata_sha1, MAX_METADATA)
    fields = parse_json(metadata, MAX_METADATA)
    if fields.get("id") != version:
        raise ReferenceError("Official metadata identity mismatch")
    try:
        server = fields["downloads"]["server"]
        url, sha1, size = validate_url(server["url"]), digest(server["sha1"], 40), server["size"]
    except (KeyError, TypeError):
        raise ReferenceError("Official server download is unavailable") from None
    if type(size) is not int or not 1 <= size <= MAX_SERVER:
        raise ReferenceError("Invalid official server size")
    binary = load("server.jar", url, sha1, MAX_SERVER, size)
    result = {"schemaVersion": 1, "release": version, "metadataUrl": metadata_url, "metadataSha1": metadata_sha1, "serverUrl": url, "serverSha1": sha1, "serverSize": len(binary), "serverSha256": hashlib.sha256(binary).hexdigest(), **inspect_server(binary, version), "executed": False, "worldCompatibilityClaim": "none"}
    receipt = cache / "receipt.json"
    if receipt.is_symlink() or (receipt.exists() and (not receipt.is_file() or receipt.stat().st_nlink != 1)):
        raise ReferenceError("Invalid reference receipt destination")
    receipt.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    ignored_cache(repo, version)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = acquire(args.manifest, Path(__file__).resolve().parents[1])
    except (ReferenceError, OSError):
        parser.exit(1, "Java reference acquisition or validation unavailable\n")
    print(json.dumps(result, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
