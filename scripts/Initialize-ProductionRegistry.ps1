[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$FinalRoot,

    [Parameter(Mandatory = $true)]
    [string]$PlanFile,

    [Parameter(Mandatory = $true)]
    [string]$AuthorityFile,

    [Parameter(Mandatory = $true)]
    [string]$TimeReceiptFile,

    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,

    [Parameter(Mandatory = $false)]
    [string]$SyntheticStorageRoot,

    [Parameter(Mandatory = $false)]
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

trap {
    try {
        if (
            -not [string]::IsNullOrWhiteSpace($OutputDirectory) -and
            (Test-Path -LiteralPath $OutputDirectory -PathType Container)
        ) {
            $failurePath = Join-Path $OutputDirectory "failure.json"
            if (-not (Test-Path -LiteralPath $failurePath)) {
                $failure = [ordered]@{
                    schema = "sedb-ral.registry-initialization-failure/0.1"
                    status = "failed"
                    error_code = "registry_initialization_failed"
                    final_root = "D:\AI_RESIDENCE\REGISTRY\SEDB-RAL"
                    cleanup_performed = $false
                    not_claimed = @(
                        "resident_registration",
                        "private_access",
                        "root_deletion"
                    )
                }
                $json = $failure | ConvertTo-Json -Depth 5 -Compress
                $encoding = [System.Text.UTF8Encoding]::new($false)
                $stream = [System.IO.File]::Open(
                    $failurePath,
                    [System.IO.FileMode]::CreateNew,
                    [System.IO.FileAccess]::Write,
                    [System.IO.FileShare]::None
                )
                try {
                    $bytes = $encoding.GetBytes($json)
                    $stream.Write($bytes, 0, $bytes.Length)
                }
                finally {
                    $stream.Dispose()
                }
            }
        }
    }
    catch {
    }
    [Console]::Error.WriteLine("registry_initialization_failed")
    exit 2
}

$exactFinalRoot = "D:\AI_RESIDENCE\REGISTRY\SEDB-RAL"
$exactParentRoot = "D:\AI_RESIDENCE\REGISTRY"
if ($FinalRoot -cne $exactFinalRoot) {
    throw "registry final root differs from the exact authorized target"
}

$plan = Get-Content -LiteralPath $PlanFile -Raw -Encoding UTF8 | ConvertFrom-Json
$authority = Get-Content -LiteralPath $AuthorityFile -Raw -Encoding UTF8 | ConvertFrom-Json
$timeReceipt = Get-Content -LiteralPath $TimeReceiptFile -Raw -Encoding UTF8 | ConvertFrom-Json
if ($plan.final_root -cne $exactFinalRoot -or $plan.registry_parent -cne $exactParentRoot) {
    throw "registry plan target differs"
}
if ($authority.operation_plan_digest -cne $plan.plan_digest) {
    throw "registry authority binds another plan"
}
if ($timeReceipt.time_ref -cne $plan.time_ref) {
    throw "registry temporal receipt binds another plan"
}
if ($plan.candidate_name -notmatch '^\.SEDB-RAL\.init-[0-9a-f-]{36}$') {
    throw "registry candidate name is invalid"
}

$outputItem = Get-Item -LiteralPath $OutputDirectory -Force
if (-not $outputItem.PSIsContainer) {
    throw "registry output location is not a directory"
}
if ([System.IO.Directory]::GetFileSystemEntries($outputItem.FullName).Count -ne 0) {
    throw "registry output location must be empty"
}

if ([string]::IsNullOrWhiteSpace($SyntheticStorageRoot)) {
    $physicalParent = $exactParentRoot
    $physicalFinal = $exactFinalRoot
    $syntheticArguments = @()
}
else {
    $syntheticItem = Get-Item -LiteralPath $SyntheticStorageRoot -Force
    if (-not $syntheticItem.PSIsContainer) {
        throw "synthetic storage root is not a directory"
    }
    $physicalParent = Join-Path $syntheticItem.FullName "REGISTRY"
    $physicalFinal = Join-Path $physicalParent "SEDB-RAL"
    $syntheticArguments = @("--synthetic-storage-root", $syntheticItem.FullName)
}
$physicalCandidate = Join-Path $physicalParent $plan.candidate_name
if (
    (Test-Path -LiteralPath $physicalParent) -or
    (Test-Path -LiteralPath $physicalFinal) -or
    (Test-Path -LiteralPath $physicalCandidate)
) {
    throw "registry target or candidate already exists"
}

function Set-RegistryProtectedAcl {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LiteralPath,

        [Parameter(Mandatory = $true)]
        [string]$OwnerSid
    )

    $owner = [System.Security.Principal.SecurityIdentifier]::new($OwnerSid)
    $security = [System.Security.AccessControl.DirectorySecurity]::new()
    $security.SetOwner($owner)
    $security.SetAccessRuleProtection($true, $false)
    $inheritance = (
        [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
        [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
    )
    $propagation = [System.Security.AccessControl.PropagationFlags]::None
    foreach ($sid in @($OwnerSid, "S-1-5-18", "S-1-5-32-544")) {
        $identity = [System.Security.Principal.SecurityIdentifier]::new($sid)
        $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
            $identity,
            [System.Security.AccessControl.FileSystemRights]::FullControl,
            $inheritance,
            $propagation,
            [System.Security.AccessControl.AccessControlType]::Allow
        )
        [void]$security.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $LiteralPath -AclObject $security
}

function Write-Utf8New {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LiteralPath,

        [Parameter(Mandatory = $true)]
        [string]$Content
    )

    $encoding = [System.Text.UTF8Encoding]::new($false)
    $stream = [System.IO.File]::Open(
        $LiteralPath,
        [System.IO.FileMode]::CreateNew,
        [System.IO.FileAccess]::Write,
        [System.IO.FileShare]::None
    )
    try {
        $writer = [System.IO.StreamWriter]::new($stream, $encoding)
        try {
            $writer.Write($Content)
        }
        finally {
            $writer.Dispose()
        }
    }
    finally {
        $stream.Dispose()
    }
}

function Get-ObservedAclJson {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PhysicalRoot,

        [Parameter(Mandatory = $true)]
        [string]$LogicalRoot
    )

    $observer = Join-Path $PSScriptRoot "Get-RegistryAclObservation.ps1"
    $json = & $observer `
        -Root $PhysicalRoot `
        -LogicalRoot $LogicalRoot `
        -ExpectedOwnerSid $plan.expected_owner_sid `
        -TimeRef $plan.time_ref `
        -PythonExe $PythonExe
    if ($LASTEXITCODE -ne 0) {
        throw "registry ACL observation failed"
    }
    return [string]::Join("`n", @($json))
}

