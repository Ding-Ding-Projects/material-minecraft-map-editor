[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PathFile,

    [switch]$ExistingOnly
)

$ErrorActionPreference = 'Stop'

# Keep the portable fallback immutable and reviewable.  The URL is an official
# Git for Windows release asset; size and SHA-256 come from that asset's GitHub
# release metadata.
$portableVersion = '2.55.0.3'
$portableUrl = 'https://github.com/git-for-windows/git/releases/download/v2.55.0.windows.3/PortableGit-2.55.0.3-64-bit.7z.exe'
$portableSize = 58919776L
$portableSha256 = 'ab00566336b5472120f9a52d34f2e79c5406535792acb0548001ffd0bd090e5d'
$toolchainRoot = Join-Path $env:LOCALAPPDATA 'Amulet Map Editor\Toolchains\Git'
$portableRoot = Join-Path $toolchainRoot $portableVersion

function Invoke-HiddenProcess([string]$FilePath, [string]$Arguments) {
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $FilePath
    $info.Arguments = $Arguments
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $info
    try {
        [void]$process.Start()
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        return [pscustomobject]@{
            ExitCode = $process.ExitCode
            Stdout = $stdoutTask.Result
            Stderr = $stderrTask.Result
        }
    }
    finally {
        $process.Dispose()
    }
}

function Test-GitExecutable([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path) -or
        -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }
    try {
        $result = Invoke-HiddenProcess $Path '--version'
        return $result.ExitCode -eq 0 -and $result.Stdout -match '^git version \d'
    }
    catch {
        return $false
    }
}

function Find-InstalledGit {
    $candidates = [Collections.Generic.List[string]]::new()
    $command = Get-Command git.exe -ErrorAction SilentlyContinue
    if ($command -and $command.Source) {
        $candidates.Add($command.Source)
    }
    if ($env:LOCALAPPDATA) {
        $candidates.Add((Join-Path $env:LOCALAPPDATA 'Programs\Git\cmd\git.exe'))
    }
    if ($env:ProgramFiles) {
        $candidates.Add((Join-Path $env:ProgramFiles 'Git\cmd\git.exe'))
    }
    if (${env:ProgramFiles(x86)}) {
        $candidates.Add((Join-Path ${env:ProgramFiles(x86)} 'Git\cmd\git.exe'))
    }
    $candidates.Add((Join-Path $portableRoot 'cmd\git.exe'))

    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (Test-GitExecutable $candidate) {
            return [IO.Path]::GetFullPath($candidate)
        }
    }
    return $null
}

function Get-Sha256([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($stream)) -replace '-', '').ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
        $stream.Dispose()
    }
}

function Remove-OwnedDirectory([string]$Path, [string]$Root) {
    $fullPath = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $fullRoot = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    $requiredPrefix = $fullRoot + [IO.Path]::DirectorySeparatorChar
    if (-not $fullPath.StartsWith($requiredPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a path outside the Git toolchain root: $fullPath"
    }
    if (Test-Path -LiteralPath $fullPath) {
        Remove-Item -LiteralPath $fullPath -Recurse -Force
    }
}

function Write-GitPath([string]$GitPath) {
    $resolvedPathFile = [IO.Path]::GetFullPath($PathFile)
    $parent = Split-Path -Parent $resolvedPathFile
    if ($parent) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    [IO.File]::WriteAllText(
        $resolvedPathFile,
        $GitPath + [Environment]::NewLine,
        [Text.UTF8Encoding]::new($false)
    )
    Write-Host "[build] Git is ready at $GitPath"
}

$gitPath = Find-InstalledGit
if ($gitPath) {
    Write-GitPath $gitPath
    return
}
if ($ExistingOnly) {
    throw 'Git was not already installed; ExistingOnly forbids installation.'
}

$winget = Get-Command winget.exe -ErrorAction SilentlyContinue
if ($winget) {
    Write-Host '[build] installing Git for the current user via winget'
    $wingetResult = Invoke-HiddenProcess $winget.Source (
        'install --id Git.Git --exact --scope user --silent ' +
        '--accept-package-agreements --accept-source-agreements --disable-interactivity'
    )
    if ($wingetResult.ExitCode -ne 0) {
        Write-Warning "winget Git install exited $($wingetResult.ExitCode); trying the pinned portable fallback."
    }
    $gitPath = Find-InstalledGit
    if ($gitPath) {
        Write-GitPath $gitPath
        return
    }
}

Write-Host "[build] installing pinned PortableGit $portableVersion for the current user"
$tempArchive = Join-Path ([IO.Path]::GetTempPath()) (
    'amulet-portable-git-' + [Guid]::NewGuid().ToString('N') + '.7z.exe'
)
$stage = Join-Path $toolchainRoot ('.stage-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $toolchainRoot -Force | Out-Null
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $client = [Net.WebClient]::new()
    try {
        $client.Headers['User-Agent'] = 'Amulet-Map-Editor-Bootstrap/1'
        $client.DownloadFile($portableUrl, $tempArchive)
    }
    finally {
        $client.Dispose()
    }

    $download = Get-Item -LiteralPath $tempArchive -ErrorAction Stop
    if ($download.Length -ne $portableSize) {
        throw "PortableGit size mismatch: expected $portableSize bytes, got $($download.Length)."
    }
    $actualHash = Get-Sha256 $download.FullName
    if ($actualHash -ne $portableSha256) {
        throw "PortableGit SHA-256 mismatch: expected $portableSha256, got $actualHash."
    }

    New-Item -ItemType Directory -Path $stage -Force | Out-Null
    $extractResult = Invoke-HiddenProcess $download.FullName ('-y -o"' + $stage + '"')
    if ($extractResult.ExitCode -ne 0) {
        throw "PortableGit extraction failed with exit code $($extractResult.ExitCode): $($extractResult.Stderr.Trim())"
    }
    $stagedGit = Join-Path $stage 'cmd\git.exe'
    if (-not (Test-GitExecutable $stagedGit)) {
        throw 'The verified PortableGit archive did not produce a working cmd\git.exe.'
    }

    if (Test-Path -LiteralPath $portableRoot) {
        Remove-OwnedDirectory $portableRoot $toolchainRoot
    }
    Move-Item -LiteralPath $stage -Destination $portableRoot
    $gitPath = Join-Path $portableRoot 'cmd\git.exe'
    if (-not (Test-GitExecutable $gitPath)) {
        throw 'PortableGit stopped working after installation.'
    }
    Write-GitPath ([IO.Path]::GetFullPath($gitPath))
}
finally {
    if (Test-Path -LiteralPath $tempArchive) {
        Remove-Item -LiteralPath $tempArchive -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $stage) {
        Remove-OwnedDirectory $stage $toolchainRoot
    }
}
