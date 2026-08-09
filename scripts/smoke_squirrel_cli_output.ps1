[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$localAppData = [Environment]::GetFolderPath(
    [Environment+SpecialFolder]::LocalApplicationData
)
$probeRoot = Join-Path $localAppData (
    'amulet-squirrel-cli-probe-' + [guid]::NewGuid().ToString('N')
)
$resolvedLocalAppData = [IO.Path]::GetFullPath($localAppData)
$resolvedProbe = [IO.Path]::GetFullPath($probeRoot)
if (-not $resolvedProbe.StartsWith(
        $resolvedLocalAppData,
        [StringComparison]::OrdinalIgnoreCase
    ) -or
    [IO.Path]::GetFileName($resolvedProbe) -notlike 'amulet-squirrel-cli-probe-*') {
    throw "Refusing unsafe Squirrel CLI probe path: $resolvedProbe"
}

function Get-Hash([string] $Path, [string] $Algorithm) {
    return (Get-FileHash -Algorithm $Algorithm -LiteralPath $Path).Hash.ToLowerInvariant()
}

try {
    New-Item -ItemType Directory -Force $resolvedProbe | Out-Null
    $nuget = Join-Path $resolvedProbe 'nuget.exe'
    & curl.exe `
        --fail `
        --location `
        --silent `
        --show-error `
        --retry 3 `
        --output $nuget `
        'https://dist.nuget.org/win-x86-commandline/v6.14.0/nuget.exe'
    if ($LASTEXITCODE -ne 0) {
        throw "NuGet download failed with exit code $LASTEXITCODE"
    }
    $expectedNuget = '92dbed160ddee0f64b901e907439e021211b428e57c089ecc12fc38dcc4bd9a5'
    $actualNuget = Get-Hash $nuget SHA256
    if ($actualNuget -cne $expectedNuget) {
        throw "NuGet v6.14.0 SHA-256 mismatch"
    }

    $toolCache = Join-Path $resolvedProbe 'tool-cache'
    & $nuget install squirrel.windows `
        -Version 2.0.1 `
        -OutputDirectory $toolCache `
        -NonInteractive `
        -DirectDownload `
        -NoCache | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Squirrel.Windows restore failed with exit code $LASTEXITCODE"
    }

    $tools = Join-Path $toolCache 'squirrel.windows.2.0.1\tools'
    Copy-Item -LiteralPath (Join-Path $tools 'Squirrel.exe') `
        -Destination (Join-Path $resolvedProbe 'Update.exe')
    $update = Join-Path $resolvedProbe 'Update.exe'
    $packages = Join-Path $resolvedProbe 'packages'
    $app = Join-Path $resolvedProbe 'app-0.10.100426'
    $feed = Join-Path $resolvedProbe 'feed'
    New-Item -ItemType Directory -Force $packages, $app, $feed | Out-Null

    $current = Join-Path $packages 'Amulet-0.10.100426-full.nupkg'
    $future = Join-Path $feed 'Amulet-0.10.100427-full.nupkg'
    [IO.File]::WriteAllBytes($current, [byte[]](1, 2, 3))
    [IO.File]::WriteAllBytes($future, [byte[]](1, 2, 3, 4))
    [IO.File]::WriteAllBytes((Join-Path $app 'Amulet.exe'), [byte[]](77, 90))
    $currentEntry = "$(Get-Hash $current SHA1) $([IO.Path]::GetFileName($current)) 3`r`n"
    $futureEntry = "$(Get-Hash $future SHA1) $([IO.Path]::GetFileName($future)) 4`r`n"
    [IO.File]::WriteAllText(
        (Join-Path $packages 'RELEASES'),
        $currentEntry,
        [Text.UTF8Encoding]::new($false)
    )
    [IO.File]::WriteAllText(
        (Join-Path $feed 'RELEASES'),
        $futureEntry,
        [Text.UTF8Encoding]::new($false)
    )

    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $update
    $startInfo.ArgumentList.Add('--checkForUpdate=' + $feed)
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    [void] $process.Start()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    if (-not $process.WaitForExit(30000)) {
        $process.Kill()
        throw 'Squirrel checkForUpdate probe timed out'
    }
    if ($process.ExitCode -ne 0) {
        throw "Squirrel checkForUpdate failed with exit code $($process.ExitCode): $stderr"
    }

    $endsCrLf = $stdout.EndsWith("`r`n")
    $endsLf = -not $endsCrLf -and $stdout.EndsWith("`n")
    $withoutTerminator = if ($endsCrLf) {
        $stdout.Substring(0, $stdout.Length - 2)
    }
    elseif ($endsLf) {
        $stdout.Substring(0, $stdout.Length - 1)
    }
    else {
        $stdout
    }
    $lines = @([regex]::Split($withoutTerminator, '\r\n|\n|\r'))
    $blankLineCount = @($lines | Where-Object { $_ -eq '' }).Count
    if ($lines.Count -lt 1 -or $blankLineCount -ne 0) {
        throw 'Squirrel checkForUpdate emitted an empty or blank output line'
    }
    if ($lines.Count -gt 1) {
        foreach ($line in $lines[0..($lines.Count - 2)]) {
            if ($line -cnotmatch '^(?:0|[1-9]\d?|100)$') {
                throw "Squirrel checkForUpdate emitted invalid progress: $line"
            }
        }
    }
    $payload = $lines[-1] | ConvertFrom-Json
    $propertyNames = @($payload.PSObject.Properties.Name | Sort-Object)
    $expectedProperties = @(
        'currentVersion',
        'futureVersion',
        'releasesToApply'
    ) | Sort-Object
    if (Compare-Object $propertyNames $expectedProperties) {
        throw 'Squirrel checkForUpdate emitted an unexpected JSON schema'
    }

    [pscustomobject]@{
        squirrel_version = '2.0.1'
        exit_code = $process.ExitCode
        progress_lines = $lines.Count - 1
        newline = if ($endsCrLf) { 'CRLF' } elseif ($endsLf) { 'LF' } else { 'none' }
        terminal_newline = $endsCrLf -or $endsLf
        blank_lines = 0
        current_version = [string] $payload.currentVersion
        future_version = [string] $payload.futureVersion
        releases_to_apply = @($payload.releasesToApply).Count
        stderr_bytes = [Text.Encoding]::UTF8.GetByteCount($stderr)
    } | ConvertTo-Json -Compress
}
finally {
    if (Test-Path -LiteralPath $resolvedProbe) {
        Remove-Item -LiteralPath $resolvedProbe -Recurse -Force
    }
}
