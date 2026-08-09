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
  timestamp, push builds validate a prior index/package pair before seeding
  delta generation, and release notes report reproducible line attribution.
  A selected pair now makes a verified current delta asset mandatory while the
  client feed remains full-only; ⏳ hosted delta publication and a three-version
  installed-client update proof remain before advertising delta delivery.

## Documentation

- 🏃 Material 3 landing shell under `docs/site/`; local feature articles,
  complete settings parity, and owner-controlled publication remain in progress.
- ✅ wx-independent offline documentation bundle with deterministic feature
  discovery, SHA-256 completeness checks, local article search, and internal
  link navigation.
- ⏳ Publish through an owner-controlled host and verify the live URL; no URL is
  claimed while that external host is absent.
