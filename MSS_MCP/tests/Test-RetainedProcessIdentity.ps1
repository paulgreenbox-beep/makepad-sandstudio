#requires -Version 7.4
[CmdletBinding()]
param([Parameter(Mandatory)][string]$Launcher,[Parameter(Mandatory)][string]$EvidenceRoot)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$tokens=$null;$parseErrors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Launcher,[ref]$tokens,[ref]$parseErrors)
if($parseErrors.Count){throw 'Launcher syntax failed.'}
foreach($name in @('Initialize-OwnedProcessInterop','Read-OwnedApp','Set-OwnedImage','Wait-OwnedImage','Save-OwnedExitProof')) {
    $definition=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true)
    if($null -eq $definition){throw ('Missing production helper: '+$name)}
    . ([scriptblock]::Create($definition.Extent.Text))
}
Initialize-OwnedProcessInterop
$run=Join-Path $EvidenceRoot ('retained-handle-'+[guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($run)
$results=@{status='FAIL';checks=@();launcher_sha256=(Get-FileHash -LiteralPath $Launcher -Algorithm SHA256).Hash;processes=@()}
function Check([bool]$Value,[string]$Name){if(-not $Value){throw ('Check failed: '+$Name)};$script:results.checks+=@{name=$Name;status='PASS'}}
$app=$null
try {
    $current=[Diagnostics.Process]::GetCurrentProcess()
    try{$currentImage=[MssOwnedProcess]::Image($current.SafeHandle)}finally{$current.Dispose()}
    Check (-not [string]::IsNullOrEmpty($currentImage)) 'current image queried through retained handle'
    $info=[Diagnostics.ProcessStartInfo]::new($currentImage)
    $info.UseShellExecute=$false;$info.CreateNoWindow=$true
    foreach($argument in @('-NoProfile','-NonInteractive','-Command','exit 0')){$info.ArgumentList.Add($argument)}
    $app=[Diagnostics.Process]::Start($info)
    $appHandle=$app.SafeHandle
    $initial=[MssOwnedProcess]::Read($appHandle)
    $birthFileTime=$initial.BirthFileTime
    $appExecutable=$currentImage
    $receipt=@{app_pid=[int]$initial.Pid;app_birth_filetime=$birthFileTime;app_image_expected=$currentImage;app_image=$null;app_image_verified=$false;exit_proof=$null}
    Check ($app.WaitForExit(10000)) 'own fast-exit fixture exited before image readiness check'
    Check (-not (Wait-OwnedImage)) 'exited fixture is not claimed image ready'
    Save-OwnedExitProof
    Check ($receipt.app_image -eq $null -and -not $receipt.app_image_verified) 'unobserved image remains null'
    Check ($receipt.exit_proof.kind -eq 'retained_process_handle' -and $receipt.exit_proof.exit_observed -and $receipt.exit_proof.exit_code -eq 0) 'exit proof comes from same retained handle'
    Check ($receipt.exit_proof.pid -eq $initial.Pid -and $receipt.exit_proof.birth_filetime -eq $initial.BirthFileTime) 'PID and kernel birth preserved after exit'
    $results.processes+=@{pid=[int]$initial.Pid;birth_filetime=$initial.BirthFileTime;expected_image=$currentImage;exit_code=$receipt.app_exit_code;exit_proof=$receipt.exit_proof}
    $oldPid=$receipt.app_pid
    $receipt.app_pid=$oldPid+1
    $rejected=$false
    try{[void](Read-OwnedApp)}catch{$rejected=$_.Exception.Message -match 'identity mismatch'}
    Check $rejected 'foreign or stale PID metadata rejected without signalling'
    $receipt.app_pid=$oldPid
    $before=$receipt.exit_proof|ConvertTo-Json -Compress
    Save-OwnedExitProof
    Check (($receipt.exit_proof|ConvertTo-Json -Compress) -ceq $before) 'repeated proof query is observational and idempotent'
    $results.status='PASS'
} catch {$results.error=$_.Exception.Message}
finally {
    if($app){$app.Dispose()}
    [IO.File]::WriteAllText((Join-Path $run 'results.json'),($results|ConvertTo-Json -Depth 8)+[Environment]::NewLine)
}
@{status=$results.status;evidence=$run;checks=$results.checks.Count}|ConvertTo-Json -Compress
if($results.status -ne 'PASS'){exit 1}
