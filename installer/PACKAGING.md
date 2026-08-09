# Windows packaging contract

The supported Windows release artifact is an **unsigned NSIS installer** built
from `installer/windows.nsi` and the PyInstaller bundle. The release workflow
must verify that the expected `Amulet-<version>-Windows-<architecture>.exe`
exists and that `Get-AuthenticodeSignature` reports `NotSigned`.

This project is a native Python/PyInstaller application and does not ship the
Electron/Squirrel.Windows update metadata (`RELEASES`, `.nupkg`, or Squirrel
delta packages). CI therefore must not label the NSIS executable as a
Squirrel.Windows installer or silently substitute Squirrel packaging. Adding a
Squirrel channel would require a separately designed update contract and
runtime integration; until then, the NSIS artifact is the only supported
Windows installer.

Code signing is intentionally disabled. Users may see an unknown-publisher or
SmartScreen warning when installing the unsigned artifact.
