@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "SILENT_MODE=0"
if /I "%~1"=="/s" set "SILENT_MODE=1"
if /I "%~1"=="--silent" set "SILENT_MODE=1"
if "%SILENT%"=="1" set "SILENT_MODE=1"
for %%I in ("%~dp0.") do set "REPO_DIR=%%~fI"
set "BUILD_EXIT_CODE=1"
set "RUN_ROOT="

set "BUILD_STARTED_AT="
for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format o"') do set "BUILD_STARTED_AT=%%T"
if not defined BUILD_STARTED_AT (
  echo [installer] Could not record the build start time.
  goto :installer_cleanup
)

rem Git is needed for provenance, but a fresh Windows checkout may not expose
rem it to this process yet.  Bootstrap it before the first repository command
rem and consume its verified absolute executable path rather than trusting PATH.
set "GIT_PATH_FILE=%TEMP%\amulet-git-path-%RANDOM%-%RANDOM%.txt"
powershell -NoProfile -ExecutionPolicy Bypass -File "%REPO_DIR%\scripts\bootstrap-git.ps1" -PathFile "%GIT_PATH_FILE%"
if errorlevel 1 (
  echo [installer] Git bootstrap failed.
  goto :installer_cleanup
)
set "GIT_EXE="
set /p GIT_EXE=<"%GIT_PATH_FILE%"
del /q "%GIT_PATH_FILE%" >nul 2>nul
set "GIT_PATH_FILE="
if not defined GIT_EXE (
  echo [installer] Git bootstrap did not return an executable path.
  goto :installer_cleanup
)
if not exist "%GIT_EXE%" (
  echo [installer] Git bootstrap returned a missing executable: %GIT_EXE%
  goto :installer_cleanup
)
for %%I in ("%GIT_EXE%") do set "PATH=%%~dpI;%PATH%"

set "GIT_OUTPUT=%TEMP%\amulet-source-sha-%RANDOM%-%RANDOM%.txt"
"%GIT_EXE%" -C "%REPO_DIR%" rev-parse --verify HEAD >"%GIT_OUTPUT%" 2>&1
if errorlevel 1 (
  type "%GIT_OUTPUT%"
  del /q "%GIT_OUTPUT%" >nul 2>nul
  echo [installer] Could not resolve the intended Git commit.
  goto :installer_cleanup
)
set "SOURCE_SHA="
set /p SOURCE_SHA=<"%GIT_OUTPUT%"
del /q "%GIT_OUTPUT%" >nul 2>nul
if not defined SOURCE_SHA (
  echo [installer] Git returned an empty intended commit.
  goto :installer_cleanup
)

rem Git status deliberately ignores assume-unchanged and skip-worktree paths.
rem Reject those index bits explicitly so they cannot conceal mutable source.
set "INDEX_OUTPUT=%TEMP%\amulet-index-flags-%RANDOM%-%RANDOM%.txt"
set "HIDDEN_INDEX_OUTPUT=%TEMP%\amulet-hidden-index-%RANDOM%-%RANDOM%.txt"
"%GIT_EXE%" -C "%REPO_DIR%" ls-files -v >"%INDEX_OUTPUT%" 2>&1
if errorlevel 1 (
  type "%INDEX_OUTPUT%"
  del /q "%INDEX_OUTPUT%" "%HIDDEN_INDEX_OUTPUT%" >nul 2>nul
  echo [installer] Could not inspect Git index flags.
  goto :installer_cleanup
)
findstr /R /C:"^[abcdefghijklmnopqrstuvwxyz] " /C:"^S " "%INDEX_OUTPUT%" >"%HIDDEN_INDEX_OUTPUT%"
set "FINDSTR_EXIT=%ERRORLEVEL%"
if "%FINDSTR_EXIT%"=="0" (
  type "%HIDDEN_INDEX_OUTPUT%"
  del /q "%INDEX_OUTPUT%" "%HIDDEN_INDEX_OUTPUT%" >nul 2>nul
  echo [installer] assume-unchanged or skip-worktree entries are not allowed for packaging.
  goto :installer_cleanup
)
if not "%FINDSTR_EXIT%"=="1" (
  type "%HIDDEN_INDEX_OUTPUT%"
  del /q "%INDEX_OUTPUT%" "%HIDDEN_INDEX_OUTPUT%" >nul 2>nul
  echo [installer] Could not evaluate Git index flags.
  goto :installer_cleanup
)
del /q "%INDEX_OUTPUT%" "%HIDDEN_INDEX_OUTPUT%" >nul 2>nul