function Assert-ProtectedAcl {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Json
    )

    $observation = $Json | ConvertFrom-Json
    $required = @(
        $plan.expected_owner_sid,
        "S-1-5-18",
        "S-1-5-32-544"
    )
    if (
        -not $observation.inheritance_protected -or
        $observation.reparse_point -or
        $observation.owner_sid -cne $plan.expected_owner_sid -or
        $observation.filesystem -cne $plan.filesystem -or
        $observation.volume_identity -cne $plan.volume_identity -or
        @($observation.forbidden_write_sids).Count -ne 0 -or
        @($observation.required_full_control_sids).Count -ne 3
    ) {
        throw "registry ACL does not meet the protected boundary"
    }
    foreach ($sid in $required) {
        if ($sid -notin @($observation.required_full_control_sids)) {
            throw "registry ACL is missing required access"
        }
    }
}

[void](New-Item -ItemType Directory -Path $physicalParent)
Set-RegistryProtectedAcl -LiteralPath $physicalParent -OwnerSid $plan.expected_owner_sid
$parentAclJson = Get-ObservedAclJson `
    -PhysicalRoot $physicalParent `
    -LogicalRoot $exactParentRoot
Assert-ProtectedAcl -Json $parentAclJson
$parentAclPath = Join-Path $outputItem.FullName "parent-acl.json"
Write-Utf8New -LiteralPath $parentAclPath -Content $parentAclJson

[void](New-Item -ItemType Directory -Path $physicalCandidate)
Set-RegistryProtectedAcl -LiteralPath $physicalCandidate -OwnerSid $plan.expected_owner_sid
$candidateAclJson = Get-ObservedAclJson `
    -PhysicalRoot $physicalCandidate `
    -LogicalRoot $plan.candidate_root
Assert-ProtectedAcl -Json $candidateAclJson
$candidateAclPath = Join-Path $outputItem.FullName "candidate-acl.json"
Write-Utf8New -LiteralPath $candidateAclPath -Content $candidateAclJson

$pythonEntry = "from sedb_ral.cli import entrypoint; entrypoint()"
$preparePath = Join-Path $outputItem.FullName "prepare-result.json"
& $PythonExe -c $pythonEntry registry prepare-root `
    $PlanFile $AuthorityFile $parentAclPath $candidateAclPath `
    --output $preparePath @syntheticArguments | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "registry candidate preparation failed"
}

$verificationPath = Join-Path $outputItem.FullName "verification.json"
& $PythonExe -c $pythonEntry registry verify-root `
    $PlanFile $AuthorityFile $parentAclPath $candidateAclPath `
    --output $verificationPath @syntheticArguments | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "registry candidate verification failed"
}

$publicationPath = Join-Path $outputItem.FullName "publication.json"
& $PythonExe -c $pythonEntry registry publish-root `
    $PlanFile $verificationPath `
    --output $publicationPath @syntheticArguments | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "registry candidate publication failed"
}

$finalAclJson = Get-ObservedAclJson `
    -PhysicalRoot $physicalFinal `
    -LogicalRoot $exactFinalRoot
Assert-ProtectedAcl -Json $finalAclJson
$finalAclPath = Join-Path $outputItem.FullName "final-acl.json"
Write-Utf8New -LiteralPath $finalAclPath -Content $finalAclJson

$statusPath = Join-Path $outputItem.FullName "status.json"
& $PythonExe -c $pythonEntry registry root-status `
    --expected-plan-digest $plan.plan_digest `
    --output $statusPath @syntheticArguments | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "published registry status verification failed"
}
Get-Content -LiteralPath $statusPath -Raw -Encoding UTF8
