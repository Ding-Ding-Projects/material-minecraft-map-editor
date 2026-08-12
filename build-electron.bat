@echo off
setlocal EnableExtensions
set "SILENT_MODE=0"
if /I "%~1"=="/s" set "SILENT_MODE=1"
if /I "%~1"=="--silent" set "SILENT_MODE=1"
if "%SILENT%"=="1" set "SILENT_MODE=1"

rem build-electron.bat -- gets a fresh Windows checkout to a runnable
rem Electron build of Amulet Map Editor, with nothing pre-installed.
rem Mirrors build.bat's shape: bootstrap every dependency itself, refresh
rem PATH in-process after installing anything, report each phase honestly,
rem stay idempotent, and offer to launch only at the very end.

if "%SILENT_MODE%"=="0" echo [build-electron] bootstrapping Node.js
where node >nul 2>nul
if errorlevel 1 powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap-node.ps1"
if errorlevel 1 (echo [build-electron] Node.js bootstrap failed.& exit /b 1)

rem A package manager writes PATH for FUTURE shells only -- refresh this
rem process's PATH from the user+machine environment so the very next
rem command below can actually find node/npm.
for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('Path','User') + ';' + [Environment]::GetEnvironmentVariable('Path','Machine')"`) do set "PATH=%%p"

where node >nul 2>nul
if errorlevel 1 (echo [build-electron] node.exe is still not on PATH after bootstrap.& exit /b 1)
where npm >nul 2>nul
if errorlevel 1 (echo [build-electron] npm.cmd is still not on PATH after bootstrap.& exit /b 1)

if "%SILENT_MODE%"=="0" (
  for /f "delims=" %%v in ('node --version') do echo [build-electron] using Node %%v
)

if not exist "%~dp0package.json" (
  echo [build-electron] no package.json at the repository root yet -- the Electron
  echo [build-electron] shell has not landed. Node.js is bootstrapped and ready;
  echo [build-electron] re-run this script once electron/ and package.json exist.
  exit /b 1
)

if "%SILENT_MODE%"=="0" echo [build-electron] installing project dependencies
if exist "%~dp0package-lock.json" (
  call npm ci --no-audit --no-fund || (echo [build-electron] npm ci failed.& exit /b 1)
) else (
  call npm install --no-audit --no-fund || (echo [build-electron] npm install failed.& exit /b 1)
)

if "%SILENT_MODE%"=="0" echo [build-electron] Electron dependencies installed; electron\main.js hosts docs\site\.
if "%SILENT_MODE%"=="0" (
  choice /M "Launch Material Minecraft Map Editor (Electron) now"
  if errorlevel 2 goto :build_done
  call npm run electron:start
)
:build_done
exit /b 0
