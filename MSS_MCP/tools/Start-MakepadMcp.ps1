#requires -Version 7.4
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Profile,
    [switch]$ValidateOnly
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Development launcher only. MCP and app commands are implemented by Makepad.
# stdout belongs exclusively to the official MCP process.
function Resolve-LocalPath([string]$Value, [bool]$Directory) {
    if (-not [IO.Path]::IsPathFullyQualified($Value) -or $Value.StartsWith('\\')) { throw 'Paths must be absolute local paths, not UNC/device paths.' }
    $item = Get-Item -LiteralPath $Value -Force
    if ($item.PSIsContainer -ne $Directory) { throw 'Unexpected path type.' }
    $node = $item
    while ($null -ne $node) {
        if (($node.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw 'Reparse points are not admitted by this launcher.'
        }
        $node = if ($node -is [IO.FileInfo]) { $node.Directory } else { $node.Parent }
    }
    return $item.FullName
}
function Open-PinnedExecutable([string]$Path, [string]$ExpectedHash) {
    if ($ExpectedHash -notmatch '^[a-fA-F0-9]{64}$') { throw 'Missing executable SHA-256.' }
    if ([IO.Path]::GetExtension($Path) -ine '.exe') { throw 'Only native Windows executables are admitted.' }
    $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    try {
        $actual = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($stream))
        if ($actual -ine $ExpectedHash) { throw 'Executable SHA-256 mismatch; admission must be reviewed.' }
        $stream.Position = 0
        return $stream
    } catch { $stream.Dispose(); throw }
}
function New-ChildInfo([string]$Executable, [string[]]$Arguments, [bool]$Capture) {
    $info = [Diagnostics.ProcessStartInfo]::new($Executable)
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.WorkingDirectory = $script:workingDirectory
    foreach ($argument in $Arguments) { $info.ArgumentList.Add($argument) }
    $info.Environment['TEMP'] = $script:sessionDirectory
    $info.Environment['TMP'] = $script:sessionDirectory
    $info.Environment['MAKEPAD_HIDE_WINDOWS'] = '1'
    [void]$info.Environment.Remove('MAKEPAD_FOCUS')
    [void]$info.Environment.Remove('MAKEPAD_HAL_BACKEND')
    $info.RedirectStandardOutput = $Capture
    $info.RedirectStandardError = $Capture
    return $info
}
function Invoke-OwnedRemote([string[]]$Words) {
    $info = New-ChildInfo $script:remoteExecutable (@('app', [string]$script:app.Id) + $Words) $true
    $info.RedirectStandardInput = $true
    $client = [Diagnostics.Process]::Start($info)
    $client.StandardInput.Close()
    $output = $client.StandardOutput.ReadToEndAsync()
    $errors = $client.StandardError.ReadToEndAsync()
    try {
        if (-not $client.WaitForExit(10000)) {
            # This is the launcher-created read/cleanup client, not the application.
            $client.Kill()
            if (-not $client.WaitForExit(5000)) { throw 'Owned Remote helper did not exit after termination.' }
            throw 'Remote client timed out; no mutation is replayed.'
        }
        return @{ ExitCode = $client.ExitCode; Output = $output.GetAwaiter().GetResult() }
    } finally { $client.Dispose() }
}
function Initialize-OwnedProcessInterop {
    if ('MssOwnedProcess' -as [type]) { return }
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;
public sealed class MssOwnedSnapshot {
    public uint Pid;
    public long BirthFileTime;
    public bool Exited;
    public int? ExitCode;
}
public static class MssOwnedProcess {
    [DllImport("kernel32.dll", SetLastError=true)]
    private static extern uint GetProcessId(SafeProcessHandle process);
    [DllImport("kernel32.dll", SetLastError=true)]
    private static extern bool GetProcessTimes(SafeProcessHandle process, out long creation,
        out long exit, out long kernel, out long user);
    [DllImport("kernel32.dll", SetLastError=true)]
    private static extern uint WaitForSingleObject(SafeProcessHandle process, uint milliseconds);
    [DllImport("kernel32.dll", SetLastError=true)]
    private static extern bool GetExitCodeProcess(SafeProcessHandle process, out uint code);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    private static extern bool QueryFullProcessImageNameW(SafeProcessHandle process, uint flags,
        StringBuilder image, ref uint length);
    public static MssOwnedSnapshot Read(SafeProcessHandle process) {
        uint pid = GetProcessId(process);
        long born, exited, kernel, user;
        if (pid == 0 || !GetProcessTimes(process, out born, out exited, out kernel, out user))
            throw new Win32Exception(Marshal.GetLastWin32Error(), "Retained process identity unavailable.");
        uint wait = WaitForSingleObject(process, 0);
        if (wait != 0 && wait != 258)
            throw new Win32Exception(Marshal.GetLastWin32Error(), "Retained process wait failed.");
        var value = new MssOwnedSnapshot { Pid=pid, BirthFileTime=born, Exited=(wait == 0) };
        if (value.Exited) {
            uint code;
            if (!GetExitCodeProcess(process, out code))
                throw new Win32Exception(Marshal.GetLastWin32Error(), "Retained exit code unavailable.");
            value.ExitCode = unchecked((int)code);
        }
        return value;
    }
    public static string Image(SafeProcessHandle process) {
        var current = Read(process);
        if (current.Exited) return null;
        uint size = 32768;
        var image = new StringBuilder((int)size);
        if (!QueryFullProcessImageNameW(process, 0, image, ref size)) return null;
        return image.ToString();
    }
}
'@
}
function Read-OwnedApp {
    if ($null -eq $script:appHandle) { throw 'No retained application handle.' }
    $current = [MssOwnedProcess]::Read($script:appHandle)
    if ($current.Pid -ne $script:receipt.app_pid -or $current.BirthFileTime -ne $script:birthFileTime) {
        throw 'Retained app PID or birth identity mismatch.'
    }
    return $current
}
function Set-OwnedImage {
    $image = [MssOwnedProcess]::Image($script:appHandle)
    if ([string]::IsNullOrEmpty($image)) { return $false }
    if ($image -ine $script:appExecutable) { throw 'App image identity mismatch.' }
    if ($script:receipt.app_image_verified -and $script:receipt.app_image -ine $image) {
        throw 'Confirmed app image changed.'
    }
    $script:receipt.app_image = $image
    $script:receipt.app_image_verified = $true
    return $true
}
function Wait-OwnedImage {
    $clock = [Diagnostics.Stopwatch]::StartNew()
    do {
        $current = Read-OwnedApp
        if ($current.Exited) { return $false }
        if (Set-OwnedImage) { return $true }
        Start-Sleep -Milliseconds 20
    } while ($clock.ElapsedMilliseconds -lt 2000)
    return $false
}
function Confirm-OwnedApp {
    $current = Read-OwnedApp
    if ($current.Exited) { return $false }
    if (-not (Set-OwnedImage)) { throw 'Owned live app image identity is unavailable.' }
    return $true
}
function Save-OwnedExitProof {
    $current = Read-OwnedApp
    if (-not $current.Exited) { throw 'Retained owned process has not exited.' }
    $script:receipt.app_exit_code = $current.ExitCode
    $script:receipt.exit_proof = @{
        kind='retained_process_handle';pid=[int]$current.Pid
        birth_filetime=$current.BirthFileTime;exit_observed=$true
        exit_code=$current.ExitCode;image_verified=$script:receipt.app_image_verified
    }
}
function Write-Receipt {
    $text = $script:receipt | ConvertTo-Json -Depth 8
    [IO.File]::WriteAllText((Join-Path $script:sessionDirectory 'session.json'), $text + [Environment]::NewLine)
}

