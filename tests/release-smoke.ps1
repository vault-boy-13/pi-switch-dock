# SPDX-License-Identifier: GPL-2.0-only
# Run each case in a fresh Windows PowerShell process. Git/GitHub are mocked;
# Python, the archive, manifest and checksums are real. No network mutations.
param([ValidateSet('draft','candidate','promote','mismatch')][string]$Case='draft')
$ErrorActionPreference='Stop'
$global:ReleaseSmoke=@{
    Case=$Case; Created=$false; Exposed=$false; Promoted=$false; Tagged=$false
    Root=(Split-Path -Parent $PSScriptRoot)
}
function git {
    $global:LASTEXITCODE=0
    switch ($args[0]) {
        'remote' { 'https://github.com/vault-boy-13/pi-switch-dock.git' }
        'branch' { 'main' }
        'status' { }
        'rev-parse' { 'abcdef' }
        'ls-remote' { if($args[1] -eq '--heads'){ "abcdef`trefs/heads/main" } }
        'tag' { if($args[1] -eq '-a'){ $global:ReleaseSmoke.Tagged=$true } }
        'push' { if(-not $global:ReleaseSmoke.Tagged){throw 'Push before tag'} }
        default { throw "Unexpected git arguments: $args" }
    }
}
function gh {
    $global:LASTEXITCODE=0
    if($args[0] -eq 'auth'){return}
    switch($args[1]) {
        'list' { '[]' }
        'create' {
            if('--draft' -notin $args -or '--prerelease' -notin $args){throw 'Must create draft prerelease'}
            foreach($asset in $args[3..4]){ if(-not(Test-Path -LiteralPath $asset)){throw 'Missing asset'} }
            $global:ReleaseSmoke.Created=$true
        }
        'download' {
            $directory=$args[[array]::IndexOf($args,'--dir')+1]
            foreach($name in @('pi-switch-dock-tools.tar.gz','SHA256SUMS')){
                Copy-Item -LiteralPath (Join-Path $global:ReleaseSmoke.Root "dist/$name") -Destination $directory
            }
            if($global:ReleaseSmoke.Case -eq 'mismatch'){
                Set-Content -LiteralPath (Join-Path $directory 'SHA256SUMS') -Value 'wrong'
            }
        }
        'edit' {
            if('--prerelease=false' -in $args){
                if($global:ReleaseSmoke.Case -eq 'mismatch'){throw 'Promoted mismatched assets'}
                $global:ReleaseSmoke.Promoted=$true
            }elseif('--draft=false' -in $args){$global:ReleaseSmoke.Exposed=$true}
            else{throw 'Unexpected release edit'}
        }
        'view' {
            $promoting=$global:ReleaseSmoke.Case -in @('promote','mismatch')
            @{
                tagName='v0.7.23'
                isDraft=(-not $promoting -and -not $global:ReleaseSmoke.Exposed)
                isPrerelease=(-not $global:ReleaseSmoke.Promoted)
                assets=@(@{name='SHA256SUMS'},@{name='pi-switch-dock-tools.tar.gz'})
            } | ConvertTo-Json -Depth 4
        }
        default{throw "Unexpected gh arguments: $args"}
    }
}
$scriptPath=Join-Path $global:ReleaseSmoke.Root 'release.ps1'
switch($Case){
    'draft' { & $scriptPath }
    'candidate' { & $scriptPath -Candidate }
    default { & $scriptPath -Publish }
}
$result=$LASTEXITCODE
if($Case -eq 'mismatch'){
    if($result -ne 1 -or $global:ReleaseSmoke.Promoted){throw 'Mismatch was not safely rejected'}
}else{
    if($result -ne 0){throw 'Release script failed'}
    if($Case -eq 'promote'){
        if(-not $global:ReleaseSmoke.Promoted -or $global:ReleaseSmoke.Created -or $global:ReleaseSmoke.Tagged){throw 'Promotion changed tag/assets'}
    }else{
        if(-not $global:ReleaseSmoke.Created -or -not $global:ReleaseSmoke.Tagged){throw 'Creation incomplete'}
        if(($Case -eq 'candidate') -ne $global:ReleaseSmoke.Exposed){throw 'Candidate exposure incorrect'}
    }
}
Write-Output "PASS: $Case"
