@echo off
setlocal EnableExtensions
set "SILENT_MODE=0"
if /I "%~1"=="/s" set "SILENT_MODE=1"
if /I "%~1"=="--silent" set "SILENT_MODE=1"
if "%SILENT%"=="1" set "SILENT_MODE=1"

call "%~dp0build.bat" /s || exit /b 1
py -3 -m pip install --user pyinstaller~=6.18 || (echo [installer] PyInstaller bootstrap failed.& exit /b 1)
if exist "%~dp0installer\dist" rmdir /s /q "%~dp0installer\dist"
py -3 -m PyInstaller -y --distpath "%~dp0installer\dist" "%~dp0installer\Amulet.spec" || (echo [installer] PyInstaller build failed.& exit /b 1)
for /f "delims=" %%V in ('py -3 "%~dp0scripts\normalize_squirrel_version.py" --raw 0.10.0-dev-local --fallback 0.10.0-dev-local') do set "BUILD_VERSION=%%V"
if not defined BUILD_VERSION (echo [installer] Could not resolve a Squirrel version.& exit /b 1)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\build-squirrel.ps1" -Version "%BUILD_VERSION%" -Architecture x64 || exit /b 1
set "RELEASE_DIR=%~dp0installer\dist\squirrel\Amulet-%BUILD_VERSION%-Windows-x64"
if not exist "%RELEASE_DIR%\Setup.exe" (echo [installer] Setup.exe was not produced.& exit /b 1)
if not exist "%RELEASE_DIR%\RELEASES" (echo [installer] RELEASES was not produced.& exit /b 1)
if not exist "%RELEASE_DIR%\Amulet-%BUILD_VERSION%-full.nupkg" (echo [installer] full Squirrel package was not produced.& exit /b 1)
if "%SILENT_MODE%"=="0" (
  echo [installer] SHA-256 digests:
  certutil -hashfile "%RELEASE_DIR%\Setup.exe" SHA256 | findstr /R /V /C:"CertUtil" /C:"SHA256"
  certutil -hashfile "%RELEASE_DIR%\RELEASES" SHA256 | findstr /R /V /C:"CertUtil" /C:"SHA256"
  certutil -hashfile "%RELEASE_DIR%\Amulet-%BUILD_VERSION%-full.nupkg" SHA256 | findstr /R /V /C:"CertUtil" /C:"SHA256"
)
if "%SILENT_MODE%"=="0" echo [installer] unsigned Squirrel artifacts are under installer\dist\squirrel
if "%SILENT_MODE%"=="0" pause
exit /b 0
