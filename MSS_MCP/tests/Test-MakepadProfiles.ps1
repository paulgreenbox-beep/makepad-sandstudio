#requires -Version 7.4
[CmdletBinding()]
param([Parameter(Mandatory)][string]$BaselineProfile, [Parameter(Mandatory)][string]$EvidenceRoot)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$launcher=Join-Path $PSScriptRoot '../tools/Start-MakepadMcp.ps1'
$baseline=Get-Content -LiteralPath $BaselineProfile -Raw | ConvertFrom-Json -AsHashtable
$runDirectory=Join-Path $EvidenceRoot ('profile-tests-' + [Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($runDirectory)
$cases=@(
    @{id='valid';expected=0;change=@{}},
    @{id='schema-string';expected=1;change=@{schema_version='1'}},
    @{id='remote-string';expected=1;change=@{remote_supported='true'}},
    @{id='hidden-number';expected=1;change=@{hidden_native_supported=1}},
    @{id='arguments-scalar';expected=1;change=@{app_arguments='argument'}},
    @{id='arguments-null';expected=1;change=@{app_arguments=$null}},
    @{id='id-number';expected=1;change=@{id=123}},
    @{id='uppercase-id';expected=1;change=@{id='TODO'}},
    @{id='network-path';expected=1;change=@{app_executable='\\server\share\app.exe'}},
    @{id='unsupported-schema';expected=1;change=@{schema_version=2}},
    @{id='invalid-profile-id';expected=1;change=@{id='../other'}},
    @{id='unadmitted';expected=1;change=@{admission='BLOCKED'}},
    @{id='remote-unconfirmed';expected=1;change=@{remote_supported=$false}},
    @{id='hidden-unconfirmed';expected=1;change=@{hidden_native_supported=$false}},
    @{id='unpinned-revision';expected=1;change=@{makepad_revision='dev'}},
    @{id='relative-exe';expected=1;change=@{app_executable='app.exe'}},
    @{id='wrong-app-digest';expected=1;change=@{app_sha256=('0'*64)}},
    @{id='wrong-remote-digest';expected=1;change=@{remote_sha256=('0'*64)}},
    @{id='missing-exe';expected=1;change=@{app_executable=(Join-Path $runDirectory 'missing.exe')}},
    @{id='reserved-argument';expected=1;change=@{app_arguments=@('--stdin-loop')}},
    @{id='non-string-argument';expected=1;change=@{app_arguments=@(123)}}
)
$results=@()
foreach ($case in $cases) {
    $profile=$baseline.Clone()
    foreach ($key in $case.change.Keys) { $profile[$key]=$case.change[$key] }
    $path=Join-Path $runDirectory ($case.id+'.json')
    [IO.File]::WriteAllText($path,($profile | ConvertTo-Json -Depth 8))
    $info=[Diagnostics.ProcessStartInfo]::new((Get-Process -Id $PID).Path)
    $info.UseShellExecute=$false
    $info.CreateNoWindow=$true
    $info.RedirectStandardOutput=$true
    $info.RedirectStandardError=$true
    foreach ($word in @('-NoProfile','-File',$launcher,'-Profile',$path,'-ValidateOnly')) { $info.ArgumentList.Add($word) }
    $child=[Diagnostics.Process]::Start($info)
    $stdout=$child.StandardOutput.ReadToEndAsync()
    $stderr=$child.StandardError.ReadToEndAsync()
    if (-not $child.WaitForExit(15000)) { $child.Kill(); $child.WaitForExit(); throw 'Profile validation timed out.' }
    $outText=$stdout.GetAwaiter().GetResult()
    $errText=$stderr.GetAwaiter().GetResult()
    $passed=$child.ExitCode -eq $case.expected
    if($case.expected -eq 0) {
        try { $passed=$passed -and (($outText|ConvertFrom-Json).status -eq 'VALIDATED') } catch { $passed=$false }
    } else {
        $passed=$passed -and $errText.StartsWith('[MSS] ') -and $errText -notmatch 'ParserError'
    }
    $results+=@{id=$case.id;status=$(if($passed){'PASS'}else{'FAIL'});exit_code=$child.ExitCode;expected=$case.expected;
        stdout=$stdout.GetAwaiter().GetResult();stderr=$stderr.GetAwaiter().GetResult()}
    $child.Dispose()
}
$result=@{launcher_sha256=(Get-FileHash -LiteralPath $launcher -Algorithm SHA256).Hash;
    tests=$results;pass=@($results|Where-Object status -eq 'PASS').Count;fail=@($results|Where-Object status -eq 'FAIL').Count}
[IO.File]::WriteAllText((Join-Path $runDirectory 'results.json'),($result|ConvertTo-Json -Depth 10))
$result | ConvertTo-Json -Depth 10
if($result.fail -gt 0){exit 1}
