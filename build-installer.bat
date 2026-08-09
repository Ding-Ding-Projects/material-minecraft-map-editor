@echo off
setlocal EnableExtensions
set "SILENT_MODE=0"
if /I "%~1"=="/s" set "SILENT_MODE=1"
if /I "%~1"=="--silent" set "SILENT_MODE=1"
if "%SILENT%"=="1" set "SILENT_MODE=1"

call "%~dp0build.bat" /s || exit /b 1
set "PYTHON_EXE="
set "PYTHON_ARGS=-3.11"
where py >nul 2>nul && set "PYTHON_EXE=py"
if not defined PYTHON_EXE if exist "%LocalAppData%\Programs\Python\Python311\python.exe" (set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python311\python.exe"& set "PYTHON_ARGS=")
if not defined PYTHON_EXE (echo [installer] Python 3.11 was not found after bootstrap.& exit /b 1)
set "PYTHON_CMD=%PYTHON_EXE% %PYTHON_ARGS%"
%PYTHON_CMD% -m pip install --user pyinstaller~=6.18 || (echo [installer] PyInstaller bootstrap failed.& exit /b 1)
if exist "%~dp0installer\dist" rmdir /s /q "%~dp0installer\dist"
%PYTHON_CMD% -m PyInstaller -y --distpath "%~dp0installer\dist" "%~dp0installer\Amulet.spec" || (echo [installer] PyInstaller build failed.& exit /b 1)
for /f "delims=" %%V in ('%PYTHON_CMD% "%~dp0scripts\normalize_squirrel_version.py" --raw 0.10.0-dev-local --fallback 0.10.0-dev-local') do set "BUILD_VERSION=%%V"
if not defined BUILD_VERSION (echo [installer] Could not resolve a Squirrel version.& exit /b 1)
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
