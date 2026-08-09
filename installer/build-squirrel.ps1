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
    [string] $PreviousPackagePath = '',
    [string] $PreviousReleasesPath = '',
    [string] $PreviousPackageSha256 = '',
    [string] $PreviousReleasesSha256 = '',
    [string] $PreviousSourceTag = '',
    [string] $PreviousChannel = '',
    # Keep the bootstrap executable immutable: the NuGet "latest" alias is a
    # moving target and would let a packaging run silently change toolchains.
    [ValidatePattern('^v\d+\.\d+\.\d+$')]
    [string] $NuGetVersion = 'v6.14.0',
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string] $NuGetSha256 = '92dbed160ddee0f64b901e907439e021211b428e57c089ecc12fc38dcc4bd9a5',
    [string] $SquirrelVersion = '2.0.1',
    [ValidateRange(30, 600)]
    [int] $SquirrelTimeoutSeconds = 180
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

function Get-Sha256([string] $Path) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [IO.File]::ReadAllBytes($Path)
        return ([BitConverter]::ToString($sha.ComputeHash($bytes)) -replace '-', '').ToLowerInvariant()
    }
    finally { $sha.Dispose() }
}

function Get-Sha1([string] $Path) {
    $sha = [Security.Cryptography.SHA1]::Create()
    try {
        $stream = [IO.File]::OpenRead($Path)
        try {
            return ([BitConverter]::ToString($sha.ComputeHash($stream)) -replace '-', '').ToLowerInvariant()
        }
        finally { $stream.Dispose() }
    }
    finally { $sha.Dispose() }
}

function Get-SignatureStatus([string] $Path) {
    # Windows PowerShell 5.1 can fail to autoload Microsoft.PowerShell.Security
    # on stripped-down runners.  The signed-file API is available in the base
    # .NET Framework and lets the unsigned policy remain fail-closed without
    # depending on that optional module.
    try {
        [void][Security.Cryptography.X509Certificates.X509Certificate]::CreateFromSignedFile($Path)
        return 'Signed'
    }
    catch {
        return 'NotSigned'
    }
}

function Invoke-Native([string] $FilePath, [string[]] $ArgumentList) {
    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "Native command failed ($LASTEXITCODE): $FilePath $($ArgumentList -join ' ')"
    }
}

function Invoke-SquirrelWithTimeout([string] $FilePath, [string[]] $ArgumentList, [int] $TimeoutSeconds) {
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $FilePath
    $info.UseShellExecute = $false
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.CreateNoWindow = $true
    if ($null -ne $info.ArgumentList) {
        foreach ($argument in $ArgumentList) { [void]$info.ArgumentList.Add($argument) }
    } else {
        # Windows PowerShell 5.1/.NET Framework has no ArgumentList property.
        # Quote the bounded arguments explicitly for the legacy Arguments API.
        $info.Arguments = ($ArgumentList | ForEach-Object {
            '"' + ([string]$_).Replace('"', '\"') + '"'
        }) -join ' '
    }
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $info
    [void]$process.Start()
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        try { $process.Kill($true) } catch { }
        throw "Squirrel releasify exceeded the $TimeoutSeconds second timeout and was terminated."
    }
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    if ($stdout) { Write-Host $stdout.TrimEnd() }
    if ($stderr) { Write-Warning $stderr.TrimEnd() }
    if ($process.ExitCode -ne 0) {
        throw "Squirrel releasify failed ($($process.ExitCode)): $FilePath $($ArgumentList -join ' ')"
    }
}

