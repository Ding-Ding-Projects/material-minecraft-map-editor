# Contributing to Amulet Map Editor

Thank you for helping improve Amulet Map Editor. Keep changes focused, preserve
existing user data and behavior unless the change explicitly replaces it, and
include tests for every behavior change.

## Prepare the checkout

On Windows, run `build.bat /s` from the repository root to bootstrap the
supported toolchain and build the application without prompts. Run
`build-installer.bat /s` only when the change affects packaging or release
delivery. The installer is intentionally unsigned.

## Verify a change

Run the narrowest relevant tests while developing, then run the complete local
suite before opening a pull request:

```powershell
py -3 -m pytest -q
py -3 -m unittest discover -v
py -3 run_static_checks.py
```

Changes to GitHub Actions workflows should also pass the repository's focused
workflow contract tests and `actionlint -shellcheck=` on Windows. The hosted
workflow performs the shellcheck portion that is not reliable through the
Windows actionlint integration.

## Documentation and accessibility

Update the matching article under `docs/features/` for user-visible behavior.
Keep keyboard operation, accessible names and states, visible focus, reduced
motion, narrow layouts, high display scales, and the longest localized copy in
scope. Regenerate the offline documentation bundle with
`py -3 scripts/build_docs_bundle.py` after article changes.

## Pull requests

Describe the behavior, the cause of any defect, the files changed, and the
exact verification performed. Do not include credentials, private data,
generated dependency trees, build output, or machine-specific paths. Code
signing is not part of this project; do not add signing keys, certificates, or
signing services.

For a security issue that should not be public, use the repository's private
security-reporting channel instead of opening a public issue.
