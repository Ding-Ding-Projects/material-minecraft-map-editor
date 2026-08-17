@echo off
setlocal EnableExtensions
set "SILENT_MODE=0"
if /I "%~1"=="/s" set "SILENT_MODE=1"
if /I "%~1"=="--silent" set "SILENT_MODE=1"
if "%SILENT%"=="1" set "SILENT_MODE=1"
for %%I in ("%~dp0.") do set "REPO_DIR=%%~fI"

if "%SILENT_MODE%"=="0" echo [build] bootstrapping the declared Python toolchain
py -3.11 -c "import sys" >nul 2>nul
if errorlevel 1 powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap-python.ps1"
if errorlevel 1 (echo [build] Python 3.11 bootstrap failed.& exit /b 1)
set "PYTHON_EXE="
set "PYTHON_ARGS=-3.11"
where py >nul 2>nul && set "PYTHON_EXE=py"
if not defined PYTHON_EXE if exist "%LocalAppData%\Programs\Python\Python311\python.exe" (set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python311\python.exe"& set "PYTHON_ARGS=")
if not defined PYTHON_EXE (echo [build] Python 3.11 was not found after bootstrap.& exit /b 1)
"%PYTHON_EXE%" %PYTHON_ARGS% -c "import sys; assert sys.version_info[:2] == (3, 11)" >nul 2>nul || (echo [build] Python 3.11 executable could not start.& exit /b 1)
"%PYTHON_EXE%" %PYTHON_ARGS% -m pip install --user --upgrade pip build cython versioneer "numpy~=1.26" >nul || (echo [build] dependency bootstrap failed.& exit /b 1)
"%PYTHON_EXE%" %PYTHON_ARGS% -m pip install --user --editable "%REPO_DIR%" --no-build-isolation || (echo [build] editable package build failed.& exit /b 1)
if "%SILENT_MODE%"=="0" echo [build] source package is ready; run pyw -3.11 -m amulet_map_editor to launch it without a terminal window.
if "%SILENT_MODE%"=="0" (
  choice /M "Launch Amulet now"
  if errorlevel 2 goto :build_done
  rem Amulet is a windowed application: launch it through pythonw so no
  rem terminal window is left behind attached to the running editor.
  where pyw >nul 2>nul
  if not errorlevel 1 (
    start "" pyw %PYTHON_ARGS% -m amulet_map_editor
  ) else (
    start "" "%PYTHON_EXE%" %PYTHON_ARGS% -m amulet_map_editor
  )
)
:build_done
exit /b 0
