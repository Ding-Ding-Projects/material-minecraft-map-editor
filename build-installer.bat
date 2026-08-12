@echo off
setlocal EnableExtensions
set "SILENT_MODE=0"
if /I "%~1"=="/s" set "SILENT_MODE=1"
if /I "%~1"=="--silent" set "SILENT_MODE=1"
if "%SILENT%"=="1" set "SILENT_MODE=1"

call "%~dp0build.bat" /s || exit /b 1
set "PYTHON_EXE="
set "PYTHON_ARGS=-3.11"
py -3.11 -c "import sys" >nul 2>nul && set "PYTHON_EXE=py"
if not defined PYTHON_EXE if exist "%LocalAppData%\Programs\Python\Python311\python.exe" (set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python311\python.exe"& set "PYTHON_ARGS=")
if not defined PYTHON_EXE (echo [installer] Python 3.11 was not found after bootstrap.& exit /b 1)
set "PYTHON_CMD=%PYTHON_EXE% %PYTHON_ARGS%"
%PYTHON_CMD% -c "import sys; assert sys.version_info[:2] == (3, 11)" >nul 2>nul || (echo [installer] Python 3.11 executable could not start.& exit /b 1)
%PYTHON_CMD% -m pip install --user pyinstaller~=6.18 || (echo [installer] PyInstaller bootstrap failed.& exit /b 1)
if exist "%~dp0installer\dist" rmdir /s /q "%~dp0installer\dist"
%PYTHON_CMD% -m PyInstaller -y --distpath "%~dp0installer\dist" "%~dp0installer\Amulet.spec" || (echo [installer] PyInstaller build failed.& exit /b 1)
rem Derive the version from the project rather than hard-coding it.
rem
rem This was `set "BUILD_VERSION=0.10.0-dev-local"`, a fixed label, so every
rem installer this script produced claimed to be 0.10.0-dev-local no matter
rem what the checkout was. That is fine while the output is only ever a local
rem smoke test, and it is a real defect the moment a release is cut through
rem this script -- which is exactly what the project's own rule requires,
rem because a manual release that goes around the script never proves the
rem script works. Tagging 1.0.0 and rebuilding produced fresh digests under
rem the old name: an artifact disagreeing with the release that carries it.
rem
rem Versioneer derives the version from the tag, so this asks the package.
rem The suffix is stripped for NuGet, which rejects PEP 440 local versions
rem such as 1.0.0+3.gabcdef -- an untagged checkout therefore builds as its
rem last tag, and only a tagged one carries a clean number.
for /f "usebackq delims=" %%v in (`%PYTHON_CMD% -c "import amulet_map_editor,re;v=amulet_map_editor.__version__;print(re.split(r'[+]',v)[0] or '0.0.0')"`) do set "BUILD_VERSION=%%v"
if not defined BUILD_VERSION set "BUILD_VERSION=0.0.0-unknown"
echo [installer] building version %BUILD_VERSION%
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\build-squirrel.ps1" -Version "%BUILD_VERSION%" -Architecture x64 -InputDirectory "%~dp0installer\dist\amulet" -OutputDirectory "%~dp0installer\dist\squirrel" || exit /b 1
set "RELEASE_DIR=%~dp0installer\dist\squirrel\Amulet-%BUILD_VERSION%-Windows-x64"
if not exist "%RELEASE_DIR%\Setup.exe" (echo [installer] Setup.exe was not produced.& exit /b 1)
if not exist "%RELEASE_DIR%\RELEASES" (echo [installer] RELEASES was not produced.& exit /b 1)
if not exist "%RELEASE_DIR%\Amulet-%BUILD_VERSION%-full.nupkg" (echo [installer] full Squirrel package was not produced.& exit /b 1)
echo [installer] SHA-256 digests:
echo [installer] Setup.exe
certutil -hashfile "%RELEASE_DIR%\Setup.exe" SHA256 | findstr /R /V /C:"CertUtil" /C:"SHA256"
echo [installer] RELEASES
certutil -hashfile "%RELEASE_DIR%\RELEASES" SHA256 | findstr /R /V /C:"CertUtil" /C:"SHA256"
echo [installer] full nupkg
certutil -hashfile "%RELEASE_DIR%\Amulet-%BUILD_VERSION%-full.nupkg" SHA256 | findstr /R /V /C:"CertUtil" /C:"SHA256"
if "%SILENT_MODE%"=="0" echo [installer] unsigned Squirrel artifacts are under installer\dist\squirrel
exit /b 0