$appPin = $null
$stdoutSink = $null
$remotePin = $null
$app = $null
$appHandle = $null
$launcherProcess = $null
$birthFileTime = $null
$server = $null
$logs = @()
$pumps = @()
$exitCode = 1
try {
    $profilePath = Resolve-LocalPath $Profile $false
    $profileBytes = [IO.File]::ReadAllBytes($profilePath)
    $profileDigest = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($profileBytes))
    $configuration = [Text.Encoding]::UTF8.GetString($profileBytes) | ConvertFrom-Json -AsHashtable
    if ($configuration -isnot [Collections.IDictionary]) { throw 'Profile must be a JSON object.' }
    if (($configuration.schema_version -isnot [long] -and $configuration.schema_version -isnot [int]) -or
        $configuration.schema_version -ne 1) { throw 'Unsupported profile schema.' }
    foreach ($key in @('id','admission','makepad_revision','app_executable','app_sha256',
        'remote_executable','remote_sha256','working_directory','session_root')) {
        if ($configuration[$key] -isnot [string] -or [string]::IsNullOrWhiteSpace($configuration[$key])) {
            throw ('Missing or incorrectly typed profile field: ' + $key)
        }
    }
    if ($configuration.id -cnotmatch '^[a-z][a-z0-9_-]{0,63}$') { throw 'Invalid application profile ID.' }
    if ($configuration.admission -ne 'TRUSTED_DEVELOPMENT') { throw 'BLOCKED: application is not admitted.' }
    if ($configuration.remote_supported -isnot [bool] -or $configuration.hidden_native_supported -isnot [bool] -or
        $configuration.remote_supported -ne $true -or $configuration.hidden_native_supported -ne $true) {
        throw 'BLOCKED: Remote and native hidden mode must be source-qualified before execution.'
    }
    if ($configuration.makepad_revision -notmatch '^[a-fA-F0-9]{40}$') { throw 'Exact Makepad revision is required.' }
    $appExecutable = Resolve-LocalPath $configuration.app_executable $false
    $remoteExecutable = Resolve-LocalPath $configuration.remote_executable $false
    $workingDirectory = Resolve-LocalPath $configuration.working_directory $true
    $sessionRoot = Resolve-LocalPath $configuration.session_root $true
    $appArguments = @('--remote')
    if ($configuration.ContainsKey('app_arguments')) {
        if ($configuration.app_arguments -isnot [Collections.IList]) { throw 'App arguments must be an array.' }
        foreach ($argument in $configuration.app_arguments) {
            if ($argument -isnot [string] -or $argument.Contains([char]0)) { throw 'App arguments must be literal strings.' }
            if ($argument -match '^--(remote|stdin-loop)(=|$)') { throw 'Reserved launch argument.' }
            $appArguments += $argument
        }
    }
    # Deny executable write/delete while this launcher retains the admitted files.
    $appPin = Open-PinnedExecutable $appExecutable $configuration.app_sha256
    $remotePin = Open-PinnedExecutable $remoteExecutable $configuration.remote_sha256
    if ($ValidateOnly) {
        @{status='VALIDATED';id=$configuration.id;makepad_revision=$configuration.makepad_revision} |
            ConvertTo-Json -Compress
        $exitCode = 0
    } else {
        if (-not $IsWindows) { throw 'This launcher is qualified for native Windows only.' }
        Initialize-OwnedProcessInterop
        $launcherProcess = [Diagnostics.Process]::GetCurrentProcess()
        $launcherState = [MssOwnedProcess]::Read($launcherProcess.SafeHandle)
        $launcherImage = [MssOwnedProcess]::Image($launcherProcess.SafeHandle)
        if ([string]::IsNullOrEmpty($launcherImage)) { throw 'Launcher process identity unavailable.' }
        $sessionId = [Guid]::NewGuid().ToString('N')
        $sessionDirectory = Join-Path $sessionRoot ($configuration.id + '-' + $sessionId)
        [void][IO.Directory]::CreateDirectory($sessionDirectory)
        $receipt = @{
            schema_version=1;session_id=$sessionId;profile_id=$configuration.id
            profile_sha256=$profileDigest
            makepad_revision_declared=$configuration.makepad_revision
            app_sha256=$configuration.app_sha256;remote_sha256=$configuration.remote_sha256
            started_utc=[DateTime]::UtcNow.ToString('o');status='STARTING'
            cleanup='NOT_RUN';mcp_exit_code=$null;app_exit_code=$null
            app_pid=$null;app_birth_utc=$null;app_birth_filetime=$null
            app_image_expected=$appExecutable;app_image=$null;app_image_verified=$false
            launch_intent_utc=[DateTime]::UtcNow.ToString('o');process_started=$false
            startup_qualified=$false;exit_proof=$null;mcp_started=$false;mcp_exit_observed=$false
            launcher_pid=[int]$launcherState.Pid;launcher_birth_filetime=$launcherState.BirthFileTime
            launcher_birth_utc=[DateTime]::FromFileTimeUtc($launcherState.BirthFileTime).ToString('o')
            launcher_image=$launcherImage;launcher_image_sha256=(Get-FileHash -LiteralPath $launcherImage -Algorithm SHA256).Hash
            launcher_script_path=$PSCommandPath;launcher_script_sha256=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash
            limitations=@('trusted development only','same-user OS isolation NOT_VERIFIED',
                'supervisor crash cleanup NOT_VERIFIED','descendant containment NOT_VERIFIED',
                'filesystem/network confinement and log disk quotas NOT_IMPLEMENTED')
        }
        # Persist launch intent before Process.Start. A PID alone never grants cleanup authority.
        Write-Receipt
        $appInfo = New-ChildInfo $appExecutable $appArguments $true
        $appInfo.RedirectStandardInput = $true
        $app = [Diagnostics.Process]::Start($appInfo)
        $appHandle = $app.SafeHandle
        $created = [MssOwnedProcess]::Read($appHandle)
        $birthFileTime = $created.BirthFileTime
        $receipt.process_started = $true
        $receipt.app_pid = [int]$created.Pid
        $receipt.app_birth_filetime = $birthFileTime
        $receipt.app_birth_utc = [DateTime]::FromFileTimeUtc($birthFileTime).ToString('o')
        Write-Receipt
        $app.StandardInput.Close()
        foreach ($name in @('stdout','stderr')) {
            $file = [IO.File]::Open((Join-Path $sessionDirectory ('app-' + $name + '.log')),
                [IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
            $logs += $file
            $reader = if ($name -eq 'stdout') { $app.StandardOutput } else { $app.StandardError }
            $pumps += $reader.BaseStream.CopyToAsync($file)
        }
        if (-not (Wait-OwnedImage)) {
            throw 'Owned app exited or image identity was unavailable within 2000 ms; no Remote request was sent.'
        }
        Write-Receipt
        $discoveryPath = Join-Path $sessionDirectory ('makepad-remote-' + $app.Id + '.json')
        $deadline = [DateTime]::UtcNow.AddSeconds(30)
        $ready = $false
        while ([DateTime]::UtcNow -lt $deadline) {
            if (-not (Confirm-OwnedApp)) { throw 'Owned app exited before readiness.' }
            if (Test-Path -LiteralPath $discoveryPath) {
                $discovery = Get-Content -LiteralPath $discoveryPath -Raw | ConvertFrom-Json -AsHashtable
                if ($discovery.pid -ne $app.Id -or $discovery.app -ine [IO.Path]::GetFileName($appExecutable) -or
                    $discovery.socket -notmatch '^tcp:127\.0\.0\.1:[0-9]+$' -or
                    [string]::IsNullOrEmpty($discovery.token)) { throw 'Discovery did not match the owned app.' }
                $answer = Invoke-OwnedRemote @('status')
                if ($answer.ExitCode -eq 0) {
                    foreach ($line in ($answer.Output -split "\r?\n")) {
                        if ($line.StartsWith('{')) {
                            $state = $line | ConvertFrom-Json -AsHashtable
                            if ($state.pid -eq $app.Id -and @($state.w).Count -gt 0) { $ready = $true }
                        }
                    }
                }
                if ($ready) { break }
            }
            Start-Sleep -Milliseconds 100
        }
        if (-not $ready) { throw 'BLOCKED: owned app Remote/window readiness was not established.' }
        $receipt.status = 'READY'
        $receipt.startup_qualified = $true
        Write-Receipt
        [Console]::Error.WriteLine('[MSS] Profile ' + $configuration.id + '; session ' + $sessionId + '; owned pid ' + $app.Id)
        # Copy raw bytes: no PowerShell text pipeline or JSON-RPC implementation.
        # Console's output stream suppresses broken-pipe errors on Windows.
        # FileStream over the same inherited stdout handle preserves disconnect errors.
        Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class MssMcpStdout {
    [DllImport("kernel32.dll", SetLastError=true)]
    private static extern IntPtr GetStdHandle(int name);
    public static Stream Open() {
        return new FileStream(new SafeFileHandle(GetStdHandle(-11), false), FileAccess.Write, 1, false);
    }
}
'@
        $stdoutSink = [MssMcpStdout]::Open()
        $serverInfo = New-ChildInfo $remoteExecutable @('mcp',[string]$app.Id) $true
        $serverInfo.RedirectStandardInput = $true
        $server = [Diagnostics.Process]::Start($serverInfo)
        $receipt.mcp_started = $true
        [void]$server.SafeHandle
        $inputPump = [Console]::OpenStandardInput().CopyToAsync($server.StandardInput.BaseStream)
        $outputPump = $server.StandardOutput.BaseStream.CopyToAsync($stdoutSink)
        $errorPump = $server.StandardError.BaseStream.CopyToAsync([Console]::OpenStandardError())
        $inputClosed = $false
        while (-not $server.WaitForExit(100)) {
            if ($outputPump.IsFaulted -or $outputPump.IsCanceled -or $errorPump.IsFaulted -or $errorPump.IsCanceled) {
                throw 'MCP output transport lost; mutation outcome may be OUTCOME_UNKNOWN; no replay.'
            }
            if (-not $inputClosed -and $inputPump.IsCompleted) {
                $inputPump.GetAwaiter().GetResult()
                $server.StandardInput.Close()
                $inputClosed = $true
            }
            if ((Read-OwnedApp).Exited) {
                $receipt.status = 'FAIL_APP_EXIT'
                $server.Kill()
                if (-not $server.WaitForExit(5000)) { throw 'Owned MCP client exit is unavailable.' }
                throw 'App exited while MCP was active; no request is replayed.'
            }
        }
        foreach ($pump in @($outputPump,$errorPump)) {
            if (-not $pump.Wait(5000)) { throw 'MCP output transfer did not finish.' }
        }
        $receipt.mcp_exit_code = $server.ExitCode
        $receipt.mcp_exit_observed = $true
        $exitCode = $server.ExitCode
        $receipt.status = if ($exitCode -eq 0) { 'MCP_EXITED' } else { 'FAIL_MCP_EXIT' }
    }
} catch {
    [Console]::Error.WriteLine('[MSS] ' + $_.Exception.Message)
    if (Get-Variable receipt -ErrorAction SilentlyContinue) { $receipt.status = 'FAIL'; $receipt.error = $_.Exception.Message }
    $exitCode = 1
} finally {
    $serverExitConfirmed = $null -eq $server
    if ($server) {
        try {
            if (-not $server.HasExited) {
                $server.Kill()
                if (-not $server.WaitForExit(5000)) { throw 'Owned MCP client did not exit after termination.' }
                $exitCode = 1
            }
            if (-not $server.HasExited) { throw 'Owned MCP client exit is unavailable.' }
            $receipt.mcp_exit_code = $server.ExitCode
            $receipt.mcp_exit_observed = $true
            $serverExitConfirmed = $true
        } catch {
            [Console]::Error.WriteLine('[MSS] MCP cleanup: ' + $_.Exception.Message)
            $exitCode = 1
        }
    }
    if ($app) {
        $appExitConfirmed = $false
        try {
            if (Confirm-OwnedApp) {
                try { [void](Invoke-OwnedRemote @('gq')) } catch { [Console]::Error.WriteLine('[MSS] gq response unavailable; checking owned process exit.') }
                if (-not $app.WaitForExit(8000)) {
                    if (Confirm-OwnedApp) { try { [void](Invoke-OwnedRemote @('quit')) } catch {} }
                    if (-not $app.WaitForExit(8000)) {
                        $receipt.cleanup = 'CLEANUP_PENDING'
                        $exitCode = 1
                        throw 'Owned app did not exit gracefully; no forced termination performed.'
                    }
                }
                $receipt.cleanup = 'GRACEFUL'
            } else { $receipt.cleanup = 'ALREADY_EXITED' }
            Save-OwnedExitProof
            $appExitConfirmed = $true
            if ($receipt.app_exit_code -ne 0) { $exitCode = 1 }
        } catch {
            [Console]::Error.WriteLine('[MSS] Cleanup: ' + $_.Exception.Message)
            $receipt.cleanup = 'CLEANUP_PENDING'
            $exitCode = 1
        }
        $receipt.log_capture = if ($pumps.Count -eq 2 -and $logs.Count -eq 2) { 'COMPLETE' } else { 'INCOMPLETE' }
        if ($receipt.log_capture -ne 'COMPLETE') { $exitCode = 1 }
        foreach ($pump in $pumps) {
            try {
                if (-not $pump.Wait(5000)) { $receipt.log_capture = 'INCOMPLETE'; $exitCode = 1 }
            } catch { $receipt.log_capture = 'INCOMPLETE'; $exitCode = 1 }
        }
        foreach ($log in $logs) {
            try { $log.Dispose() } catch { $receipt.log_capture = 'INCOMPLETE'; $exitCode = 1 }
        }
        $receipt.launcher_exit_code = $exitCode
        if ($appExitConfirmed -and $serverExitConfirmed) {
            $receipt.status = if ($receipt.startup_qualified -and $exitCode -eq 0) { 'CLOSED' } else { 'FAILED_CLOSED' }
        } else {
            $receipt.status = 'CLEANUP_PENDING'
            $receipt.cleanup = 'CLEANUP_PENDING'
            $exitCode = 1
            $receipt.launcher_exit_code = 1
        }
        $receipt.completed_utc = [DateTime]::UtcNow.ToString('o')
        try { Write-Receipt }
        catch { [Console]::Error.WriteLine('[MSS] Final receipt could not be written.'); $exitCode = 1 }
    } elseif (Get-Variable receipt -ErrorAction SilentlyContinue) {
        # A failed Process.Start did not provide a retained handle proving what happened.
        $receipt.status = 'CLEANUP_PENDING'
        $receipt.cleanup = 'CLEANUP_PENDING'
        $receipt.launcher_exit_code = 1
        $receipt.completed_utc = [DateTime]::UtcNow.ToString('o')
        try { Write-Receipt } catch { [Console]::Error.WriteLine('[MSS] Incomplete-launch receipt could not be written.') }
    }
    foreach ($resource in @($server,$app,$remotePin,$appPin,$stdoutSink,$launcherProcess)) {
        if ($null -ne $resource) { try { $resource.Dispose() } catch { $exitCode = 1 } }
    }
}
exit $exitCode
