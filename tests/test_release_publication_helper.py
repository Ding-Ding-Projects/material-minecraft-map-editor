from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "publish_release.sh"
RUN_SHA = "a" * 40
WRONG_SHA = "b" * 40
VERSION = "1.2.3"
TAG = VERSION


def _bash_path(path: Path) -> str:
    resolved = path.resolve()
    value = resolved.as_posix()
    if len(value) >= 3 and value[1:3] == ":/":
        return f"/{value[0].lower()}{value[2:]}"
    return value


def _find_bash() -> str | None:
    candidates = [
        Path(r"C:\Program Files\Git\bin\bash.exe"),
        Path(r"C:\Program Files\Git\usr\bin\bash.exe"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return shutil.which("bash")


FAKE_PYTHON = r"""#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  *normalize_release_tag.py)
    printf '%s\n' "$RELEASE_TAG_EXPECTED_SOURCE"
    ;;
  *count_lines.py)
    printf '%s\n' 'category,total,non_blank,agent,person,unattributed' 'source,1,1,1,0,0'
    ;;
  *resolve_dim_sum_code_name.py)
    if [[ "$FAKE_SCENARIO" == 'dim_sum_unavailable' ]]; then
      printf '%s\n' 'DIM_SUM_STATUS=unavailable' 'DIM_SUM_WARNING=Catalog unavailable; release uses its version only.'
    elif [[ "$FAKE_SCENARIO" == 'dim_sum_inconsistent' ]]; then
      printf '%s\n' 'DIM_SUM_STATUS=unavailable' 'DIM_SUM_CODE_NAME=Har Gow · 蝦餃' 'DIM_SUM_PHOTO_URL=https://example.invalid/har-gow.jpg' 'DIM_SUM_WARNING=Catalog unavailable.'
    else
      printf '%s\n' 'DIM_SUM_STATUS=available' 'DIM_SUM_CODE_NAME=Har Gow · 蝦餃' 'DIM_SUM_PHOTO_URL=https://example.invalid/har-gow.jpg'
    fi
    ;;
  *release_timing.py)
    printf '%s\n' '00:01:00'
    ;;
  *)
    echo "Unexpected python3 invocation: $*" >&2
    exit 91
    ;;
esac
"""


FAKE_GIT = r"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\t' "$*" >> "$FAKE_STATE/git.log"
printf '\n' >> "$FAKE_STATE/git.log"
case "${1:-}" in
  ls-remote)
    if [[ -f "$FAKE_STATE/tag_sha" ]]; then
      printf '%s\trefs/tags/%s\n' "$(<"$FAKE_STATE/tag_sha")" "$RELEASE_TAG_EXPECTED_SOURCE"
    fi
    ;;
  fetch)
    ;;
  rev-parse)
    test -f "$FAKE_STATE/tag_sha"
    cat "$FAKE_STATE/tag_sha"
    ;;
  *)
    echo "Unexpected git invocation: $*" >&2
    exit 92
    ;;
esac
"""


FAKE_GH = r"""#!/usr/bin/env bash
set -euo pipefail
printf '%q ' "$@" >> "$FAKE_STATE/gh.log"
printf '\n' >> "$FAKE_STATE/gh.log"

release_inventory() {
  if [[ "$FAKE_SCENARIO" == 'inventory_failure' ]]; then
    exit 71
  fi
  if [[ "$FAKE_SCENARIO" == 'inventory_failure_after_draft' && -f "$FAKE_STATE/release_exists" ]]; then
    exit 72
  fi
  if [[ "$FAKE_SCENARIO" == 'existing_release' ]]; then
    printf '42\tfalse\t%s\n' "$RUN_SHA"
  elif [[ -f "$FAKE_STATE/release_exists" ]]; then
    printf '42\t%s\t%s\n' "$(<"$FAKE_STATE/draft")" "$(<"$FAKE_STATE/target")"
  fi
}

if [[ "${1:-}" == 'release' && "${2:-}" == 'create' ]]; then
  shift 2
  tag="$1"
  shift
  : > "$FAKE_STATE/uploaded_assets"
  notes_file=''
  target=''
  while (($#)); do
    case "$1" in
      --repo|--title)
        shift 2
        ;;
      --notes-file)
        notes_file="$2"
        shift 2
        ;;
      --target)
        target="$2"
        shift 2
        ;;
      --draft)
        shift
        ;;
      --*)
        echo "Unexpected release-create option: $1" >&2
        exit 73
        ;;
      *)
        basename -- "$1" >> "$FAKE_STATE/uploaded_assets"
        shift
        ;;
    esac
  done
  test "$tag" = "$RELEASE_TAG_EXPECTED_SOURCE"
  test -n "$notes_file"
  test "$target" = "$RUN_SHA"
  cp -- "$notes_file" "$FAKE_STATE/body"
  printf '%s\n' true > "$FAKE_STATE/draft"
  if [[ "$FAKE_SCENARIO" == 'wrong_draft_target' ]]; then
    printf '%s\n' 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb' > "$FAKE_STATE/target"
  else
    printf '%s\n' "$target" > "$FAKE_STATE/target"
  fi
  : > "$FAKE_STATE/hosted_assets"
  while IFS= read -r asset_name; do
    asset_path="$FAKE_ASSET_DIRECTORY/$asset_name"
    digest="$(sha256sum -- "$asset_path")"
    digest="${digest%% *}"
    if [[ "$FAKE_SCENARIO" == 'wrong_digest' && ! -s "$FAKE_STATE/hosted_assets" ]]; then
      digest='0000000000000000000000000000000000000000000000000000000000000000'
    fi
    printf '%s\tsha256:%s\n' "$asset_name" "$digest" >> "$FAKE_STATE/hosted_assets"
  done < "$FAKE_STATE/uploaded_assets"
  touch "$FAKE_STATE/release_exists"
  exit 0
