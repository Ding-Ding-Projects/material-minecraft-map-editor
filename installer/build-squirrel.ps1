[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^v?\d+\.\d+\.\d+(?:\.\d+)?(?:-[0-9A-Za-z.-]+)?$')]
    [string] $Version,

    [Parameter(Mandatory = $true)]
    [ValidateSet('x64', 'arm64')]
    [string] $Architecture,

    [string] $InputDirectory = (Join-Path $PSScriptRoot 'dist\amulet'),
    [string] $OutputDirectory = (Join-Path $PSScriptRoot 'dist\squirrel'),
    # Keep the bootstrap executable immutable: the NuGet "latest" alias is a
    # moving target and would let a packaging run silently change toolchains.
    [ValidatePattern('^v\d+\.\d+\.\d+$')]
    [string] $NuGetVersion = 'v6.14.0',
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string] $NuGetSha256 = '92dbed160ddee0f64b901e907439e021211b428e57c089ecc12fc38dcc4bd9a5',
    [string] $SquirrelVersion = '2.0.1'
)

$ErrorActionPreference = 'Stop'
$Version = $Version.TrimStart('v')
$inputPath = (Resolve-Path $InputDirectory).Path
$out = [IO.Path]::GetFullPath($OutputDirectory)
$scratch = Join-Path ([IO.Path]::GetTempPath()) ('amulet-squirrel-' + [guid]::NewGuid().ToString('N'))
$nuget = Join-Path $scratch 'nuget.exe'
$squirrelRoot = Join-Path $scratch "squirrel.windows.$SquirrelVersion"
$packageRoot = Join-Path $scratch 'package'
$packageLib = Join-Path $packageRoot 'lib\net45'
$nupkg = Join-Path $scratch "Amulet.$Version.nupkg"

function Invoke-Native([string] $FilePath, [string[]] $ArgumentList) {
    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "Native command failed ($LASTEXITCODE): $FilePath $($ArgumentList -join ' ')"
    }
}