try {
    New-Item -ItemType Directory -Force $scratch, $packageLib, $out | Out-Null
    $hasPreviousPackage = -not [string]::IsNullOrWhiteSpace($PreviousPackagePath)
    $hasPreviousReleases = -not [string]::IsNullOrWhiteSpace($PreviousReleasesPath)
    if ($hasPreviousPackage -ne $hasPreviousReleases) {
        throw 'PreviousPackagePath and PreviousReleasesPath must be supplied together.'
    }
    if ($hasPreviousPackage -and
        ([string]::IsNullOrWhiteSpace($PreviousSourceTag) -or
         $PreviousChannel -notin @('automated', 'stable'))) {
        throw 'PreviousSourceTag and a supported PreviousChannel are required with a previous feed pair.'
    }
    $previousPackageName = $null
    $validatedPreviousPackage = $null
    $validatedPreviousIndex = $null
    $downloadedPreviousIndex = $null
    if ($hasPreviousPackage) {
        $previous = Get-Item -LiteralPath $PreviousPackagePath -ErrorAction Stop
        if ($previous.Extension -ne '.nupkg' -or $previous.Name -notmatch '-full\.nupkg$') {
            throw "Previous Squirrel package must be a full .nupkg: $PreviousPackagePath"
        }
        $previousIndex = Get-Item -LiteralPath $PreviousReleasesPath -ErrorAction Stop
        if ($previousIndex.Name -cne 'RELEASES') {
            throw "Previous Squirrel index must be named RELEASES: $PreviousReleasesPath"
        }
        $previousPackageName = $previous.Name
        $validatedPreviousPackage = Join-Path $scratch $previousPackageName
        $previousInputRoot = Join-Path $scratch 'previous-input'
        New-Item -ItemType Directory -Force $previousInputRoot | Out-Null
        $downloadedPreviousIndex = Join-Path $previousInputRoot 'RELEASES'
        $validatedPreviousIndex = Join-Path $scratch 'previous-RELEASES'
        Copy-Item -LiteralPath $previous.FullName -Destination $validatedPreviousPackage -Force
        Copy-Item -LiteralPath $previousIndex.FullName -Destination $downloadedPreviousIndex -Force
        $deltaValidator = Join-Path $PSScriptRoot '..\scripts\validate_squirrel_delta_base.py'
        $validatorArgs = @(
            $deltaValidator,
            '--current', $Version,
            '--package', $validatedPreviousPackage,
            '--releases', $downloadedPreviousIndex,
            '--expected-source', $PreviousSourceTag,
            '--channel', $PreviousChannel,
            '--output-releases', $validatedPreviousIndex
        )
        if (-not [string]::IsNullOrWhiteSpace($PreviousPackageSha256)) {
            $validatorArgs += @('--package-sha256', $PreviousPackageSha256)
        }
        if (-not [string]::IsNullOrWhiteSpace($PreviousReleasesSha256)) {
            $validatorArgs += @('--releases-sha256', $PreviousReleasesSha256)
        }
        Invoke-Native 'python' $validatorArgs
    }
    $nugetUri = "https://dist.nuget.org/win-x86-commandline/$NuGetVersion/nuget.exe"
    Invoke-Native 'curl.exe' @(
        '--fail', '--location', '--silent', '--show-error', '--retry', '4',
        '--retry-all-errors', '--output', $nuget, $nugetUri
    )
    $nugetHash = Get-Sha256 $nuget
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
    if (Test-Path -LiteralPath $releaseDir) {
        Remove-Item -LiteralPath $releaseDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force $releaseDir | Out-Null
    if ($previousPackageName) {
        Copy-Item -LiteralPath $validatedPreviousPackage -Destination (Join-Path $releaseDir $previousPackageName) -Force
        Copy-Item -LiteralPath $validatedPreviousIndex -Destination (Join-Path $releaseDir 'RELEASES') -Force
    }
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
        if (-not $previousPackageName) {
            $releasifyArgs += '--no-delta'
        }
        Invoke-SquirrelWithTimeout $squirrel $releasifyArgs $SquirrelTimeoutSeconds
    }
    finally { Set-Location $oldLocation }

    # Squirrel 2.0.1 dispatches archive work asynchronously on some Windows
    # runners. Wait for the release contract rather than trusting process exit.
    $required = @('Setup.exe', 'RELEASES', "Amulet-$Version-full.nupkg")
    if ($previousPackageName) {
        $required += "Amulet-$Version-delta.nupkg"
    }
    $deadline = [DateTime]::UtcNow.AddSeconds(60)
    while ([DateTime]::UtcNow -lt $deadline -and
        (@($required | Where-Object { -not (Test-Path (Join-Path $releaseDir $_)) }).Count -gt 0)) {
        Start-Sleep -Milliseconds 500
    }
    foreach ($name in $required) {
        $path = Join-Path $releaseDir $name
        if (-not (Test-Path $path)) { throw "Squirrel did not create required artifact: $name" }
    }

    # The previous full package is an input to releasify, not a new public
    # asset. Remove it after Squirrel has had the chance to emit a delta.
    if ($previousPackageName) {
        Remove-Item -LiteralPath (Join-Path $releaseDir $previousPackageName) -Force -ErrorAction SilentlyContinue
    }

    $signatureTargets = Get-ChildItem -Path $releaseDir -File |
        Where-Object { $_.Extension -in @('.exe', '.dll') }
    if (-not ($signatureTargets | Where-Object Name -eq 'Setup.exe')) {
        throw 'Squirrel output has no Setup.exe to verify'
    }
    foreach ($file in $signatureTargets) {
        $signatureStatus = Get-SignatureStatus $file.FullName
        if ($signatureStatus -ne 'NotSigned') {
            throw "Unsigned policy violated: $($file.Name) reports $signatureStatus"
        }
    }
    $releaseIndexPath = Join-Path $releaseDir 'RELEASES'
    $releaseIndex = Get-Content $releaseIndexPath -Raw
    $entryPattern = '^(?<sha1>[0-9a-fA-F]{40})\s+(?<filename>\S+)\s+(?<size>\d+)(?:\s+#\s+\d{1,3}%)?$'
    $entries = @()
    foreach ($line in ($releaseIndex -split '\r?\n')) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        if ($line -notmatch $entryPattern) {
            throw "Squirrel generated an invalid RELEASES entry: $line"
        }
        $entries += [pscustomobject]@{
            Sha1 = $Matches.sha1.ToLowerInvariant()
            Filename = $Matches.filename
            Size = [long]$Matches.size
        }
    }

    # Squirrel carries prior rows into its generated feed. Validate the current
    # full and delta outputs against that generated index, then publish only the
    # current full package in the client feed. The delta remains a release asset
    # for controlled compatibility testing, but clients must not select it until
    # a three-version install/update proof has passed.
    $currentPackageNames = @()
    if ($previousPackageName) {
        $currentPackageNames += "Amulet-$Version-delta.nupkg"
    }
    $currentPackageNames += "Amulet-$Version-full.nupkg"
    $validatedEntries = @{}
    foreach ($packageName in $currentPackageNames) {
        $matches = @($entries | Where-Object { $_.Filename -ceq $packageName })
        if ($matches.Count -ne 1) {
            throw "RELEASES must contain exactly one current entry for $packageName; found $($matches.Count)."
        }
        $artifact = Get-Item -LiteralPath (Join-Path $releaseDir $packageName) -ErrorAction Stop
        $actualSha1 = Get-Sha1 $artifact.FullName
        if ($matches[0].Sha1 -ne $actualSha1) {
            throw "RELEASES SHA-1 mismatch for $packageName"
        }
        if ($matches[0].Size -ne $artifact.Length) {
            throw "RELEASES size mismatch for $packageName"
        }
        $validatedEntries[$packageName] = "$actualSha1 $packageName $($artifact.Length)"
    }
    $fullPackageName = "Amulet-$Version-full.nupkg"
    $publishableEntries = @($validatedEntries[$fullPackageName])
    [IO.File]::WriteAllText(
        $releaseIndexPath,
        ($publishableEntries -join "`n"),
        [Text.UTF8Encoding]::new($false)
    )
    $releaseIndex = Get-Content $releaseIndexPath -Raw
    if ($releaseIndex -notmatch [regex]::Escape("Amulet-$Version-full.nupkg")) {
        throw 'RELEASES does not reference the full package'
    }
    if ($releaseIndex -match '-delta\.nupkg') {
        throw 'RELEASES must remain full-only until the delta update path has three-version client proof'
    }
    if ($previousPackageName -and $releaseIndex -match [regex]::Escape($previousPackageName)) {
        throw 'RELEASES still advertises the unpublished previous full package'
    }
    Write-Output "Squirrel.Windows $SquirrelVersion produced unsigned artifacts in $releaseDir"
}
finally {
    if (Test-Path $scratch) {
        try { Remove-Item $scratch -Recurse -Force -ErrorAction Stop }
        catch { Write-Warning "Squirrel left a locked temporary log at $scratch; the CI workspace can discard it." }
    }
}
