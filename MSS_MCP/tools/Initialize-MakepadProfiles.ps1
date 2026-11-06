#requires -Version 7.4
[CmdletBinding()]
param(
    [string]$MakepadDirectory,
    [string]$TargetDirectory
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $IsWindows) { throw 'Native MSS profiles require Windows.' }
$revision = '2271c0eb350cedd497c84373f17ad2b0b662cb72'

function Resolve-LocalPath([string]$Value, [bool]$Directory) {
    $path = [IO.Path]::GetFullPath($Value, (Get-Location).ProviderPath)
    if ($path.StartsWith('\\')) { throw 'Use an absolute local path, not a UNC/device path.' }
    $item = Get-Item -LiteralPath $path -Force
    if ($item.PSIsContainer -ne $Directory) { throw "Unexpected path type: $path" }
    $node = $item
    while ($null -ne $node) {
        if (($node.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Reparse points are not admitted: $($node.FullName)"
        }
        $node = if ($node -is [IO.FileInfo]) { $node.Directory } else { $node.Parent }
    }
    return $item.FullName
}

function Ensure-LocalDirectory([string]$Parent, [string]$Name) {
    $verifiedParent = Resolve-LocalPath $Parent $true
    $path = Join-Path $verifiedParent $Name
    if (-not (Test-Path -LiteralPath $path)) {
        [void][IO.Directory]::CreateDirectory($path)
    }
    return Resolve-LocalPath $path $true
}

function Read-Git([string[]]$Arguments) {
    $output = & $script:git --no-optional-locks -C $script:sdk @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Could not verify the Makepad checkout with Git ($($Arguments[0]))." }
    return $output
}

function ConvertTo-JsonBytes($Value) {
    $text = ($Value | ConvertTo-Json -Depth 8) + [Environment]::NewLine
    return ,([Text.Encoding]::UTF8.GetBytes($text))
}

function Get-BytesHash([byte[]]$Bytes) {
    return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($Bytes))
}

$repo = Resolve-LocalPath (Join-Path $PSScriptRoot '../..') $true
if (-not $MakepadDirectory) { $MakepadDirectory = Join-Path $repo 'makepad-work' }
if (-not $TargetDirectory) { $TargetDirectory = Join-Path $repo 'makepad-work-target' }
$sdk = Resolve-LocalPath $MakepadDirectory $true
$release = Resolve-LocalPath (Join-Path $TargetDirectory 'release') $true
$git = (Get-Command git.exe -CommandType Application | Select-Object -First 1).Path

$checkoutRoot = Read-Git @('rev-parse', '--show-toplevel')
if ((Resolve-LocalPath $checkoutRoot $true) -ine $sdk) {
    throw 'MakepadDirectory must identify the root of its own Git checkout.'
}
$origin = Read-Git @('remote', 'get-url', 'origin')
if ($origin -cnotmatch '^https://github\.com/makepad/makepad(?:\.git)?/?$') {
    throw 'Use a Makepad checkout with the official HTTPS origin.'
}
if ((Read-Git @('rev-parse', 'HEAD')) -cne $revision) {
    throw "Check out Makepad $revision before building the fixture executables."
}
if (@(Read-Git @('status', '--porcelain=v1', '--untracked-files=normal')).Count -ne 0) {
    throw 'Build the fixtures from a clean Makepad checkout.'
}

$pwsh = Resolve-LocalPath (Get-Process -Id $PID).Path $false
if ([IO.Path]::GetFileName($pwsh) -ine 'pwsh.exe') { throw 'Run this script with PowerShell 7.' }
$launcher = Resolve-LocalPath (Join-Path $PSScriptRoot 'Start-MakepadMcp.ps1') $false
$remote = Resolve-LocalPath (Join-Path $release 'makepad-remote.exe') $false
$remoteHash = (Get-FileHash -LiteralPath $remote -Algorithm SHA256).Hash
$profilesDirectory = Resolve-LocalPath (Join-Path $repo 'MSS_MCP/profiles') $true

$fixtures = @(
    [ordered]@{ id = 'todo'; title = 'Makepad Todo'; executable = 'makepad-example-todo.exe' }
    [ordered]@{ id = 'counter'; title = 'Makepad Counter'; executable = 'makepad-example-counter.exe' }
)
$profiles = [Collections.Generic.List[object]]::new()
$pending = [Collections.Generic.List[object]]::new()
$generatedProfiles = Join-Path $repo 'local/makepad-profiles'
$sessionRoot = Join-Path $repo 'proof/mcp-sessions'

foreach ($fixture in $fixtures) {
    $app = Resolve-LocalPath (Join-Path $release $fixture.executable) $false
    $relativeProfile = "local/makepad-profiles/$($fixture.id).json"
    $bytes = ConvertTo-JsonBytes ([ordered]@{
        schema_version = 1
        id = $fixture.id
        admission = 'TRUSTED_DEVELOPMENT'
        makepad_revision = $revision
        remote_supported = $true
        hidden_native_supported = $true
        app_executable = $app
        app_sha256 = (Get-FileHash -LiteralPath $app -Algorithm SHA256).Hash
        remote_executable = $remote
        remote_sha256 = $remoteHash
        working_directory = $sdk
        session_root = $sessionRoot
        app_arguments = @()
    })
    $profiles.Add([ordered]@{
        profile = $fixture.id
        title = $fixture.title
        access = 'semantic'
        kind = 'native'
        profile_file = $relativeProfile
        profile_sha256 = Get-BytesHash $bytes
    })
    $pending.Add(@{ Path = (Join-Path $repo $relativeProfile); Bytes = $bytes })
}

$catalogPath = Join-Path $profilesDirectory 'local.apps.json'
$pending.Add(@{
    Path = $catalogPath
    Bytes = (ConvertTo-JsonBytes ([ordered]@{
        schema_version = 1
        launcher_sha256 = (Get-FileHash -LiteralPath $launcher -Algorithm SHA256).Hash
        pwsh_executable = $pwsh
        pwsh_sha256 = (Get-FileHash -LiteralPath $pwsh -Algorithm SHA256).Hash
        profiles = $profiles.ToArray()
    }))
})

# The generated catalog is published last, and existing operator data is preserved.
$missing = [Collections.Generic.List[object]]::new()
foreach ($file in $pending) {
    if (Test-Path -LiteralPath $file.Path) {
        $existing = Resolve-LocalPath $file.Path $false
        if ((Get-FileHash -LiteralPath $existing -Algorithm SHA256).Hash -cne (Get-BytesHash $file.Bytes)) {
            throw "Existing configuration differs: $existing. Review or move it before initializing again."
        }
    } else {
        $missing.Add($file)
    }
}

$local = Ensure-LocalDirectory $repo 'local'
[void](Ensure-LocalDirectory $local 'makepad-profiles')
$proof = Ensure-LocalDirectory $repo 'proof'
[void](Ensure-LocalDirectory $proof 'mcp-sessions')
foreach ($file in $missing) {
    $stream = [IO.File]::Open($file.Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $stream.Write($file.Bytes, 0, $file.Bytes.Length) }
    finally { $stream.Dispose() }
}

[ordered]@{
    status = 'INITIALIZED'
    makepad_revision = $revision
    release_directory = $release
    catalog = $catalogPath
    profile_directory = $generatedProfiles
    evidence_root = $proof
    profiles = @($fixtures | ForEach-Object { $_.id })
} | ConvertTo-Json -Depth 5