fi

if [[ "${1:-}" != 'api' ]]; then
  echo "Unexpected gh invocation: $*" >&2
  exit 74
fi
shift

method='GET'
endpoint=''
jq_filter=''
body_mode=''
body_value=''
draft_value=''
while (($#)); do
  case "$1" in
    --method)
      method="$2"
      shift 2
      ;;
    --paginate|--silent)
      shift
      ;;
    --jq)
      jq_filter="$2"
      shift 2
      ;;
    -F|-f)
      form_flag="$1"
      form_value="$2"
      case "$form_value" in
        body=*) body_mode="$form_flag"; body_value="${form_value#body=}" ;;
        draft=*) draft_value="${form_value#draft=}" ;;
      esac
      shift 2
      ;;
    /*)
      endpoint="$1"
      shift
      ;;
    *)
      shift
      ;;
  esac
done

case "$endpoint" in
  */actions/runs/*/jobs\?per_page=100)
    printf '%s\n' '2026-08-10T12:00:00Z'
    ;;
  */releases\?per_page=100)
    release_inventory
    ;;
  */releases/42/assets\?per_page=100)
    count_file="$FAKE_STATE/asset_query_count"
    count=0
    [[ ! -f "$count_file" ]] || count="$(<"$count_file")"
    count=$((count + 1))
    printf '%s\n' "$count" > "$count_file"
    cat "$FAKE_STATE/hosted_assets"
    if [[ "$FAKE_SCENARIO" == 'terminal_tag_move' && "$count" -eq 2 ]]; then
      printf '%s\n' 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb' > "$FAKE_STATE/tag_sha"
    fi
    ;;
  */releases/42)
    if [[ "$method" == 'PATCH' && -n "$draft_value" ]]; then
      printf '%s\n' "$draft_value" > "$FAKE_STATE/draft"
      printf '%s\n' '2026-08-10T12:01:00Z'
    elif [[ "$method" == 'PATCH' && -n "$body_mode" ]]; then
      if [[ "$body_mode" == '-F' && "$body_value" == @* ]]; then
        cat -- "${body_value#@}" > "$FAKE_STATE/body"
      else
        printf '%s\n' "$body_value" > "$FAKE_STATE/body"
      fi
    elif [[ "$jq_filter" == '.body' ]]; then
      cat "$FAKE_STATE/body"
    elif [[ "$jq_filter" == '.draft' ]]; then
      cat "$FAKE_STATE/draft"
    else
      echo "Unsupported release-record query: $jq_filter" >&2
      exit 75
    fi
    ;;
  */git/refs)
    if [[ "$method" != 'POST' ]]; then
      exit 76
    fi
    if [[ "$FAKE_SCENARIO" == 'wrong_tag_race' ]]; then
      printf '%s\n' 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb' > "$FAKE_STATE/tag_sha"
      exit 77
    fi
    if [[ -f "$FAKE_STATE/tag_sha" ]]; then
      exit 78
    fi
    printf '%s\n' "$RUN_SHA" > "$FAKE_STATE/tag_sha"
    ;;
  *)
    echo "Unsupported gh api endpoint: $endpoint" >&2
    exit 79
    ;;
