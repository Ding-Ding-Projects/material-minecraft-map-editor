# Appearance preset foundation

## Behaviour

`amulet_map_editor.api.appearance_presets` provides a wx-independent model for
named appearance presets. Each preset captures one complete, versioned set of
the existing `Preferences` appearance fields: theme, density, accent colour,
UI font family, and UI scale. Applying a preset writes only those five fields
through the existing preferences API, so language, funny levels, and dialog
emoji settings remain untouched.

The library supports case-insensitive preset lookup, explicit replacement,
deletion, a per-property reset, and an appearance-only global reset. Reset
values are the documented shipped values from `AppearanceValues`; the broader
`preferences.reset()` behaviour is unchanged.

This is a persistence and validation foundation. It does not claim that every
wx element already consumes every appearance value or has a live editor.

## Storage and configuration

The active appearance remains in the existing `amulet_preferences` record and
its fields are unchanged. Theme and density constants are shared with that
model so the accepted values cannot drift.

Named presets use a separate `amulet_appearance_presets` record with schema
version `1`, avoiding a breaking change to existing profiles. Up to 100 presets
may be stored. Names are unique case-insensitively and limited to 64 characters.

`save_preset(name)` captures the current appearance. A caller may instead pass
an `AppearanceValues` instance. `apply_preset(name)`, `reset_property(name)`,
and `reset_appearance()` return the updated `Preferences` value.

## Export and import

`export_preset()` emits deterministic UTF-8 JSON with the schema identifier
`amulet-appearance-preset` and version `1`. `import_preset()` accepts text or
UTF-8 bytes, validates the complete schema, and rejects unknown or missing
fields, unsupported versions, duplicate names, control characters, oversized
fonts/imports, invalid colours, and scale values outside 0.8–2.0. Replacement
must be explicitly requested with `replace=True`.

## Failure modes

- A malformed import raises `AppearancePresetValidationError` and is not saved.
- Applying an unknown preset raises `KeyError` and changes nothing.
- Malformed readable storage and unsupported versions fail closed. Save remains
  blocked so a future or damaged document cannot be silently overwritten.
- A historical seven-digit accent accepted by the base preferences model is
  captured as the shipped accent because its alpha meaning is ambiguous;
  imports continue to require the documented six- or eight-digit form.
- Resetting an unknown or non-appearance property raises `KeyError`.

## Security considerations

Import size is bounded to 32 KiB. The importer requires exact keys and does not
instantiate arbitrary classes. Font names and preset names reject control
characters. Stored documents fail closed before the load-modify-write operation;
cross-process writers still require coordination from a future persistence
layer. The model performs no file, network, or wx operations; file-picker and
user-notification behaviour belongs to a future UI integration.

## Verification

Run:

```text
python -m unittest tests.test_appearance_presets
```

The focused suite covers persistence and application through the existing
preferences API, deterministic export/import, duplicate handling, malformed
and future schemas without overwrite, bounded values, legacy accents, corrupt
stored entries, and both reset paths preserving non-appearance preferences.

## Suggested articles

- [Scheduled settings](../scheduled-settings/README.md) explains temporary
  local theme, density, and accent overrides.
- [Changelog](../changelog/README.md) explains the offline release history.
