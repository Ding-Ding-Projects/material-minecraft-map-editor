[CmdletBinding()]
param(
    [switch] $LifecycleSelfTest
)

$ErrorActionPreference = 'Stop'

function Invoke-BoundedProcessCapture {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [Diagnostics.ProcessStartInfo] $StartInfo,
        [ValidateRange(1, 600000)]
        [int] $TimeoutMilliseconds,
        [ValidateRange(1, 30000)]
        [int] $ReadTimeoutMilliseconds = 5000,
        [ValidateRange(1, 1048576)]
        [int] $MaximumStreamBytes = 65536
    )

    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $StartInfo
    try {
        [void] $process.Start()
        # Both pipes must drain before waiting for process exit or either full
        # pipe can deadlock the probe before its timeout is ever observed.
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $timedOut = -not $process.WaitForExit($TimeoutMilliseconds)
        if ($timedOut) {
            try {
                $process.Kill($true)
            }
            catch {
                $process.Kill()
            }
            if (-not $process.WaitForExit(5000)) {
                throw 'Squirrel probe did not terminate within 5 seconds after kill'
            }
        }

        $readTasks = [Threading.Tasks.Task[]] @($stdoutTask, $stderrTask)
        if (-not [Threading.Tasks.Task]::WaitAll(
                $readTasks,
                $ReadTimeoutMilliseconds
            )) {
            if (-not $process.HasExited) {
                try {
                    $process.Kill($true)
                }
                catch {
                    $process.Kill()
                }
                [void] $process.WaitForExit(5000)
            }
            throw "Squirrel probe output reads exceeded $ReadTimeoutMilliseconds ms"
        }

        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        if ([Text.Encoding]::UTF8.GetByteCount($stdout) -gt $MaximumStreamBytes -or
            [Text.Encoding]::UTF8.GetByteCount($stderr) -gt $MaximumStreamBytes) {
            throw "Squirrel probe output exceeded $MaximumStreamBytes bytes per stream"
        }
        if ($timedOut) {
            throw [TimeoutException]::new(
                "Squirrel probe exceeded $TimeoutMilliseconds ms and was killed"
            )
        }
        return [pscustomobject]@{
            ExitCode = $process.ExitCode
            Stdout = $stdout
            Stderr = $stderr
        }
    }
    finally {
        $process.Dispose()
    }
}

if ($LifecycleSelfTest) {
    $selfTestInfo = [Diagnostics.ProcessStartInfo]::new()
    $selfTestInfo.FileName = (Get-Process -Id $PID).Path
    $selfTestInfo.ArgumentList.Add('-NoProfile')
    $selfTestInfo.ArgumentList.Add('-Command')
    $selfTestInfo.ArgumentList.Add('Start-Sleep -Seconds 30')
    $selfTestInfo.UseShellExecute = $false
    $selfTestInfo.CreateNoWindow = $true
    $selfTestInfo.RedirectStandardOutput = $true
    $selfTestInfo.RedirectStandardError = $true
    $selfTestTimer = [Diagnostics.Stopwatch]::StartNew()
    try {
        Invoke-BoundedProcessCapture `
            -StartInfo $selfTestInfo `
            -TimeoutMilliseconds 250 | Out-Null
        throw 'Lifecycle self-test child unexpectedly completed'
    }
    catch [TimeoutException] {
        $selfTestTimer.Stop()
        if ($selfTestTimer.ElapsedMilliseconds -gt 10000) {
            throw 'Lifecycle self-test did not kill the hung child promptly'
        }
        [pscustomobject]@{
            lifecycle = 'hung-child-killed'
            elapsed_ms = $selfTestTimer.ElapsedMilliseconds
        } | ConvertTo-Json -Compress
        return
    }
}

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
    $capture = Invoke-BoundedProcessCapture `
        -StartInfo $startInfo `
        -TimeoutMilliseconds 30000
    $stdout = $capture.Stdout
    $stderr = $capture.Stderr
    if ($capture.ExitCode -ne 0) {
        throw "Squirrel checkForUpdate failed with exit code $($capture.ExitCode): $stderr"
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
        exit_code = $capture.ExitCode
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