esac
"""


class ReleasePublicationHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bash = _find_bash()
        if cls.bash is None:
            raise unittest.SkipTest("Bash is required for publication helper tests")

    def _write_executable(self, path: Path, content: str) -> None:
        path.write_text(textwrap.dedent(content), encoding="utf-8", newline="\n")
        path.chmod(0o755)

    def _run(self, scenario: str) -> tuple[subprocess.CompletedProcess[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        temp_root = Path(temporary.name)
        state = temp_root / "state"
        fake_bin = temp_root / "bin"
        assets = temp_root / "release-assets"
        state.mkdir()
        fake_bin.mkdir()
        assets.mkdir()
        for name, content in {
            "Setup.exe": "setup",
            "RELEASES": f"release {VERSION}",
            f"Amulet-{VERSION}-full.nupkg": "full",
            f"Amulet-{VERSION}-delta.nupkg": "delta",
        }.items():
            (assets / name).write_text(content, encoding="utf-8")
        self._write_executable(fake_bin / "python3", FAKE_PYTHON)
        self._write_executable(fake_bin / "git", FAKE_GIT)
        self._write_executable(fake_bin / "gh", FAKE_GH)

        command = "\n".join(
            [
                f"export PATH='{_bash_path(fake_bin)}':\"$PATH\"",
                f"export FAKE_STATE='{_bash_path(state)}'",
                f"export FAKE_ASSET_DIRECTORY='{_bash_path(assets)}'",
                f"cd '{_bash_path(ROOT)}'",
                f"bash '{_bash_path(HELPER)}' '{_bash_path(assets)}'",
            ]
        )
        environment = os.environ.copy()
        environment.update(
            {
                "FAKE_SCENARIO": scenario,
                "GITHUB_REPOSITORY": "example/amulet",
                "RELEASE_TAG_EXPECTED_VERSION": VERSION,
                "RELEASE_TAG_EXPECTED_SOURCE": TAG,
                "RELEASE_TAG_INPUT": TAG,
                "RELEASE_TAG_FALLBACK": TAG,
                "RUN_ID": "1234",
                "RUN_NUMBER": "55",
                "RUN_SHA": RUN_SHA,
            }
        )
        stdout_path = temp_root / "stdout.txt"
        stderr_path = temp_root / "stderr.txt"
        with stdout_path.open("wb") as stdout_file, stderr_path.open(
            "wb"
        ) as stderr_file:
            result = subprocess.run(
                [self.bash, "--noprofile", "--norc", "-c", command],
                check=False,
                stdout=stdout_file,
                stderr=stderr_file,
                env=environment,
                timeout=15,
            )
        result.stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
        result.stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
        return result, state

    def _gh_log(self, state: Path) -> str:
        log = state / "gh.log"
        return log.read_text(encoding="utf-8") if log.exists() else ""

    def assert_not_published(self, state: Path) -> None:
        self.assertNotIn("draft=false", self._gh_log(state))

    def assert_no_tag_mutation(self, state: Path) -> None:
        self.assertNotIn("/git/refs", self._gh_log(state))

    def test_success_round_trips_body_digests_delta_and_terminal_tag(self):
        result, state = self._run("success")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        uploaded = (state / "uploaded_assets").read_text(encoding="utf-8")
        self.assertIn(f"Amulet-{VERSION}-delta.nupkg", uploaded)
        body = (state / "body").read_text(encoding="utf-8")
        self.assertIn(f"Release commit: {RUN_SHA}", body)
        self.assertIn("Workflow duration: 00:01:00", body)
        self.assertIn("body=@", self._gh_log(state))
        self.assertGreaterEqual(
            (state / "git.log").read_text(encoding="utf-8").count("rev-parse"),
            3,
        )

    def test_wrong_api_draft_target_cannot_be_replaced_by_self_attestation(self):
        result, state = self._run("wrong_draft_target")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("did not match run commit", result.stdout + result.stderr)
        self.assert_not_published(state)
        self.assert_no_tag_mutation(state)

    def test_explicit_unavailable_dim_sum_status_publishes_version_only(self):
        result, state = self._run("dim_sum_unavailable")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        body = (state / "body").read_text(encoding="utf-8")
        self.assertIn("this release uses its version only", body)
        self.assertIn("Catalog unavailable", body)

    def test_inconsistent_unavailable_dim_sum_shape_fails_closed(self):
        result, state = self._run("dim_sum_inconsistent")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must not include a code name", result.stdout + result.stderr)
        self.assertNotIn("release create", self._gh_log(state))
        self.assert_no_tag_mutation(state)

    def test_wrong_hosted_digest_stops_before_publication(self):
        result, state = self._run("wrong_digest")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("did not match the release notes", result.stdout + result.stderr)
        self.assert_not_published(state)
        self.assert_no_tag_mutation(state)

    def test_inventory_failure_stops_before_creating_a_draft(self):
        result, state = self._run("inventory_failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("release create", self._gh_log(state))
        self.assert_not_published(state)
        self.assert_no_tag_mutation(state)

    def test_inventory_failure_after_draft_still_stops_before_publication(self):
        result, state = self._run("inventory_failure_after_draft")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("release create", self._gh_log(state))
        self.assert_not_published(state)
        self.assert_no_tag_mutation(state)

    def test_existing_release_is_never_mutated(self):
        result, state = self._run("existing_release")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "Refusing to mutate existing release", result.stdout + result.stderr
        )
        log = self._gh_log(state)
        self.assertNotIn("release create", log)
        self.assertNotIn("PATCH", log)
        self.assert_no_tag_mutation(state)

    def test_wrong_sha_tag_race_stops_before_publication(self):
        result, state = self._run("wrong_tag_race")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("instead of run commit", result.stdout + result.stderr)
        self.assert_not_published(state)

    def test_terminal_tag_move_makes_the_helper_fail(self):
        result, _state = self._run("terminal_tag_move")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("instead of run commit", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
