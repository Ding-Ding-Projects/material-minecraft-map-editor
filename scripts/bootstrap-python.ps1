[CmdletBinding()]
param(
    [string]$PackageId = 'Python.Python.3.11'
)

$ErrorActionPreference = 'Stop'
$winget = Get-Command winget.exe -ErrorAction SilentlyContinue
if (-not $winget) {
    throw 'Python 3.11 is missing and winget.exe is unavailable; install the official Python.Python.3.11 package source or provide winget.'
}

Write-Host "[build] installing $PackageId for the current user via winget"
& $winget.Source install --id $PackageId --scope user --exact --accept-source-agreements --accept-package-agreements --silent
if ($LASTEXITCODE -ne 0) {
    throw "winget could not install $PackageId (exit code $LASTEXITCODE)"
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
