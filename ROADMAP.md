# Roadmap

## Material 3 modernization

- ✅ Shared wxPython colour, typography, spacing, shape, and control-size tokens.
- ✅ Owner-drawn M3 shell card, action buttons, caption controls, and application
  command bar, with a quiet startup path and no acknowledgement or purchase gate.
- 🏃 Roll the tokens through remaining dialogs and editor pages.
- ✅ Persisted language, funny-level, appearance, and regex-builder foundation.
- ✅ Versioned named appearance presets, validated JSON interchange, and
  native Appearance-tab load/save/import/export and staged reset controls.
- ✅ Versioned scheduled-settings foundation with local precedence and boundary tests.
- 🏃 Complete full per-element appearance editing and live tab-strip projection;
  native controls now expose a bounded persisted M3 element editor, and the
  native tab/group manager covers persisted docking, pinning, grouping, search,
  and notebook activation. Scheduled settings have native date/time pickers
  and local history has a native browser; remaining global-memory surfaces
  still need migration.

## Windows delivery

- ✅ Unsigned PyInstaller + Squirrel.Windows contract with Setup.exe, RELEASES,
  full nupkg, and Authenticode `NotSigned` checks.
- ✅ Bounded startup/manual update check with an unsigned status-bar state.
- ✅ Hosted release publication produces unsigned Setup.exe, RELEASES, and the
  full nupkg. Publication timing is measured through GitHub's confirmed publish
  timestamp, push builds safely seed delta generation when an older full
  package exists, and release notes report reproducible line attribution;
  ⏳ end-to-end restart/update proof remains.

## Documentation

- ✅ Dependency-free Material 3 landing page under `docs/site/`, including all
  18 feature articles in reviewed English and Hong Kong Cantonese, complete
  localized site chrome, semantic language switching, suggested navigation,
  four full regex builders, settings, and deterministic Docker/Sites staging.
- ✅ wx-independent offline documentation bundle with deterministic feature
  discovery, SHA-256 completeness checks, local article search, and internal
  link navigation.
- ✅ Read-only post-release staging consumes an exact API-verified Build Windows
  run artifact, rejects out-of-order releases, and avoids committing a changing
  release manifest back into the source repository.
- ⏳ Publish through an owner-controlled host or a separately controlled Sites
  source repository and verify the live URL; no URL is claimed while a hostname,
  HTTPS route, and authenticated publication target are absent.
