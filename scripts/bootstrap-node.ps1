[CmdletBinding()]
param(
    [string]$PackageId = 'OpenJS.NodeJS.LTS',
    [string]$InstallerUrl = 'https://nodejs.org/dist/v22.14.0/node-v22.14.0-x64.msi'
)

# Bootstraps a current-user Node.js install for the Electron packaging lane.
# Mirrors scripts/bootstrap-python.ps1: prefer winget (user scope, silent),
# fall back to the official installer when winget is unavailable, then
# refresh this process's PATH so the very next command in the calling batch
# script can find node/npm without a second shell.

$ErrorActionPreference = 'Stop'
$winget = Get-Command winget.exe -ErrorAction SilentlyContinue
if ($winget) {
    Write-Host "[build-electron] installing $PackageId for the current user via winget"
    & $winget.Source install --id $PackageId --scope user --exact --accept-source-agreements --accept-package-agreements --silent
    if ($LASTEXITCODE -ne 0) {
        throw "winget could not install $PackageId (exit code $LASTEXITCODE)"
    }
} else {
    # A clean Windows image may not have App Installer/winget yet. Use the
    # canonical nodejs.org MSI as a no-prompt, user-scoped fallback.
    $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("amulet-node-" + [Guid]::NewGuid().ToString('N'))
    $installer = Join-Path $tempRoot 'node-installer.msi'
    New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
    try {
        Write-Host "[build-electron] winget unavailable; downloading official Node.js LTS installer"
        Invoke-WebRequest -Uri $InstallerUrl -OutFile $installer -UseBasicParsing
        if (-not (Test-Path -LiteralPath $installer)) {
            throw "Node installer download did not create $installer"
        }
        $msiArgs = @('/i', "`"$installer`"", '/quiet', '/norestart', 'ALLUSERS=2', 'MSIINSTALLPERUSER=1')
        $proc = Start-Process -FilePath 'msiexec.exe' -ArgumentList $msiArgs -Wait -PassThru
        if ($proc.ExitCode -ne 0) {
            throw "official Node.js installer failed (exit code $($proc.ExitCode))"
        }
    } finally {
        if (Test-Path -LiteralPath $tempRoot) {
            Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

# The installer updates PATH for future processes. Expose the new user and
# machine paths to this process too, so the very next batch command can find
# node/npm without opening a fresh shell. This was the exact bootstrap-python
# mistake to avoid: a package manager writes PATH for FUTURE shells only.
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
$env:Path = "$userPath;$machinePath"
if (-not (Get-Command node.exe -ErrorAction SilentlyContinue)) {
    throw 'Node.js was installed but node.exe is not visible after PATH refresh.'
}
