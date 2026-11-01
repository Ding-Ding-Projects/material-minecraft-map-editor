param()
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repositoryRoot = Split-Path $PSScriptRoot -Parent
$environmentRoot = Join-Path $repositoryRoot 'native/.venv'
$pythonPath = Join-Path $environmentRoot 'Scripts/python.exe'

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw ('Native build command returned exit code ' + $LASTEXITCODE)
    }
}

try {
    Push-Location $repositoryRoot
    try {
        if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
            Invoke-Checked 'powershell' @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'bootstrap-python.ps1'))
        }
        Invoke-Checked 'py' @('-3.11', '-c', 'import sys; assert sys.version_info[:2] == (3, 11)')
        if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
            throw 'Rust Cargo is unavailable. Native toolchain acquisition is not implemented in this experimental route.'
        }
        if (-not (Test-Path -LiteralPath $pythonPath)) {
            Invoke-Checked 'py' @('-3.11', '-m', 'venv', $environmentRoot)
        }
        Invoke-Checked $pythonPath @('-m', 'pip', 'install', '--disable-pip-version-check', '--only-binary=:all:', '-r', (Join-Path $repositoryRoot 'native/requirements.txt'))
        Invoke-Checked 'cargo' @('build', '--locked', '--manifest-path', (Join-Path $repositoryRoot 'engine/Cargo.toml'))
        Invoke-Checked $pythonPath @('-c', 'import PySide6; print(PySide6.__version__)')
        Write-Output 'Native development build completed. No application was launched and no installer was produced.'
        Write-Output 'Launch route: native\.venv\Scripts\pythonw.exe -m native.amulet_native'
    } finally {
        Pop-Location
    }
    exit 0
} catch {
    Write-Error ('Native build incomplete: ' + $_.Exception.Message)
    exit 1
}
