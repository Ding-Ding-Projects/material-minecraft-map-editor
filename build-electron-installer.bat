@echo off
setlocal EnableExtensions
set "SILENT_MODE=0"
if /I "%~1"=="/s" set "SILENT_MODE=1"
if /I "%~1"=="--silent" set "SILENT_MODE=1"
if "%SILENT%"=="1" set "SILENT_MODE=1"

rem build-electron-installer.bat -- produces the unsigned Squirrel.Windows
rem installer for the Electron build, through electron-builder. Never
rem configures, requests, or invokes a code signer: every signing control in
rem electron-builder.yml is explicitly false, and this script verifies that
rem the artifact it produced actually reports as unsigned before it claims
rem success.

call "%~dp0build-electron.bat" /s
if errorlevel 1 (
  echo [installer-electron] build-electron.bat did not complete -- see the
  echo [installer-electron] messages above. If package.json/electron\ do not
  echo [installer-electron] exist yet, this script cannot produce an installer
  echo [installer-electron] until the electron-shell lane lands them.
  exit /b 1
)

if not exist "%~dp0package.json" (
  echo [installer-electron] no package.json -- nothing to package yet.
  exit /b 1
)

set "BUILDER_CONFIG=%~dp0electron\electron-builder.yml"
if not exist "%BUILDER_CONFIG%" (echo [installer-electron] electron\electron-builder.yml is missing.& exit /b 1)

if "%SILENT_MODE%"=="0" echo [installer-electron] verifying no code-signing control is enabled
findstr /I /C:"forceCodeSigning: true" "%BUILDER_CONFIG%" >nul 2>nul
if not errorlevel 1 (
  echo [installer-electron] electron\electron-builder.yml enables code signing -- refusing to build.
  echo [installer-electron] Code signing is permanently prohibited for this project.
  exit /b 1
)
findstr /I /C:"signAndEditExecutable: true" "%BUILDER_CONFIG%" >nul 2>nul
if not errorlevel 1 (
  echo [installer-electron] electron\electron-builder.yml enables executable signing -- refusing to build.
  exit /b 1
)

set "DIST_DIR=%~dp0dist\electron"
if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"

if "%SILENT_MODE%"=="0" echo [installer-electron] packaging the Squirrel.Windows installer
call npm run electron:dist || (echo [installer-electron] electron-builder packaging failed.& exit /b 1)

rem electron-builder writes Squirrel output (Setup.exe, RELEASES, .nupkg)
rem under the directories.output path configured in electron-builder.yml,
rem which is dist\electron relative to the repository root. Search rather
rem than assume one fixed subdirectory, since electron-builder has moved
rem that layout across versions.
if not exist "%DIST_DIR%" (echo [installer-electron] %DIST_DIR% was not produced.& exit /b 1)

set "SETUP_EXE="
for /f "delims=" %%f in ('dir /s /b "%DIST_DIR%\*Setup*.exe" 2^>nul') do if not defined SETUP_EXE set "SETUP_EXE=%%f"
if not defined SETUP_EXE (echo [installer-electron] no Setup*.exe was produced under %DIST_DIR%\.& exit /b 1)

set "RELEASES_FILE="
for /f "delims=" %%f in ('dir /s /b "%DIST_DIR%\RELEASES" 2^>nul') do if not defined RELEASES_FILE set "RELEASES_FILE=%%f"
if not defined RELEASES_FILE (echo [installer-electron] no RELEASES index was produced under %DIST_DIR%\.& exit /b 1)

set "NUPKG_FOUND=0"
for /f "delims=" %%f in ('dir /s /b "%DIST_DIR%\*-full.nupkg" 2^>nul') do set "NUPKG_FOUND=1"
if "%NUPKG_FOUND%"=="0" (echo [installer-electron] no full .nupkg was produced under %DIST_DIR%\.& exit /b 1)

if "%SILENT_MODE%"=="0" echo [installer-electron] verifying the installer is unsigned
rem signtool is not guaranteed present on a fresh machine (it ships with the
rem Windows SDK, not Windows itself), and Get-AuthenticodeSignature depends
rem on a PowerShell module that is not reliably autoloadable in every host
rem shell. Verify from the file's own structure instead: an Authenticode
rem signature is an appended PKCS#7 blob whose presence certutil's own
rem -dump reports, with no external tool or module needed.
certutil -dump "%SETUP_EXE%" | findstr /I /C:"Signer Certificate" >nul 2>nul
if not errorlevel 1 (
  echo [installer-electron] %SETUP_EXE% appears to carry a signer certificate -- expected unsigned.
  exit /b 1
)

echo [installer-electron] artifact: %SETUP_EXE%
echo [installer-electron] SHA-256:
certutil -hashfile "%SETUP_EXE%" SHA256 | findstr /R /V /C:"CertUtil" /C:"SHA256"
echo [installer-electron] status: unsigned Squirrel.Windows installer -- code signing is
echo [installer-electron] permanently disabled for this project; expect an
echo [installer-electron] unknown-publisher / SmartScreen warning on first run.
exit /b 0
