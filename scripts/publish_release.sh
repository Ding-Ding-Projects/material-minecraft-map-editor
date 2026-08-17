#!/usr/bin/env bash

# Publish one immutable, unsigned Squirrel.Windows release from a validated
# artifact directory. This helper is intentionally executable outside Actions
# so its fail-closed behavior can be tested with hostile GitHub/Git fixtures.

set -euo pipefail

artifact_directory="${1:-release-assets}"

require_environment() {
  local name
  for name in \
    GITHUB_REPOSITORY \
    RELEASE_TAG_EXPECTED_VERSION \
    RUN_ID \
    RUN_SHA; do
    test -n "${!name:-}" || {
      echo "Required environment variable is empty: $name"
      exit 1
    }
  done
}

require_environment
[[ "$RUN_SHA" =~ ^[0-9a-f]{40}$ ]] || {
  echo "Run commit is not a full Git SHA: $RUN_SHA"
  exit 1
}

notes_file="$(mktemp)"
asset_table_file="$(mktemp)"
release_file_list="$(mktemp)"
trap 'rm -f "$notes_file" "$asset_table_file" "$release_file_list"' EXIT

test -d "$artifact_directory" || {
  echo "Downloaded release artifact directory is missing: $artifact_directory"
  exit 1
}
find "$artifact_directory" -type f -print0 > "$release_file_list" || {
  echo 'Could not enumerate downloaded release artifacts'
  exit 1
}
mapfile -d '' -t release_files < "$release_file_list"

setup_name='Setup.exe'
releases_name='RELEASES'
nupkg_name="Amulet-$RELEASE_TAG_EXPECTED_VERSION-full.nupkg"
delta_name="Amulet-$RELEASE_TAG_EXPECTED_VERSION-delta.nupkg"
setup_matches=()
releases_matches=()
nupkg_matches=()
delta_matches=()
for path in "${release_files[@]}"; do
  case "$(basename -- "$path")" in
    "$setup_name") setup_matches+=("$path") ;;
    "$releases_name") releases_matches+=("$path") ;;
    "$nupkg_name") nupkg_matches+=("$path") ;;
    "$delta_name") delta_matches+=("$path") ;;
    *) echo "Unexpected release artifact: $path"; exit 1 ;;
  esac