set "STATUS_OUTPUT=%TEMP%\amulet-source-status-%RANDOM%-%RANDOM%.txt"
"%GIT_EXE%" -C "%REPO_DIR%" status --porcelain --untracked-files=all >"%STATUS_OUTPUT%" 2>&1
if errorlevel 1 (
  type "%STATUS_OUTPUT%"
  del /q "%STATUS_OUTPUT%" >nul 2>nul
  echo [installer] Could not inspect the source working tree.
  goto :installer_cleanup
)
set "SOURCE_TREE_CHANGED="
for /f "usebackq delims=" %%S in ("%STATUS_OUTPUT%") do set "SOURCE_TREE_CHANGED=1"
if defined SOURCE_TREE_CHANGED (
  type "%STATUS_OUTPUT%"
  del /q "%STATUS_OUTPUT%" >nul 2>nul
  echo [installer] working tree must be clean before packaging.
  goto :installer_cleanup
)
del /q "%STATUS_OUTPUT%" >nul 2>nul

echo [installer] started: %BUILD_STARTED_AT%
echo [installer] intended Git commit: %SOURCE_SHA%

rem Build from a Git archive of the exact source commit.  This staging tree has
rem no mutable working-tree overlay, so every packaged byte starts from HEAD.
set "RUN_ROOT=%TEMP%\amulet-installer-%SOURCE_SHA:~0,12%-%RANDOM%-%RANDOM%"
set "SOURCE_ARCHIVE=%RUN_ROOT%\source.zip"
set "STAGE_DIR=%RUN_ROOT%\source"
powershell -NoProfile -Command "$ErrorActionPreference = 'Stop'; New-Item -ItemType Directory -Path $env:RUN_ROOT -Force | Out-Null"
if errorlevel 1 (
  echo [installer] Could not create the exact-commit staging directory.
  goto :installer_cleanup
)
"%GIT_EXE%" -C "%REPO_DIR%" archive --format=zip --output="%SOURCE_ARCHIVE%" "%SOURCE_SHA%"
if errorlevel 1 (
  echo [installer] Could not archive the intended Git commit.
  goto :installer_cleanup
)
if not exist "%SOURCE_ARCHIVE%" (
  echo [installer] Git did not create the intended source archive.
  goto :installer_cleanup
)
for %%Z in ("%SOURCE_ARCHIVE%") do if %%~zZ LEQ 0 (
  echo [installer] Git created an empty source archive.
  goto :installer_cleanup
)
powershell -NoProfile -Command "$ErrorActionPreference = 'Stop'; New-Item -ItemType Directory -Path $env:STAGE_DIR -Force | Out-Null; Expand-Archive -LiteralPath $env:SOURCE_ARCHIVE -DestinationPath $env:STAGE_DIR -Force"
if errorlevel 1 (
  echo [installer] Could not expand the exact source archive.
  goto :installer_cleanup
)
if not exist "%STAGE_DIR%\build.bat" (
  echo [installer] Exact source archive is missing build.bat.
  goto :installer_cleanup
)
if not exist "%STAGE_DIR%\installer\build-squirrel.ps1" (
  echo [installer] Exact source archive is missing the Squirrel build script.
  goto :installer_cleanup
)
if exist "%STAGE_DIR%\.git" (
  echo [installer] Exact source staging unexpectedly contains mutable Git metadata.
  goto :installer_cleanup
)
echo [installer] staging exact commit: %SOURCE_SHA%

pushd "%STAGE_DIR%"
if errorlevel 1 (
  echo [installer] Could not enter the exact source staging directory.
  goto :installer_cleanup
)
call "%STAGE_DIR%\build.bat" /s
set "STEP_EXIT_CODE=%ERRORLEVEL%"
popd
if not "%STEP_EXIT_CODE%"=="0" (
  echo [installer] Source build failed with exit code %STEP_EXIT_CODE%.
  goto :installer_cleanup
)