try {
    New-Item -ItemType Directory -Force $scratch, $packageLib, $out | Out-Null
    $nugetUri = "https://dist.nuget.org/win-x86-commandline/$NuGetVersion/nuget.exe"
    Invoke-Native 'curl.exe' @(
        '--fail', '--location', '--silent', '--show-error', '--retry', '4',
        '--retry-all-errors', '--output', $nuget, $nugetUri
    )
    $nugetHash = (Get-FileHash -LiteralPath $nuget -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($nugetHash -ne $NuGetSha256.ToLowerInvariant()) {
        throw "NuGet $NuGetVersion SHA-256 mismatch: expected $NuGetSha256, got $nugetHash"
    }

    Invoke-Native $nuget @(
        'install', 'squirrel.windows', '-Version', $SquirrelVersion,
        '-OutputDirectory', $scratch, '-NonInteractive', '-NoCache'
    )

    if (-not (Test-Path (Join-Path $squirrelRoot 'tools\Squirrel.exe'))) {
        throw "Squirrel.Windows $SquirrelVersion did not provide tools\Squirrel.exe"
    }
    # Releasify shells out to the bundled 7z/WriteZipToSetup helpers. Put the
    # pinned Squirrel tool directory first so the invocation is self-contained
    # on a clean runner (and never depends on a machine-wide 7-Zip install).
    $env:PATH = "$(Join-Path $squirrelRoot 'tools');$env:PATH"

    # Squirrel expects every application file in lib/net45, even when the app
    # itself is not a .NET application. Keep the PyInstaller tree intact.
    Copy-Item (Join-Path $inputPath '*') $packageLib -Recurse -Force

    # The updater uses these framework files during install/update. They are
    # redistributable Squirrel payload, not signing tools or application code.
    Copy-Item (Join-Path $squirrelRoot 'tools\Squirrel.exe') (Join-Path $packageLib 'squirrel.exe') -Force
    Get-ChildItem (Join-Path $squirrelRoot 'lib') -Recurse -File -Include '*.dll' |
        ForEach-Object { Copy-Item $_.FullName $packageLib -Force }

    $nuspec = @"
<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://schemas.microsoft.com/packaging/2010/07/nuspec.xsd">
  <metadata>
    <id>Amulet</id>
    <version>$Version</version>
    <title>Amulet Map Editor</title>
    <authors>Amulet Team</authors>
    <owners>Amulet Team</owners>
    <description>Amulet Map Editor for Windows ($Architecture).</description>
    <requireLicenseAcceptance>false</requireLicenseAcceptance>
    <developmentDependency>false</developmentDependency>
  </metadata>
  <files>
    <file src="lib\net45\**" target="lib\net45" />
  </files>
</package>
"@
    $nuspecPath = Join-Path $packageRoot 'Amulet.nuspec'
    Set-Content -Path $nuspecPath -Value $nuspec -Encoding UTF8
    Invoke-Native $nuget @('pack', $nuspecPath, '-OutputDirectory', $scratch, '-NoPackageAnalysis')

    $releaseDir = Join-Path $out "Amulet-$Version-Windows-$Architecture"
    New-Item -ItemType Directory -Force $releaseDir | Out-Null
    $squirrel = Join-Path $squirrelRoot 'tools\Squirrel.exe'
    $oldLocation = Get-Location
    try {
        # Squirrel 2.x resolves its bundled 7z helper relative to the current
        # process directory, so invoke it from the package's tools directory.
        Set-Location (Join-Path $squirrelRoot 'tools')
        $releasifyArgs = @(
            "--releasify=$nupkg", "--releaseDir=$releaseDir", '--no-msi'
        )
        # A first release has no prior full package from which a delta can be
        # calculated. Skipping that impossible delta keeps Setup.exe and
        # RELEASES deterministic; later runs retain delta generation.
        if (-not (Get-ChildItem $out -Recurse -File -Filter '*-full.nupkg' -ErrorAction SilentlyContinue)) {
            $releasifyArgs += '--no-delta'
        }
        Invoke-Native $squirrel $releasifyArgs
    }
    finally { Set-Location $oldLocation }

    # Squirrel 2.0.1 dispatches archive work asynchronously on some Windows
    # runners. Wait for the release contract rather than trusting process exit.
    $required = @('Setup.exe', 'RELEASES', "Amulet-$Version-full.nupkg")
    $deadline = [DateTime]::UtcNow.AddSeconds(60)
    while ([DateTime]::UtcNow -lt $deadline -and
        (@($required | Where-Object { -not (Test-Path (Join-Path $releaseDir $_)) }).Count -gt 0)) {
        Start-Sleep -Milliseconds 500
    }
    foreach ($name in $required) {
        $path = Join-Path $releaseDir $name
        if (-not (Test-Path $path)) { throw "Squirrel did not create required artifact: $name" }
    }

    $signatureTargets = Get-ChildItem -Path $releaseDir -File |
        Where-Object { $_.Extension -in @('.exe', '.dll') }
    if (-not ($signatureTargets | Where-Object Name -eq 'Setup.exe')) {
        throw 'Squirrel output has no Setup.exe to verify'
    }
    foreach ($file in $signatureTargets) {
        $signature = Get-AuthenticodeSignature $file.FullName
        if ($signature.Status -ne 'NotSigned') {
            throw "Unsigned policy violated: $($file.Name) reports $($signature.Status)"
        }
    }
    $releaseIndex = Get-Content (Join-Path $releaseDir 'RELEASES') -Raw
    if ($releaseIndex -notmatch [regex]::Escape("Amulet-$Version-full.nupkg")) {
        throw 'RELEASES does not reference the full package'
    }
    Write-Output "Squirrel.Windows $SquirrelVersion produced unsigned artifacts in $releaseDir"
}
finally {
    if (Test-Path $scratch) {
        try { Remove-Item $scratch -Recurse -Force -ErrorAction Stop }
        catch { Write-Warning "Squirrel left a locked temporary log at $scratch; the CI workspace can discard it." }
    }
}