done
(( ${#setup_matches[@]} == 1 )) || {
  echo "Expected exactly one Setup.exe, found ${#setup_matches[@]}"
  exit 1
}
(( ${#releases_matches[@]} == 1 )) || {
  echo "Expected exactly one RELEASES index, found ${#releases_matches[@]}"
  exit 1
}
(( ${#nupkg_matches[@]} == 1 )) || {
  echo "Expected exactly one full Squirrel package, found ${#nupkg_matches[@]}"
  exit 1
}
(( ${#delta_matches[@]} <= 1 )) || {
  echo "Duplicate release asset basename: $delta_name"
  exit 1
}

setup_path="${setup_matches[0]}"
releases_path="${releases_matches[0]}"
nupkg_path="${nupkg_matches[0]}"
upload_paths=("$setup_path" "$releases_path" "$nupkg_path")
if (( ${#delta_matches[@]} == 1 )); then
  upload_paths+=("${delta_matches[0]}")
fi

# Both event data and the fallback stay in environment variables; the helper
# validates them before the value reaches the release API.
tag="$(python3 scripts/normalize_release_tag.py)"

verify_tag_target() {
  git fetch --force --no-tags origin "refs/tags/$tag:refs/tags/$tag"
  local tag_commit
  tag_commit="$(git rev-parse "$tag^{commit}")"
  test "$tag_commit" = "$RUN_SHA" || {
    echo "Release tag $tag resolves to $tag_commit instead of run commit $RUN_SHA"
    exit 1
  }
}

existing_tag_ref="$(git ls-remote --tags origin "refs/tags/$tag")" || {
  echo "Could not inspect the existing release tag $tag"
  exit 1
}
if [[ -n "$existing_tag_ref" ]]; then
  verify_tag_target
fi

started="$(
  gh api --paginate "/repos/$GITHUB_REPOSITORY/actions/runs/$RUN_ID/jobs?per_page=100" \
    --jq '.jobs[] | select(.name | startswith("deploy")) | .started_at' |
    sed -n '1p'
)"
test -n "$started" || {
  echo 'Could not resolve the deploy job start time for release timing notes'
  exit 1
}

line_table="$(python3 scripts/count_lines.py)"
dim_sum_result="$(python3 scripts/resolve_dim_sum_code_name.py)" || {
  echo 'Dim-sum code-name resolver failed'
  exit 1
}
DIM_SUM_STATUS=''
DIM_SUM_CODE_NAME=''
DIM_SUM_PHOTO_URL=''
DIM_SUM_WARNING=''
dim_sum_status_count=0
dim_sum_name_count=0
dim_sum_photo_count=0
dim_sum_warning_count=0
while IFS='=' read -r key value; do
  case "$key" in
    DIM_SUM_STATUS)
      DIM_SUM_STATUS="$value"
      dim_sum_status_count=$((dim_sum_status_count + 1))
      ;;
    DIM_SUM_CODE_NAME)
      DIM_SUM_CODE_NAME="$value"
      dim_sum_name_count=$((dim_sum_name_count + 1))
      ;;
    DIM_SUM_PHOTO_URL)
      DIM_SUM_PHOTO_URL="$value"
      dim_sum_photo_count=$((dim_sum_photo_count + 1))
      ;;
    DIM_SUM_WARNING)
      DIM_SUM_WARNING="$value"
      dim_sum_warning_count=$((dim_sum_warning_count + 1))
      ;;
    '') ;;
    *)
      echo "Dim-sum resolver returned an unknown field: $key"
      exit 1
      ;;
  esac
done <<< "$dim_sum_result"
test "$dim_sum_status_count" -eq 1 || {
  echo 'Dim-sum resolver must return exactly one DIM_SUM_STATUS field'
  exit 1
}
case "$DIM_SUM_STATUS" in
  available)
    test "$dim_sum_name_count" -eq 1 && test -n "$DIM_SUM_CODE_NAME" || {
      echo 'Available dim-sum result must include exactly one non-empty code name'
      exit 1
    }
    test "$dim_sum_photo_count" -eq 1 && test -n "$DIM_SUM_PHOTO_URL" || {
      echo 'Available dim-sum result must include exactly one non-empty public photo URL'
      exit 1
    }
    test "$dim_sum_warning_count" -eq 0 || {
      echo 'Available dim-sum result must not include an unavailable warning'
      exit 1
    }
    ;;
  unavailable)
    test "$dim_sum_name_count" -eq 0 && test -z "$DIM_SUM_CODE_NAME" || {
      echo 'Unavailable dim-sum result must not include a code name'
      exit 1
    }
    test "$dim_sum_photo_count" -eq 0 && test -z "$DIM_SUM_PHOTO_URL" || {
      echo 'Unavailable dim-sum result must not include a public photo URL'
      exit 1
    }
    test "$dim_sum_warning_count" -eq 1 && test -n "$DIM_SUM_WARNING" || {
      echo 'Unavailable dim-sum result must include exactly one non-empty warning'
      exit 1
    }
    printf 'WARNING: %s\n' "$DIM_SUM_WARNING" >&2
    ;;
  *)
    echo "Dim-sum resolver returned an unsupported status: $DIM_SUM_STATUS"
    exit 1
    ;;
esac

write_notes() {
  local completed="$1"
  local duration="$2"
  {
    printf '%s\n' '<!-- amulet-auto-release -->'
    printf '%s\n' 'Unsigned Squirrel.Windows release. Code signing is intentionally disabled; the operating system may show an unknown-publisher warning.'
    printf '%s\n' "Release commit: $RUN_SHA"
    printf '%s\n' "Workflow started: $started"
    printf '%s\n' "Workflow completed: $completed"
    printf '%s\n\n' "Workflow duration: $duration"
    printf '%s\n' 'Release assets (SHA-256):'
    printf '%s\n' '```csv'
    printf '%s\n' 'asset,sha256'
    printf '%s\n' "$asset_table"
    printf '%s\n\n' '```'
    printf '%s\n' 'Line count and surviving attribution (CI, scripts/count_lines.py):'
    printf '%s\n' '```csv'
    printf '%s\n' "$line_table"
    printf '%s\n\n' '```'
    printf '%s\n' 'Generated text and deliberately excluded text are separate rows; repository-grand-total is every tracked line-oriented text file counted. Binary assets are not line-counted.'
    printf '%s\n' 'Agent attribution uses surviving git-blame lines whose commit author or Co-Authored-By trailer identifies an automation agent; person and unattributed lines are reported separately.'
    if [[ "$DIM_SUM_STATUS" == 'available' ]]; then
      printf '%s\n' "Dim-sum code name: $DIM_SUM_CODE_NAME"
      printf '%s\n' "Dim-sum public photo: $DIM_SUM_PHOTO_URL"
    else
      printf '%s\n' 'Dim-sum code name: unavailable; this release uses its version only.'
      printf '%s\n' "Dim-sum catalog warning: $DIM_SUM_WARNING"
    fi
  } > "$notes_file"
}

: > "$asset_table_file"
for path in "${upload_paths[@]}"; do
  test -f "$path" || {
    echo "Release asset was not found before hashing: $path"
    exit 1
  }
  asset_name="$(basename -- "$path")"
  [[ "$asset_name" =~ ^[A-Za-z0-9._-]+$ ]] || {
    echo "Release asset name is not safe for the notes table: $asset_name"
    exit 1
  }
  digest_line="$(sha256sum -- "$path")"
  asset_sha256="${digest_line%% *}"
  [[ "$asset_sha256" =~ ^[0-9a-f]{64}$ ]] || {
    echo "Could not compute a valid SHA-256 digest for $asset_name"
    exit 1
  }
  printf '%s,%s\n' "$asset_name" "$asset_sha256" >> "$asset_table_file"
done
LC_ALL=C sort -o "$asset_table_file" "$asset_table_file"
duplicate_asset_name="$(cut -d, -f1 "$asset_table_file" | uniq -d | sed -n '1p')"
test -z "$duplicate_asset_name" || {
  echo "Duplicate release asset basename: $duplicate_asset_name"
  exit 1
}
asset_table="$(<"$asset_table_file")"
test -n "$asset_table" || {
  echo 'Release asset hash table is empty'
  exit 1
}

find_release_record() {
  gh api --paginate "/repos/$GITHUB_REPOSITORY/releases?per_page=100" \
    --jq ".[] | select(.tag_name == \"$tag\") | [.id, .draft, .target_commitish] | @tsv"
}

verify_hosted_assets() {
  local hosted_asset_rows hosted_asset_count expected_asset_count
  local asset_name asset_sha256 hosted_digest hosted_match_count
  hosted_asset_rows="$(
    gh api --paginate "/repos/$GITHUB_REPOSITORY/releases/$release_id/assets?per_page=100" \
      --jq '.[] | [.name, .digest] | @tsv'
  )" || {
    echo "Could not read hosted assets for release $release_id"
    exit 1
  }
  expected_asset_count="$(awk 'END { print NR }' "$asset_table_file")"
  hosted_asset_count="$(awk 'NF { count++ } END { print count + 0 }' <<< "$hosted_asset_rows")"
  test "$hosted_asset_count" -eq "$expected_asset_count" || {
    echo "Published asset count $hosted_asset_count did not match expected count $expected_asset_count"
    exit 1
  }
  while IFS=',' read -r asset_name asset_sha256; do
    hosted_match_count="$(
      awk -F '\t' -v expected="$asset_name" '$1 == expected { count++ } END { print count + 0 }' \
        <<< "$hosted_asset_rows"
    )"
    test "$hosted_match_count" -eq 1 || {
      echo "Hosted asset inventory did not contain exactly one $asset_name entry"
      exit 1
    }
    hosted_digest="$(
      awk -F '\t' -v expected="$asset_name" '$1 == expected { print $2 }' \
        <<< "$hosted_asset_rows"
    )"
    test "$hosted_digest" = "sha256:$asset_sha256" || {
      echo "Published digest for $asset_name did not match the release notes: $hosted_digest"
      exit 1
    }
  done < "$asset_table_file"
}