set "PYTHON_EXE="
set "PYTHON_ARGS=-3.11"
py -3.11 -c "import sys" >nul 2>nul && set "PYTHON_EXE=py"
if not defined PYTHON_EXE if exist "%LocalAppData%\Programs\Python\Python311\python.exe" (set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python311\python.exe"& set "PYTHON_ARGS=")
if not defined PYTHON_EXE (
  echo [installer] Python 3.11 was not found after bootstrap.
  goto :installer_cleanup
)
"%PYTHON_EXE%" %PYTHON_ARGS% -c "import sys; assert sys.version_info[:2] == (3, 11)" >nul 2>nul
if errorlevel 1 (
  echo [installer] Python 3.11 executable could not start.
  goto :installer_cleanup
)
"%PYTHON_EXE%" %PYTHON_ARGS% -m pip install --user pyinstaller~=6.18
if errorlevel 1 (
  echo [installer] PyInstaller bootstrap failed.
  goto :installer_cleanup
)

pushd "%STAGE_DIR%"
if errorlevel 1 (
  echo [installer] Could not re-enter the exact source staging directory.
  goto :installer_cleanup
)
"%PYTHON_EXE%" %PYTHON_ARGS% -m PyInstaller -y --distpath "%STAGE_DIR%\installer\dist" "%STAGE_DIR%\installer\Amulet.spec"
set "STEP_EXIT_CODE=%ERRORLEVEL%"
popd
if not "%STEP_EXIT_CODE%"=="0" (
  echo [installer] PyInstaller build failed with exit code %STEP_EXIT_CODE%.
  goto :installer_cleanup
)

rem This label is local-only and is never a release tag. Public builds resolve
rem and validate their canonical source/package identity in build-windows.yml.
set "BUILD_VERSION=0.10.0-dev-local"
powershell -NoProfile -ExecutionPolicy Bypass -File "%STAGE_DIR%\installer\build-squirrel.ps1" -Version "%BUILD_VERSION%" -Architecture x64 -InputDirectory "%STAGE_DIR%\installer\dist\amulet" -OutputDirectory "%STAGE_DIR%\installer\dist\squirrel"
if errorlevel 1 (
  echo [installer] Squirrel.Windows packaging failed.
  goto :installer_cleanup
)
set "STAGED_SQUIRREL_ROOT=%STAGE_DIR%\installer\dist\squirrel"
set "STAGED_RELEASE_DIR=%STAGED_SQUIRREL_ROOT%\Amulet-%BUILD_VERSION%-Windows-x64"
if not exist "%STAGED_RELEASE_DIR%\Setup.exe" (
  echo [installer] Setup.exe was not produced.
  goto :installer_cleanup
)
if not exist "%STAGED_RELEASE_DIR%\RELEASES" (
  echo [installer] RELEASES was not produced.
  goto :installer_cleanup
)
if not exist "%STAGED_RELEASE_DIR%\Amulet-%BUILD_VERSION%-full.nupkg" (
  echo [installer] full Squirrel package was not produced.
  goto :installer_cleanup
)

rem Replace only the repository's known generated output root, after resolving
rem and proving that destination is exactly where the build contract expects.
set "FINAL_SQUIRREL_ROOT=%REPO_DIR%\installer\dist\squirrel"
powershell -NoProfile -Command "$ErrorActionPreference = 'Stop'; $repo = [IO.Path]::GetFullPath($env:REPO_DIR); $expected = [IO.Path]::GetFullPath((Join-Path $repo 'installer\dist\squirrel')); $destination = [IO.Path]::GetFullPath($env:FINAL_SQUIRREL_ROOT); if (-not $destination.Equals($expected, [StringComparison]::OrdinalIgnoreCase)) { throw 'Refusing unexpected generated-output destination.' }; if (Test-Path -LiteralPath $destination) { Remove-Item -LiteralPath $destination -Recurse -Force }; Copy-Item -LiteralPath $env:STAGED_SQUIRREL_ROOT -Destination $destination -Recurse -Force"
if errorlevel 1 (
  echo [installer] Could not publish the locally generated artifacts into the repository output directory.
  goto :installer_cleanup
)
set "FINAL_RELEASE_DIR=%FINAL_SQUIRREL_ROOT%\Amulet-%BUILD_VERSION%-Windows-x64"
if not exist "%FINAL_RELEASE_DIR%\Setup.exe" (
  echo [installer] Copied Setup.exe is missing.
  goto :installer_cleanup
)
if not exist "%FINAL_RELEASE_DIR%\RELEASES" (
  echo [installer] Copied RELEASES is missing.
  goto :installer_cleanup
)
if not exist "%FINAL_RELEASE_DIR%\Amulet-%BUILD_VERSION%-full.nupkg" (
  echo [installer] Copied full Squirrel package is missing.
  goto :installer_cleanup
)

echo [installer] SHA-256 digests:
echo [installer] artifact path: %FINAL_RELEASE_DIR%\Setup.exe
set "HASH_OUTPUT=%TEMP%\amulet-setup-sha256-%RANDOM%-%RANDOM%.txt"
certutil -hashfile "%FINAL_RELEASE_DIR%\Setup.exe" SHA256 >"%HASH_OUTPUT%" 2>&1
if errorlevel 1 (
  type "%HASH_OUTPUT%"
  del /q "%HASH_OUTPUT%" >nul 2>nul
  echo [installer] Setup.exe SHA-256 command failed.
  goto :installer_cleanup
)
powershell -NoProfile -Command "$hash = @(Get-Content -LiteralPath $env:HASH_OUTPUT | ForEach-Object { $_.Trim() } | Where-Object { $_ -match '^[0-9A-Fa-f]{64}$' }); if ($hash.Count -ne 1) { throw 'Expected exactly one SHA-256 digest.' }; Write-Output ('[installer] SHA-256: ' + $hash[0].ToLowerInvariant())"
if errorlevel 1 (
  del /q "%HASH_OUTPUT%" >nul 2>nul
  echo [installer] Setup.exe SHA-256 output was invalid.
  goto :installer_cleanup
)
del /q "%HASH_OUTPUT%" >nul 2>nul

echo [installer] artifact path: %FINAL_RELEASE_DIR%\RELEASES
set "HASH_OUTPUT=%TEMP%\amulet-releases-sha256-%RANDOM%-%RANDOM%.txt"
certutil -hashfile "%FINAL_RELEASE_DIR%\RELEASES" SHA256 >"%HASH_OUTPUT%" 2>&1
if errorlevel 1 (
  type "%HASH_OUTPUT%"
  del /q "%HASH_OUTPUT%" >nul 2>nul
  echo [installer] RELEASES SHA-256 command failed.
  goto :installer_cleanup
)
powershell -NoProfile -Command "$hash = @(Get-Content -LiteralPath $env:HASH_OUTPUT | ForEach-Object { $_.Trim() } | Where-Object { $_ -match '^[0-9A-Fa-f]{64}$' }); if ($hash.Count -ne 1) { throw 'Expected exactly one SHA-256 digest.' }; Write-Output ('[installer] SHA-256: ' + $hash[0].ToLowerInvariant())"
if errorlevel 1 (
  del /q "%HASH_OUTPUT%" >nul 2>nul
  echo [installer] RELEASES SHA-256 output was invalid.
  goto :installer_cleanup
)
del /q "%HASH_OUTPUT%" >nul 2>nul

echo [installer] artifact path: %FINAL_RELEASE_DIR%\Amulet-%BUILD_VERSION%-full.nupkg
set "HASH_OUTPUT=%TEMP%\amulet-package-sha256-%RANDOM%-%RANDOM%.txt"
certutil -hashfile "%FINAL_RELEASE_DIR%\Amulet-%BUILD_VERSION%-full.nupkg" SHA256 >"%HASH_OUTPUT%" 2>&1
if errorlevel 1 (
  type "%HASH_OUTPUT%"
  del /q "%HASH_OUTPUT%" >nul 2>nul
  echo [installer] full nupkg SHA-256 command failed.
  goto :installer_cleanup
)
powershell -NoProfile -Command "$hash = @(Get-Content -LiteralPath $env:HASH_OUTPUT | ForEach-Object { $_.Trim() } | Where-Object { $_ -match '^[0-9A-Fa-f]{64}$' }); if ($hash.Count -ne 1) { throw 'Expected exactly one SHA-256 digest.' }; Write-Output ('[installer] SHA-256: ' + $hash[0].ToLowerInvariant())"
if errorlevel 1 (
  del /q "%HASH_OUTPUT%" >nul 2>nul
  echo [installer] full nupkg SHA-256 output was invalid.
  goto :installer_cleanup
)
del /q "%HASH_OUTPUT%" >nul 2>nul

set "GIT_OUTPUT=%TEMP%\amulet-finished-sha-%RANDOM%-%RANDOM%.txt"
"%GIT_EXE%" -C "%REPO_DIR%" rev-parse --verify HEAD >"%GIT_OUTPUT%" 2>&1
if errorlevel 1 (
  type "%GIT_OUTPUT%"
  del /q "%GIT_OUTPUT%" >nul 2>nul
  echo [installer] Could not re-check the intended Git commit.
  goto :installer_cleanup
)
set "FINISHED_SOURCE_SHA="
set /p FINISHED_SOURCE_SHA=<"%GIT_OUTPUT%"
del /q "%GIT_OUTPUT%" >nul 2>nul
if not defined FINISHED_SOURCE_SHA (
  echo [installer] Git returned an empty finished commit.
  goto :installer_cleanup
)
if /I not "%FINISHED_SOURCE_SHA%"=="%SOURCE_SHA%" (
  echo [installer] Git commit changed during packaging: %SOURCE_SHA% to %FINISHED_SOURCE_SHA%.
  goto :installer_cleanup
)

set "INDEX_OUTPUT=%TEMP%\amulet-finished-index-%RANDOM%-%RANDOM%.txt"
set "HIDDEN_INDEX_OUTPUT=%TEMP%\amulet-finished-hidden-index-%RANDOM%-%RANDOM%.txt"
"%GIT_EXE%" -C "%REPO_DIR%" ls-files -v >"%INDEX_OUTPUT%" 2>&1
if errorlevel 1 (
  type "%INDEX_OUTPUT%"
  del /q "%INDEX_OUTPUT%" "%HIDDEN_INDEX_OUTPUT%" >nul 2>nul
  echo [installer] Could not re-check Git index flags.
  goto :installer_cleanup
)
findstr /R /C:"^[abcdefghijklmnopqrstuvwxyz] " /C:"^S " "%INDEX_OUTPUT%" >"%HIDDEN_INDEX_OUTPUT%"
set "FINDSTR_EXIT=%ERRORLEVEL%"
if "%FINDSTR_EXIT%"=="0" (
  type "%HIDDEN_INDEX_OUTPUT%"
  del /q "%INDEX_OUTPUT%" "%HIDDEN_INDEX_OUTPUT%" >nul 2>nul
  echo [installer] assume-unchanged or skip-worktree entries appeared during packaging.
  goto :installer_cleanup
)
if not "%FINDSTR_EXIT%"=="1" (
  type "%HIDDEN_INDEX_OUTPUT%"
  del /q "%INDEX_OUTPUT%" "%HIDDEN_INDEX_OUTPUT%" >nul 2>nul
  echo [installer] Could not evaluate finished Git index flags.
  goto :installer_cleanup
)
del /q "%INDEX_OUTPUT%" "%HIDDEN_INDEX_OUTPUT%" >nul 2>nul

set "STATUS_OUTPUT=%TEMP%\amulet-finished-status-%RANDOM%-%RANDOM%.txt"
"%GIT_EXE%" -C "%REPO_DIR%" status --porcelain --untracked-files=all >"%STATUS_OUTPUT%" 2>&1
if errorlevel 1 (
  type "%STATUS_OUTPUT%"
  del /q "%STATUS_OUTPUT%" >nul 2>nul
  echo [installer] Could not re-check the source working tree.
  goto :installer_cleanup
)
set "SOURCE_TREE_CHANGED="
for /f "usebackq delims=" %%S in ("%STATUS_OUTPUT%") do set "SOURCE_TREE_CHANGED=1"
if defined SOURCE_TREE_CHANGED (
  type "%STATUS_OUTPUT%"
  del /q "%STATUS_OUTPUT%" >nul 2>nul
  echo [installer] working tree changed during packaging.
  goto :installer_cleanup
)
del /q "%STATUS_OUTPUT%" >nul 2>nul
set "BUILD_EXIT_CODE=0"

:installer_cleanup
if defined GIT_PATH_FILE del /q "%GIT_PATH_FILE%" >nul 2>nul
if defined RUN_ROOT powershell -NoProfile -Command "$ErrorActionPreference = 'Stop'; $candidate = [IO.Path]::GetFullPath($env:RUN_ROOT).TrimEnd('\'); $temp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + [IO.Path]::DirectorySeparatorChar; if (-not $candidate.StartsWith($temp, [StringComparison]::OrdinalIgnoreCase)) { throw 'Refusing to remove staging outside the temporary directory.' }; if (Test-Path -LiteralPath $candidate) { Remove-Item -LiteralPath $candidate -Recurse -Force }"
if errorlevel 1 (
  echo [installer] Could not safely remove the exact-commit staging directory.
  set "BUILD_EXIT_CODE=1"
)
if not "%BUILD_EXIT_CODE%"=="0" exit /b %BUILD_EXIT_CODE%

set "BUILD_COMPLETED_AT="
for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format o"') do set "BUILD_COMPLETED_AT=%%T"
if not defined BUILD_COMPLETED_AT (
  echo [installer] Could not record the build completion time.
  exit /b 1
)
echo [installer] unsigned Squirrel artifacts: %FINAL_RELEASE_DIR%
echo [installer] completed: %BUILD_COMPLETED_AT%
powershell -NoProfile -Command "$ErrorActionPreference = 'Stop'; $started = [DateTimeOffset]::Parse($env:BUILD_STARTED_AT); $completed = [DateTimeOffset]::Parse($env:BUILD_COMPLETED_AT); if ($completed -lt $started) { throw 'Completion preceded start.' }; Write-Output ('[installer] duration: ' + ($completed - $started).ToString('c'))"
if errorlevel 1 (
  echo [installer] Could not calculate the build duration.
  exit /b 1
)
exit /b %BUILD_EXIT_CODE%
