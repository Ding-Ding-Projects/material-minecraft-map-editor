[CmdletBinding()]
param(
    [string]$PackageId = 'Python.Python.3.11',
    [string]$InstallerUrl = 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe'
)

$ErrorActionPreference = 'Stop'
$winget = Get-Command winget.exe -ErrorAction SilentlyContinue
if ($winget) {
    Write-Host "[build] installing $PackageId for the current user via winget"
    & $winget.Source install --id $PackageId --scope user --exact --accept-source-agreements --accept-package-agreements --silent
    if ($LASTEXITCODE -ne 0) {
        throw "winget could not install $PackageId (exit code $LASTEXITCODE)"
    }
} else {
    # A clean Windows image may not have App Installer/winget yet. Use the
    # canonical python.org installer as a no-prompt, user-scoped fallback.
    $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("amulet-python-" + [Guid]::NewGuid().ToString('N'))
    $installer = Join-Path $tempRoot 'python-3.11.9-amd64.exe'
    New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
    try {
        Write-Host "[build] winget unavailable; downloading official Python 3.11 installer"
        Invoke-WebRequest -Uri $InstallerUrl -OutFile $installer -UseBasicParsing
        if (-not (Test-Path -LiteralPath $installer)) {
            throw "Python installer download did not create $installer"
        }
        & $installer /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0 SimpleInstall=1
        if ($LASTEXITCODE -ne 0) {
            throw "official Python installer failed (exit code $LASTEXITCODE)"
        }
    } finally {
        if (Test-Path -LiteralPath $tempRoot) {
            Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

# The installer updates PATH for future processes.  Expose the new user paths
# to this process too, so the very next batch command can find py/python.
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
$env:Path = "$userPath;$machinePath"
if (-not (Get-Command py.exe -ErrorAction SilentlyContinue) -and
    -not (Get-Command python.exe -ErrorAction SilentlyContinue)) {
    throw 'Python.Python.3.11 installed but no py.exe or python.exe is visible after PATH refresh.'
}
