@echo off
setlocal EnableExtensions
set "SILENT_MODE=0"
if /I "%~1"=="/s" set "SILENT_MODE=1"
if /I "%~1"=="--silent" set "SILENT_MODE=1"
if "%SILENT%"=="1" set "SILENT_MODE=1"

if "%SILENT_MODE%"=="0" echo [build] bootstrapping the declared Python toolchain
where py >nul 2>nul || powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap-python.ps1" || (echo [build] Python 3.11 bootstrap failed.& exit /b 1)
set "PYTHON_EXE="
set "PYTHON_ARGS=-3.11"
where py >nul 2>nul && set "PYTHON_EXE=py"
if not defined PYTHON_EXE if exist "%LocalAppData%\Programs\Python\Python311\python.exe" (set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python311\python.exe"& set "PYTHON_ARGS=")
if not defined PYTHON_EXE (echo [build] Python 3.11 was not found after bootstrap.& exit /b 1)
%PYTHON_EXE% %PYTHON_ARGS% -c "import sys" >nul 2>nul || (echo [build] Python executable could not start.& exit /b 1)
set "PYTHON_CMD=%PYTHON_EXE% %PYTHON_ARGS%"
%PYTHON_CMD% -m pip install --user --upgrade pip build cython versioneer "numpy~=1.26" >nul || (echo [build] dependency bootstrap failed.& exit /b 1)
%PYTHON_CMD% -m pip install --user --editable . --no-build-isolation || (echo [build] editable package build failed.& exit /b 1)
if "%SILENT_MODE%"=="0" echo [build] source package is ready; run py -3 -m amulet_map_editor to launch it.
if "%SILENT_MODE%"=="0" (
  choice /M "Launch Amulet now"
  if errorlevel 2 goto :build_done
  %PYTHON_CMD% -m amulet_map_editor
  if errorlevel 1 exit /b 1
)
:build_done
exit /b 0
