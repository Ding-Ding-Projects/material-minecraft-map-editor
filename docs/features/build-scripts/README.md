# One-click Windows build scripts

## Behaviour

`build.bat` probes Python 3.11, installs it for the current user through
`winget` or the official python.org installer when needed, refreshes the current
process path, installs declared build/runtime dependencies, and installs the
package in editable mode. `/s`, `--silent`, or `SILENT=1` suppresses prompts.

`build-installer.bat` invokes the silent source bootstrap, installs PyInstaller,
builds `installer/Amulet.spec`, and runs the same pinned Squirrel.Windows path as
CI. It verifies `Setup.exe`, `RELEASES`, and the full package before printing
SHA-256 digests. No script signs, publishes, tags, or creates a release.

## Failure and security boundaries

The bootstrap is user-scoped and fails closed when Python 3.11 cannot be started
after installation. Code signing and credentials are deliberately absent. The
resulting Squirrel artifacts are unsigned and may trigger an unknown-publisher
or SmartScreen warning.

## Verification

On 2026-08-09, this checkout passed `cmd /c build.bat /s` and
`cmd /c build-installer.bat /s`; the latter produced all three required unsigned
Squirrel artifacts locally. CI remains the authoritative release proof.