release_record="$(find_release_record)" || {
  echo "Could not inspect release inventory for $tag"
  exit 1
}
release_record_count="$(awk 'NF { count++ } END { print count + 0 }' <<< "$release_record")"
(( release_record_count <= 1 )) || {
  echo "Release inventory contained duplicate records for $tag"
  exit 1
}
if (( release_record_count != 0 )); then
  echo "Refusing to mutate existing release $tag; choose a new canonical tag"
  exit 1
fi

write_notes 'publication-pending' 'publication-pending'
gh release create "$tag" "${upload_paths[@]}" \
  --repo "$GITHUB_REPOSITORY" \
  --title "Amulet Map Editor $tag" \
  --notes-file "$notes_file" \
  --target "$RUN_SHA" \
  --draft

release_record="$(find_release_record)" || {
  echo "Could not locate the new draft release $tag"
  exit 1
}
release_record_count="$(awk 'NF { count++ } END { print count + 0 }' <<< "$release_record")"
test "$release_record_count" -eq 1 || {
  echo "Expected exactly one draft release record for $tag"
  exit 1
}
IFS=$'\t' read -r release_id release_is_draft release_target <<< "$release_record"
test "$release_is_draft" = 'true' || {
  echo "New release $tag was not staged as a draft"
  exit 1
}
test "$release_target" = "$RUN_SHA" || {
  echo "Draft release target $release_target did not match run commit $RUN_SHA"
  exit 1
}

