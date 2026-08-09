@echo off
setlocal EnableExtensions
set "SILENT_MODE=0"
if /I "%~1"=="/s" set "SILENT_MODE=1"
if /I "%~1"=="--silent" set "SILENT_MODE=1"
if "%SILENT%"=="1" set "SILENT_MODE=1"

if "%SILENT_MODE%"=="0" echo [build] bootstrapping the declared Python toolchain
where py >nul 2>nul || (echo [build] Python launcher py -3 is required and was not found.& exit /b 1)
py -3 -m pip install --user --upgrade pip build cython versioneer >nul || (echo [build] dependency bootstrap failed.& exit /b 1)
py -3 -m pip install --user --editable . || (echo [build] editable package build failed.& exit /b 1)
if "%SILENT_MODE%"=="0" echo [build] source package is ready; run py -3 -m amulet_map_editor to launch it.
if "%SILENT_MODE%"=="0" pause
exit /b 0
