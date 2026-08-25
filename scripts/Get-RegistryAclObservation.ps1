[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Root,

    [Parameter(Mandatory = $true)]
    [string]$LogicalRoot,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedOwnerSid,

    [Parameter(Mandatory = $true)]
    [string]$TimeRef,

    [Parameter(Mandatory = $false)]
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$item = Get-Item -LiteralPath $Root -Force
if (-not $item.PSIsContainer) {
    throw "registry ACL target is not a directory"
}

$acl = Get-Acl -LiteralPath $item.FullName
$owner = [System.Security.Principal.NTAccount]::new($acl.Owner).Translate(
    [System.Security.Principal.SecurityIdentifier]
).Value
$systemSid = "S-1-5-18"
$administratorsSid = "S-1-5-32-544"
$allowedSids = @($ExpectedOwnerSid, $systemSid, $administratorsSid)
$rules = @(
    $acl.GetAccessRules(
        $true,
        $true,
        [System.Security.Principal.SecurityIdentifier]
    )
)

$fullControl = [int64][System.Security.AccessControl.FileSystemRights]::FullControl
$requiredFullControl = @()
foreach ($sid in $allowedSids) {
    $allowFull = $false
    $denyAny = $false
    foreach ($rule in $rules) {
        if ($rule.IdentityReference.Value -ne $sid) {
            continue
        }
        $rights = [int64]$rule.FileSystemRights
        if ($rule.AccessControlType -eq [System.Security.AccessControl.AccessControlType]::Deny) {
            if ($rights -ne 0) {
                $denyAny = $true
            }
        }
        elseif (($rights -band $fullControl) -eq $fullControl) {
            $allowFull = $true
        }
    }
    if ($allowFull -and -not $denyAny) {
        $requiredFullControl += $sid
    }
}

$writeMask = [int64]0
foreach ($right in @(
    [System.Security.AccessControl.FileSystemRights]::Write,
    [System.Security.AccessControl.FileSystemRights]::Modify,
    [System.Security.AccessControl.FileSystemRights]::FullControl,
    [System.Security.AccessControl.FileSystemRights]::Delete,
    [System.Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles,
    [System.Security.AccessControl.FileSystemRights]::ChangePermissions,
    [System.Security.AccessControl.FileSystemRights]::TakeOwnership
)) {
    $writeMask = $writeMask -bor [int64]$right
}
$unexpectedWriteSids = @(
    $rules |
        Where-Object {
            $_.AccessControlType -eq [System.Security.AccessControl.AccessControlType]::Allow -and
            ([int64]$_.FileSystemRights -band $writeMask) -ne 0 -and
            $_.IdentityReference.Value -notin $allowedSids
        } |
        ForEach-Object { $_.IdentityReference.Value } |
        Sort-Object -Unique
)

$pathRoot = [System.IO.Path]::GetPathRoot($item.FullName)
if ([string]::IsNullOrWhiteSpace($pathRoot) -or $pathRoot.Length -lt 2) {
    throw "registry ACL volume cannot be resolved"
}
$driveLetter = $pathRoot.Substring(0, 1)
$volume = Get-Volume -DriveLetter $driveLetter
if ([string]::IsNullOrWhiteSpace($volume.FileSystem)) {
    throw "registry ACL filesystem cannot be resolved"
}
$volumeSource = [string]$volume.UniqueId
if ([string]::IsNullOrWhiteSpace($volumeSource)) {
    $volumeSource = "drive:$driveLetter"
}

$sha256 = [System.Security.Cryptography.SHA256]::Create()
try {
    $sddlBytes = [System.Text.Encoding]::UTF8.GetBytes($acl.Sddl)
    $sddlSha256 = [Convert]::ToHexString(
        $sha256.ComputeHash($sddlBytes)
    ).ToLowerInvariant()
    $volumeBytes = [System.Text.Encoding]::UTF8.GetBytes($volumeSource)
    $volumeHash = [Convert]::ToHexString(
        $sha256.ComputeHash($volumeBytes)
    ).ToLowerInvariant()
}
finally {
    $sha256.Dispose()
}

$material = [ordered]@{
    schema = "sedb-ral.registry-acl-observation/0.1"
    observed_root = $LogicalRoot
    owner_sid = $owner
    filesystem = [string]$volume.FileSystem
    volume_identity = "volume:sha256:$volumeHash"
    inheritance_protected = [bool]$acl.AreAccessRulesProtected
    reparse_point = [bool](
        $item.Attributes -band [System.IO.FileAttributes]::ReparsePoint
    )
    required_full_control_sids = @($requiredFullControl)
    forbidden_write_sids = @($unexpectedWriteSids)
    sddl_sha256 = $sddlSha256
    observed_time_ref = $TimeRef
    not_claimed = @(
        "offsite_backup",
        "private_confidentiality",
        "multi_host_security"
    )
}
$materialJson = $material | ConvertTo-Json -Depth 8 -Compress
$pythonCode = @'
import json
import sys
from sedb_ral.canonical import canonical_bytes
from sedb_ral.registry_root_contracts import bind_registry_acl_fingerprint

value = bind_registry_acl_fingerprint(json.load(sys.stdin))
sys.stdout.buffer.write(canonical_bytes(value) + b"\n")
'@
$output = $materialJson | & $PythonExe -c $pythonCode
if ($LASTEXITCODE -ne 0) {
    throw "registry ACL observation binding failed"
}
$output