draft_body="$(gh api "/repos/$GITHUB_REPOSITORY/releases/$release_id" --jq '.body')" || {
  echo "Could not read the draft release body for $release_id"
  exit 1
}
grep -Fqx "Release commit: $RUN_SHA" <<< "$draft_body"
while IFS=',' read -r asset_name asset_sha256; do
  grep -Fqx "$asset_name,$asset_sha256" <<< "$draft_body"
done < "$asset_table_file"
verify_hosted_assets

if ! gh api --method POST "/repos/$GITHUB_REPOSITORY/git/refs" \
  -f ref="refs/tags/$tag" -f sha="$RUN_SHA" --silent; then
  raced_tag_ref="$(git ls-remote --tags origin "refs/tags/$tag")" || {
    echo "Could not inspect the release tag after a refused create: $tag"
    exit 1
  }
  test -n "$raced_tag_ref" || {
    echo "Could not create release tag $tag at run commit $RUN_SHA"
    exit 1
  }
fi
verify_tag_target

completed="$(
  gh api --method PATCH "/repos/$GITHUB_REPOSITORY/releases/$release_id" \
    -F draft=false --jq '.published_at'
)"
test -n "$completed" && test "$completed" != 'null' || {
  echo 'GitHub did not report a publication completion timestamp'
  exit 1
}
verify_tag_target

duration="$(python3 scripts/release_timing.py --started "$started" --completed "$completed")"
write_notes "$completed" "$duration"
gh api --method PATCH "/repos/$GITHUB_REPOSITORY/releases/$release_id" \
  -F "body=@$notes_file" --silent

is_draft="$(gh api "/repos/$GITHUB_REPOSITORY/releases/$release_id" --jq '.draft')"
test "$is_draft" = 'false' || {
  echo 'Release remained a draft after publication'
  exit 1
}
final_body="$(gh api "/repos/$GITHUB_REPOSITORY/releases/$release_id" --jq '.body')"
grep -Fqx "Release commit: $RUN_SHA" <<< "$final_body"
grep -Fqx "Workflow completed: $completed" <<< "$final_body"
grep -Fqx "Workflow duration: $duration" <<< "$final_body"
while IFS=',' read -r asset_name asset_sha256; do
  grep -Fqx "$asset_name,$asset_sha256" <<< "$final_body"
done < "$asset_table_file"
verify_hosted_assets
verify_tag_target
