#!/usr/bin/env pwsh
[CmdletBinding()]
param(
    # Publish immediately after creating and verifying the draft release.
    [switch]$Publish
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Repo = 'vault-boy-13/pi-switch-dock'
$Root = $PSScriptRoot
$SpecPath = Join-Path $Root 'release-spec.json'
$ArchivePath = Join-Path $Root 'dist/pi-switch-dock-tools.tar.gz'
$ChecksumsPath = Join-Path $Root 'dist/SHA256SUMS'

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments, [string]$Action)
    $output = & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Action failed (exit code $LASTEXITCODE)."
    }
    return $output
}

try {
    foreach ($command in @('git', 'gh', 'python')) {
        if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
            throw "Required command not found: $command"
        }
    }

    if (-not (Test-Path -LiteralPath $SpecPath -PathType Leaf)) {
        throw 'release-spec.json is missing.'
    }
    if (-not (Test-Path -LiteralPath $ArchivePath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $ChecksumsPath -PathType Leaf)) {
        throw 'Build the validated release assets first; dist archive or SHA256SUMS is missing.'
    }

    $spec = Get-Content -LiteralPath $SpecPath -Raw | ConvertFrom-Json
    $tag = [string]$spec.version
    if ($tag -notmatch '^v\d+\.\d+\.\d+$' -or $tag -cne [string]$spec.upstream_tag) {
        throw 'release-spec.json must use matching vMAJOR.MINOR.PATCH version and upstream_tag values.'
    }

    $actualHash = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $sumLines = @(Get-Content -LiteralPath $ChecksumsPath | Where-Object { $_.Trim() })
    if ($sumLines.Count -ne 1 -or
        $sumLines[0] -notmatch '^([0-9a-fA-F]{64})\s+\*?pi-switch-dock-tools\.tar\.gz$' -or
        $Matches[1].ToLowerInvariant() -cne $actualHash) {
        throw 'SHA256SUMS does not match the release archive.'
    }

    # Send code through stdin: Windows PowerShell 5.1 strips embedded quotes
    # when passing Python code through a native command's -c argument.
    $manifestCode = @'
import sys, tarfile
with tarfile.open(sys.argv[1], 'r:gz') as archive:
    print(archive.extractfile('release.json').read().decode('utf-8'))
