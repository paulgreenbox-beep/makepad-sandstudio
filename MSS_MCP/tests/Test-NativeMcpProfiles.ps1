#requires -Version 7.4
[CmdletBinding()]
param([Parameter(Mandatory)][string]$TodoProfile,[Parameter(Mandatory)][string]$CounterProfile,
    [Parameter(Mandatory)][string]$EvidenceRoot,[switch]$DisconnectOnly)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$launcher=Join-Path $PSScriptRoot '../tools/Start-MakepadMcp.ps1'
$run=Join-Path $EvidenceRoot ('generic-mcp-e2e-'+[Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($run)
$sessions=@()
$report=@{status='FAIL';error=$null;checks=@();sessions=@();launcher_sha256=(Get-FileHash -LiteralPath $launcher).Hash}
function Assert-Check([bool]$Condition,[string]$Name) {
    if(-not $Condition){throw ('Assertion failed: '+$Name)}
    $script:report.checks+=@{name=$Name;status='PASS'}
}
function Send-Rpc($Session,[string]$Method,$Parameters) {
    $Session.Sequence++
    $message=@{jsonrpc='2.0';id=$Session.Sequence;method=$Method;params=$Parameters}|ConvertTo-Json -Depth 12 -Compress
    $Session.Process.StandardInput.WriteLine($message)
    $Session.Process.StandardInput.Flush()
    $task=$Session.Process.StandardOutput.ReadLineAsync()
    if(-not $task.Wait(45000)){throw ('MCP reply timeout: '+$Method)}
    if(-not $task.Result){throw ('MCP EOF: '+$Method+' '+$Session.Errors.GetAwaiter().GetResult())}
    $answer=$task.Result|ConvertFrom-Json -AsHashtable
    if($answer.id -ne $Session.Sequence -or $answer.ContainsKey('error')){throw ('MCP rejected '+$Method+': '+$task.Result)}
    return $answer.result
}
function Call-Tool($Session,[string]$Name,$Arguments) {
    $result=Send-Rpc $Session 'tools/call' @{name=$Name;arguments=$Arguments}
    if($result.isError){throw ('Tool failed: '+$Name+' '+($result.content|Where-Object type -eq 'text'|ForEach-Object text))}
    return $result
}
function Read-TextResult($Result) { return (($Result.content|Where-Object type -eq 'text'|ForEach-Object text) -join [Environment]::NewLine) }
function Read-Tree($Session) {
    return (Read-TextResult (Call-Tool $Session 'ui__ui' @{json=$true}))|ConvertFrom-Json -AsHashtable
}
function Find-Node($Tree,[string]$Suffix) {
    $nodes=@($Tree.trees[0].nodes|Where-Object {$_.path -eq $Suffix -or $_.path.EndsWith('.'+$Suffix)})
    if($nodes.Count -ne 1){throw ('Expected unique semantic node: '+$Suffix)}
    return $nodes[0]
}
function Start-Session([string]$Path) {
    $info=[Diagnostics.ProcessStartInfo]::new((Get-Process -Id $PID).Path)
    $info.UseShellExecute=$false;$info.CreateNoWindow=$true
    $info.RedirectStandardInput=$true;$info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
    $info.StandardInputEncoding=[Text.UTF8Encoding]::new($false)
    $info.StandardOutputEncoding=[Text.UTF8Encoding]::new($false)
    $info.StandardErrorEncoding=[Text.UTF8Encoding]::new($false)
    foreach($word in @('-NoProfile','-File',$launcher,'-Profile',$Path)){$info.ArgumentList.Add($word)}
    $process=[Diagnostics.Process]::Start($info)
    $session=@{Process=$process;Errors=$process.StandardError.ReadToEndAsync();Sequence=0;Profile=$Path;Receipt=$null;ExpectedExit=0}
    $script:sessions+=,$session
    $init=Send-Rpc $session 'initialize' @{protocolVersion='2025-06-18';capabilities=@{};clientInfo=@{name='MSS-native-profile-test';version='1'}}
    Assert-Check ($init.protocolVersion -eq '2025-06-18') 'native MCP initialize'
    $tools=Send-Rpc $session 'tools/list' @{}
    Assert-Check (@($tools.tools|Where-Object name -eq 'ui__grab').Count -eq 1) 'native MCP tool catalog'
    $status=(Read-TextResult (Call-Tool $session 'ui__status' @{}))|ConvertFrom-Json -AsHashtable
    $session.AppPid=$status.pid
    $profile=Get-Content -LiteralPath $Path -Raw|ConvertFrom-Json -AsHashtable
    $found=@(Get-ChildItem -LiteralPath $profile.session_root -Filter 'session.json' -File -Recurse|
        Where-Object {((Get-Content -LiteralPath $_.FullName -Raw|ConvertFrom-Json -AsHashtable).app_pid) -eq $status.pid})
    Assert-Check ($found.Count -eq 1) 'status belongs to launcher receipt'
    $session.Receipt=$found[0].FullName
    return $session
}
function Capture-Native($Session) {
    $capture=Call-Tool $Session 'ui__grab' @{}
    $image=@($capture.content|Where-Object type -eq 'image')
    Assert-Check ($image.Count -eq 1) 'real MCP image returned'
    $bytes=[Convert]::FromBase64String($image[0].data)
    Assert-Check ($bytes.Length -gt 24 -and [Convert]::ToHexString($bytes[0..7]) -eq '89504E470D0A1A0A') 'native PNG bytes'
    $metadata=(Read-TextResult $capture)|ConvertFrom-Json -AsHashtable
    Assert-Check ([Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)) -ceq (Get-FileHash -LiteralPath $metadata.png).Hash) 'MCP image bytes match native PNG file'
    Assert-Check ($metadata.capture_kind -eq 'pixels' -and $metadata.sz[0] -gt 0 -and $metadata.sz[1] -gt 0) 'pixel capture metadata'
    return @{png=$metadata.png;sha256=(Get-FileHash -LiteralPath $metadata.png).Hash;dimensions=$metadata.sz}
}
try {
    $todo=Start-Session $TodoProfile
    if($DisconnectOnly) {
        $todo.ExpectedExit=1
        $todo.Process.StandardOutput.Close()
        $todo.Sequence++
        $message=@{jsonrpc='2.0';id=$todo.Sequence;method='tools/call';params=@{name='ui__status';arguments=@{}}}|ConvertTo-Json -Depth 8 -Compress
        $todo.Process.StandardInput.WriteLine($message)
        $todo.Process.StandardInput.Flush()
        Assert-Check ($todo.Process.WaitForExit(15000)) 'closed output triggers cleanup while client stdin remains open'
        Assert-Check ($todo.Process.ExitCode -eq 1) 'lost transport is not PASS'
        $receipt=Get-Content -LiteralPath $todo.Receipt -Raw|ConvertFrom-Json -AsHashtable
        Assert-Check ($receipt.error -match 'output transport lost') 'transport failure retained in receipt'
    } else {
    $counter=Start-Session $CounterProfile
    Assert-Check ($todo.AppPid -ne $counter.AppPid) 'independent app processes'
    Assert-Check ((Split-Path $todo.Receipt) -ne (Split-Path $counter.Receipt)) 'separate session directories'
    $counterBefore=Read-Tree $counter
    Assert-Check ((Find-Node $counterBefore 'counter_label').name -eq 'Count: 0') 'counter initial state'
    $tree=Read-Tree $todo
    $input=Find-Node $tree 'todo_input'
    Assert-Check ($input.actions -match 'set_value') 'Todo declares semantic set_value'
    $marker='MSS Универсальный ✓'
    $activity=(Read-TextResult (Call-Tool $todo 'ui__activity' @{}))|ConvertFrom-Json -AsHashtable
    [void](Call-Tool $todo 'ui__ui_act' @{node=$input.id;w=$tree.trees[0].window;action='set_value';v=$marker;wait=$true;if_user_seq=$activity.user_seq})
    Assert-Check ((Find-Node (Read-Tree $todo) 'todo_input').value -eq $marker) 'Todo independent value readback'
    $tree=Read-Tree $todo
    $add=Find-Node $tree 'add_button'
    [void](Call-Tool $todo 'ui__ui_act' @{node=$add.id;w=$tree.trees[0].window;action='press';wait=$true;if_user_seq=$activity.user_seq})
    $todoAfter=Read-Tree $todo
    Assert-Check ((Find-Node $todoAfter 'todo_input').value -eq '') 'Todo input cleared after Add'
    Assert-Check (@($todoAfter.trees[0].nodes|Where-Object {$_.role -eq 'static_text' -and $_.name -eq $marker}).Count -eq 1) 'Todo task appears exactly once'
    Assert-Check ((Find-Node $todoAfter 'status').name -eq '1 remaining / 2 total') 'Todo status postcondition'
    Assert-Check ((Find-Node (Read-Tree $counter) 'counter_label').name -eq 'Count: 0') 'Todo action leaves counter unchanged'
    $tree=Read-Tree $counter
    $button=Find-Node $tree 'increment_button'
    $activity=(Read-TextResult (Call-Tool $counter 'ui__activity' @{}))|ConvertFrom-Json -AsHashtable
    [void](Call-Tool $counter 'ui__ui_act' @{node=$button.id;w=$tree.trees[0].window;action='press';wait=$true;if_user_seq=$activity.user_seq})
    Assert-Check ((Find-Node (Read-Tree $counter) 'counter_label').name -eq 'Count: 1') 'Counter independent postcondition'
    Assert-Check ((Find-Node (Read-Tree $todo) 'status').name -eq '1 remaining / 2 total') 'Counter action leaves Todo unchanged'
    $report.todo_capture=Capture-Native $todo
    $report.counter_capture=Capture-Native $counter
    }
    $report.status='PASS'
} catch {
    $report.error=$_.Exception.Message
    [Console]::Error.WriteLine($report.error)
} finally {
    foreach($session in $sessions) {
        $session.Process.StandardInput.Close()
        if(-not $session.Process.WaitForExit(45000)){
            $report.status='FAIL';$report.error='Launcher EOF cleanup did not finish; ownership receipts preserved.'
        } else {
            $sessionResult=@{profile=$session.Profile;launcher_exit_code=$session.Process.ExitCode;stderr=$session.Errors.GetAwaiter().GetResult()}
            if($session.Receipt){
                $receipt=Get-Content -LiteralPath $session.Receipt -Raw|ConvertFrom-Json -AsHashtable
                $sessionResult.receipt=$session.Receipt;$sessionResult.cleanup=$receipt.cleanup;$sessionResult.app_exit_code=$receipt.app_exit_code
                if($session.Process.ExitCode -ne $session.ExpectedExit -or $receipt.cleanup -ne 'GRACEFUL' -or $receipt.app_exit_code -ne 0){$report.status='FAIL'}
            } else { $report.status='FAIL' }
            $report.sessions+=,$sessionResult
        }
    }
    $report.test_sha256=(Get-FileHash -LiteralPath $PSCommandPath).Hash
    [IO.File]::WriteAllText((Join-Path $run 'results.json'),($report|ConvertTo-Json -Depth 12))
}
@{status=$report.status;checks=$report.checks.Count;report=(Join-Path $run 'results.json');error=$report.error}|ConvertTo-Json -Compress
if($report.status -ne 'PASS'){exit 1}
