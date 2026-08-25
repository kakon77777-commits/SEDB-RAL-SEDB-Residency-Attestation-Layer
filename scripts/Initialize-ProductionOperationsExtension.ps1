[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$FinalRoot,
    [Parameter(Mandatory=$true)][string]$PlanFile,
    [Parameter(Mandatory=$true)][string]$AuthorityFile,
    [Parameter(Mandatory=$true)][string]$PreCheckpointFile,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [Parameter(Mandatory=$false)][string]$SyntheticStorageRoot,
    [Parameter(Mandatory=$false)][string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

trap {
    [Console]::Error.WriteLine("production_operations_activation_failed")
    exit 2
}

$exactRoot = "D:\AI_RESIDENCE\REGISTRY\SEDB-RAL"
$exactParent = "D:\AI_RESIDENCE\REGISTRY"
if ($FinalRoot -cne $exactRoot) {
    throw "production operations final root differs"
}

$plan = Get-Content -LiteralPath $PlanFile -Raw -Encoding UTF8 | ConvertFrom-Json
$authority = Get-Content -LiteralPath $AuthorityFile -Raw -Encoding UTF8 | ConvertFrom-Json
$checkpoint = Get-Content -LiteralPath $PreCheckpointFile -Raw -Encoding UTF8 | ConvertFrom-Json
if (
    $plan.final_root -cne $exactRoot -or
    $plan.pre_checkpoint_digest -cne $checkpoint.checkpoint_digest -or
    $authority.operation_plan_digest -cne $plan.plan_digest
) {
    throw "production operations inputs differ"
}

$output = Get-Item -LiteralPath $OutputDirectory -Force
if (-not $output.PSIsContainer) {
    throw "production operations output directory is unavailable"
}

if ([string]::IsNullOrWhiteSpace($SyntheticStorageRoot)) {
    $physicalParent = $exactParent
    $physicalFinal = $exactRoot
    $syntheticArgs = @()
}
else {
    $synthetic = Get-Item -LiteralPath $SyntheticStorageRoot -Force
    if (-not $synthetic.PSIsContainer) {
        throw "synthetic storage root is unavailable"
    }
    $physicalParent = Join-Path $synthetic.FullName "REGISTRY"
    $physicalFinal = Join-Path $physicalParent "SEDB-RAL"
    $syntheticArgs = @("--synthetic-storage-root", $synthetic.FullName)
}

$candidate = Join-Path $physicalParent $plan.candidate_name
$finalExtensions = Join-Path $physicalFinal "extensions"
if ((Test-Path -LiteralPath $candidate) -or (Test-Path -LiteralPath $finalExtensions)) {
    throw "production operations candidate or final extension exists"
}

function Set-ProtectedOperationsAcl {
    param([string]$LiteralPath, [string]$OwnerSid)
    $owner = [System.Security.Principal.SecurityIdentifier]::new($OwnerSid)
    $security = [System.Security.AccessControl.DirectorySecurity]::new()
    $security.SetOwner($owner)
    $security.SetAccessRuleProtection($true, $false)
    $inheritance = (
        [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
        [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
    )
    foreach ($sid in @($OwnerSid, "S-1-5-18", "S-1-5-32-544")) {
        $identity = [System.Security.Principal.SecurityIdentifier]::new($sid)
        $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
            $identity,
            [System.Security.AccessControl.FileSystemRights]::FullControl,
            $inheritance,
            [System.Security.AccessControl.PropagationFlags]::None,
            [System.Security.AccessControl.AccessControlType]::Allow
        )
        [void]$security.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $LiteralPath -AclObject $security
}

[void](New-Item -ItemType Directory -Path $candidate)
Set-ProtectedOperationsAcl -LiteralPath $candidate -OwnerSid $plan.expected_owner_sid
$logicalCandidate = Join-Path $exactParent $plan.candidate_name
$aclObserver = Join-Path $PSScriptRoot "Get-RegistryAclObservation.ps1"
$aclJson = & $aclObserver `
    -Root $candidate `
    -LogicalRoot $logicalCandidate `
    -ExpectedOwnerSid $plan.expected_owner_sid `
    -TimeRef $plan.time_ref `
    -PythonExe $PythonExe
if ($LASTEXITCODE -ne 0) {
    throw "production operations ACL observation failed"
}
$aclPath = Join-Path $output.FullName "candidate-acl.json"
[System.IO.File]::WriteAllText(
    $aclPath,
    [string]::Join("`n", @($aclJson)),
    [System.Text.UTF8Encoding]::new($false)
)

$entry = "from sedb_ral.cli import entrypoint; entrypoint()"
$verificationPath = Join-Path $output.FullName "candidate-verification.json"
& $PythonExe -c $entry registry operations-extension-prepare `
    $PlanFile $AuthorityFile $aclPath `
    --output $verificationPath @syntheticArgs | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "production operations candidate preparation failed"
}

$candidateExtensions = Join-Path $candidate "extensions"
Set-ProtectedOperationsAcl `
    -LiteralPath $candidateExtensions `
    -OwnerSid $plan.expected_owner_sid
$candidateExtensionsAclJson = & $aclObserver `
    -Root $candidateExtensions `
    -LogicalRoot "$exactRoot\extensions" `
    -ExpectedOwnerSid $plan.expected_owner_sid `
    -TimeRef $plan.time_ref `
    -PythonExe $PythonExe
if ($LASTEXITCODE -ne 0) {
    throw "production operations candidate extensions ACL observation failed"
}
$candidateExtensionsAcl = $candidateExtensionsAclJson | ConvertFrom-Json
if (
    -not $candidateExtensionsAcl.inheritance_protected -or
    @($candidateExtensionsAcl.forbidden_write_sids).Count -ne 0 -or
    $candidateExtensionsAcl.acl_fingerprint -cne $plan.acl_fingerprint
) {
    throw "production operations candidate extensions ACL differs"
}
$candidateExtensionsAclPath = Join-Path $output.FullName "candidate-extensions-acl.json"
[System.IO.File]::WriteAllText(
    $candidateExtensionsAclPath,
    [string]::Join("`n", @($candidateExtensionsAclJson)),
    [System.Text.UTF8Encoding]::new($false)
)

$publishCode = @'
import json
import sys
from pathlib import Path
from sedb_ral.production_operations_layout import publish_production_operations_candidate, write_activation_receipt
from sedb_ral.registry_root import RegistryStorage

plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
verification = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
synthetic = sys.argv[3]
storage = RegistryStorage.synthetic(Path(synthetic)) if synthetic else None
publication = publish_production_operations_candidate(plan, verification, storage=storage)
root = storage.final if storage else Path(r"D:\AI_RESIDENCE\REGISTRY\SEDB-RAL")
index = json.loads((root / "extensions/index/00000000000000000000.json").read_text(encoding="utf-8"))
receipt = write_activation_receipt(root=root, plan=plan, index=index, observed_time_ref=plan["time_ref"])
print(json.dumps({"publication": publication, "activation_receipt": receipt}, sort_keys=True, separators=(",", ":")))
'@
$publishPath = Join-Path $output.FullName "publication.json"
$syntheticValue = if ([string]::IsNullOrWhiteSpace($SyntheticStorageRoot)) { "" } else { $SyntheticStorageRoot }
$published = & $PythonExe -c $publishCode $PlanFile $verificationPath $syntheticValue
if ($LASTEXITCODE -ne 0) {
    throw "production operations publication failed"
}
[System.IO.File]::WriteAllText(
    $publishPath,
    [string]::Join("`n", @($published)),
    [System.Text.UTF8Encoding]::new($false)
)

$finalExtensionsAclJson = & $aclObserver `
    -Root $finalExtensions `
    -LogicalRoot "$exactRoot\extensions" `
    -ExpectedOwnerSid $plan.expected_owner_sid `
    -TimeRef $plan.time_ref `
    -PythonExe $PythonExe
if ($LASTEXITCODE -ne 0) {
    throw "production operations final extensions ACL observation failed"
}
$finalExtensionsAcl = $finalExtensionsAclJson | ConvertFrom-Json
if (
    -not $finalExtensionsAcl.inheritance_protected -or
    @($finalExtensionsAcl.forbidden_write_sids).Count -ne 0 -or
    $finalExtensionsAcl.acl_fingerprint -cne $plan.acl_fingerprint
) {
    throw "production operations final extensions ACL differs"
}
$finalExtensionsAclPath = Join-Path $output.FullName "final-extensions-acl.json"
[System.IO.File]::WriteAllText(
    $finalExtensionsAclPath,
    [string]::Join("`n", @($finalExtensionsAclJson)),
    [System.Text.UTF8Encoding]::new($false)
)

$statusPath = Join-Path $output.FullName "status.json"
& $PythonExe -c $entry registry operations-extension-status `
    --output $statusPath @syntheticArgs | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "production operations final status failed"
}
Get-Content -LiteralPath $statusPath -Raw -Encoding UTF8