'@
    $manifestOutput = $manifestCode | & python - $ArchivePath
    if ($LASTEXITCODE -ne 0) {
        throw "Reading release bundle manifest failed (exit code $LASTEXITCODE)."
    }
    $manifest = ($manifestOutput -join "`n") | ConvertFrom-Json
    if ($manifest.version -cne $tag -or $manifest.upstream_tag -cne [string]$spec.upstream_tag -or
        $manifest.upstream_sha256 -cne [string]$spec.upstream_sha256) {
        throw 'Release bundle metadata does not match release-spec.json.'
    }

    $null = Invoke-Checked 'gh' @('auth', 'status', '--hostname', 'github.com') 'GitHub authentication check'

    $remote = [string](Invoke-Checked 'git' @('remote', 'get-url', 'origin') 'Reading origin URL')
    if ($remote.Trim() -notmatch '(?i)github\.com[:/]vault-boy-13/pi-switch-dock(?:\.git)?$') {
        throw "origin must point to https://github.com/$Repo or git@github.com:$Repo.git."
    }

    $branch = [string](Invoke-Checked 'git' @('branch', '--show-current') 'Reading current branch')
    if ([string]::IsNullOrWhiteSpace($branch)) {
        throw 'Checkout is detached; switch to the release branch first.'
    }
    $dirty = @(& git status --porcelain --untracked-files=all)
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect Git working tree.' }
    if ($dirty.Count -gt 0) {
        throw 'Git working tree is not clean. Commit and push the release changes first.'
    }

    $head = [string](Invoke-Checked 'git' @('rev-parse', 'HEAD') 'Reading HEAD')
    $upstream = [string](Invoke-Checked 'git' @('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}') 'Reading branch upstream')
    $upstreamHead = [string](Invoke-Checked 'git' @('rev-parse', $upstream) 'Reading pushed branch')
    if ($head.Trim() -cne $upstreamHead.Trim()) {
        throw 'Current commit differs from its pushed upstream branch. Push the branch and retry.'
    }

    $existingLocalTag = & git show-ref --verify --quiet "refs/tags/$tag"
    if ($LASTEXITCODE -eq 0) { throw "Local tag $tag already exists; refusing to overwrite it." }
    $existingRemoteTag = Invoke-Checked 'git' @('ls-remote', '--tags', 'origin', "refs/tags/$tag", "refs/tags/$tag^{}") 'Checking remote tag'
    if (@($existingRemoteTag).Count -gt 0) { throw "Remote tag $tag already exists; refusing to overwrite it." }

    # Fail early if a release with this tag already exists. The tag check above
    # also prevents replacing published releases or their assets.
    $priorRelease = & gh release view $tag --repo $Repo --json tagName 2>$null
    if ($LASTEXITCODE -eq 0) { throw "A GitHub Release for $tag already exists; refusing to replace it." }

    Write-Host "Release: $tag"
    Write-Host "Archive SHA256: $actualHash"
    Write-Host "Branch commit: $($head.Trim())"
    Write-Host 'Creating and pushing annotated tag...'
    $null = Invoke-Checked 'git' @('tag', '-a', $tag, '-m', "pi-switch-dock $tag") 'Creating annotated tag'
    $null = Invoke-Checked 'git' @('push', 'origin', $tag) 'Pushing release tag'

    $notes = "Switch Frame Tap $tag support for Raspberry Pi OS Trixie (ARM64)."
    $null = Invoke-Checked 'gh' @(
        'release', 'create', $tag, $ArchivePath, $ChecksumsPath,
        '--repo', $Repo, '--title', "pi-switch-dock $tag", '--notes', $notes,
        '--draft', '--verify-tag'
    ) 'Creating draft GitHub Release'

    $releaseJson = Invoke-Checked 'gh' @(
        'release', 'view', $tag, '--repo', $Repo,
        '--json', 'tagName,isDraft,isPrerelease,assets'
    ) 'Verifying draft GitHub Release'
    $release = ($releaseJson -join "`n") | ConvertFrom-Json
    $expectedAssets = @('SHA256SUMS', 'pi-switch-dock-tools.tar.gz')
    $actualAssets = @($release.assets | ForEach-Object { [string]$_.name } | Sort-Object)
    if ($release.tagName -cne $tag -or -not $release.isDraft -or $release.isPrerelease -or
        (Compare-Object $expectedAssets $actualAssets)) {
        throw 'Draft release verification failed. Inspect it on GitHub; no existing release was overwritten.'
    }

    if ($Publish) {
        Write-Host 'Publishing stable release...'
        $null = Invoke-Checked 'gh' @('release', 'edit', $tag, '--repo', $Repo, '--draft=false', '--verify-tag') 'Publishing GitHub Release'
        $publishedJson = Invoke-Checked 'gh' @(
            'release', 'view', $tag, '--repo', $Repo,
            '--json', 'tagName,isDraft,isPrerelease,assets'
        ) 'Verifying published GitHub Release'
        $published = ($publishedJson -join "`n") | ConvertFrom-Json
        if ($published.tagName -cne $tag -or $published.isDraft -or $published.isPrerelease) {
            throw 'Release was submitted for publication but did not verify as a stable published release.'
        }
        Write-Host "Published stable release: https://github.com/$Repo/releases/tag/$tag"
    } else {
        Write-Host "Draft ready for review: https://github.com/$Repo/releases/tag/$tag"
        Write-Host "After review, publish with: gh release edit $tag --repo $Repo --draft=false"
    }
}
catch {
    Write-Error $_
    exit 1
}
