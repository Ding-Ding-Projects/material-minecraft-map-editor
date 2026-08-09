# Roadmap

## Material 3 modernization

- ✅ Shared wxPython colour, typography, spacing, shape, and control-size tokens.
- 🏃 Roll the tokens through remaining dialogs and editor pages.
- ✅ Persisted language, funny-level, appearance, and regex-builder foundation.
- ✅ Versioned named appearance presets, validated JSON interchange, and
  native Appearance-tab load/save/import/export and staged reset controls.
- ✅ Versioned scheduled-settings foundation with local precedence and boundary tests.
- 🏃 Complete full per-element appearance editing and live tab-strip projection;
  the native tab/group manager now covers persisted docking, pinning, grouping,
  search, and notebook activation. Scheduled settings have native date/time
  pickers and local history has a native browser; remaining global-memory
  surfaces still need migration.

## Windows delivery

- ✅ Unsigned PyInstaller + Squirrel.Windows contract with Setup.exe, RELEASES,
  full nupkg, and Authenticode `NotSigned` checks.
- ✅ Bounded startup/manual update check with an unsigned status-bar state.
- ✅ Hosted release publication produces unsigned Setup.exe, RELEASES, and the
  full nupkg; ⏳ end-to-end restart/update proof remains.

## Documentation

- ✅ Material 3 responsive landing/docs source under `docs/site/`, routed to the
  owner-controlled repository.
- ✅ wx-independent offline documentation bundle with deterministic feature
  discovery, SHA-256 completeness checks, local article search, and internal
  link navigation.
- ⏳ Publish through an owner-controlled host and verify the live URL; no URL is
  claimed while that external host is absent.
