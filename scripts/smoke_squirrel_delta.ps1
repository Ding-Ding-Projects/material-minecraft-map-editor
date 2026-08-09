[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path $PSScriptRoot -Parent
$smokeRoot = Join-Path ([IO.Path]::GetTempPath()) (
    'amulet-squirrel-delta-smoke-' + [guid]::NewGuid().ToString('N')
)
$resolvedTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$resolvedSmoke = [IO.Path]::GetFullPath($smokeRoot)
if (-not $resolvedSmoke.StartsWith($resolvedTemp, [StringComparison]::OrdinalIgnoreCase) -or
    [IO.Path]::GetFileName($resolvedSmoke) -notlike 'amulet-squirrel-delta-smoke-*') {
    throw "Refusing unsafe Squirrel smoke path: $resolvedSmoke"
}

function Get-Sha256([string] $Path) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $stream = [IO.File]::OpenRead($Path)
        try {
            return ([BitConverter]::ToString($sha.ComputeHash($stream)) -replace '-', '').ToLowerInvariant()
        }
        finally { $stream.Dispose() }
    }
    finally { $sha.Dispose() }
}

try {
    $inputOne = Join-Path $resolvedSmoke 'input-one'
    $inputTwo = Join-Path $resolvedSmoke 'input-two'
    $output = Join-Path $resolvedSmoke 'output'
    New-Item -ItemType Directory -Force $inputOne, $inputTwo, $output | Out-Null
    # Reuse the current PowerShell host only as a valid PE fixture. It is never
    # published, and the version marker supplies the content change whose delta
    # is under test.
    $fixtureExecutable = [Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
    Copy-Item -LiteralPath $fixtureExecutable -Destination (Join-Path $inputOne 'Amulet.exe')
    Copy-Item -LiteralPath $fixtureExecutable -Destination (Join-Path $inputTwo 'Amulet.exe')
    [IO.File]::WriteAllText(
        (Join-Path $inputOne 'version.txt'),
        "fixture version one`n",
        [Text.UTF8Encoding]::new($false)
    )
    [IO.File]::WriteAllText(
        (Join-Path $inputTwo 'version.txt'),
        "fixture version one`nfixture version two`n",
        [Text.UTF8Encoding]::new($false)
    )

    $builder = Join-Path $repositoryRoot 'installer\build-squirrel.ps1'
    & $builder `
        -Version '0.10.100426' `
        -Architecture x64 `
        -InputDirectory $inputOne `
        -OutputDirectory $output

    $first = Join-Path $output 'Amulet-0.10.100426-Windows-x64'
    $previousPackage = Join-Path $first 'Amulet-0.10.100426-full.nupkg'
    $previousIndex = Join-Path $first 'RELEASES'
    $packageDigest = 'sha256:' + (Get-Sha256 $previousPackage)
    $indexDigest = 'sha256:' + (Get-Sha256 $previousIndex)

    & $builder `
        -Version '0.10.100427' `
        -Architecture x64 `
        -InputDirectory $inputTwo `
        -OutputDirectory $output `
        -PreviousPackagePath $previousPackage `
        -PreviousReleasesPath $previousIndex `
        -PreviousPackageSha256 $packageDigest `
        -PreviousReleasesSha256 $indexDigest `
        -PreviousSourceTag '0.10.0-dev.426' `
        -PreviousChannel automated

    $second = Join-Path $output 'Amulet-0.10.100427-Windows-x64'
    $delta = Get-Item -LiteralPath (
        Join-Path $second 'Amulet-0.10.100427-delta.nupkg'
    ) -ErrorAction Stop
    $feedLines = @(
        Get-Content -LiteralPath (Join-Path $second 'RELEASES') |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    if ($feedLines.Count -ne 1 -or
        $feedLines[0] -notmatch 'Amulet-0\.10\.100427-full\.nupkg' -or
        $feedLines[0] -match 'delta') {
        throw "Expected one full-only RELEASES row, got: $($feedLines -join ' | ')"
    }
    [pscustomobject]@{
        delta_bytes = $delta.Length
        delta_sha256 = Get-Sha256 $delta.FullName
        releases_rows = $feedLines.Count
        releases_entry = $feedLines[0]
    } | ConvertTo-Json -Compress
}
finally {
    if (Test-Path -LiteralPath $resolvedSmoke) {
        Remove-Item -LiteralPath $resolvedSmoke -Recurse -Force
    }
}
