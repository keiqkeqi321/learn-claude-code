# release.ps1 — Somnia 发版脚本 (Windows PowerShell)
# =============================================================
#  用法:
#    powershell -File scripts\release.ps1 0.2.0
#    powershell -File scripts\release.ps1 0.2.0 -Dry
#    powershell -File scripts\release.ps1 0.2.0 -SkipPush
# =============================================================

param(
    [Parameter(Mandatory=$true)]
    [string]$Version,

    [switch]$Dry,
    [switch]$SkipPush
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

Write-Host ""
Write-Host "🚀 Somnia Release" -ForegroundColor Cyan
Write-Host ""

# ─── 1. 检查工作区干净 ──────────────────────────────────────
$status = git status --porcelain
if ($status) {
    Write-Host "✗ 工作区有未提交的更改，请先 commit 或 stash" -ForegroundColor Red
    git status --short
    exit 1
}
Write-Host "✓ 工作区干净" -ForegroundColor Green

# ─── 2. 验证版本号格式 ──────────────────────────────────────
if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    Write-Host "✗ 版本号格式错误: $Version (需要 semver: x.y.z)" -ForegroundColor Red
    exit 1
}

$currentVersion = (Get-Content "VERSION" -Raw).Trim()
Write-Host "  当前版本: $currentVersion" -ForegroundColor Yellow
Write-Host "  目标版本: $Version" -ForegroundColor Green
Write-Host ""

if ($Dry) {
    Write-Host "👀 DRY RUN — 不会实际修改任何内容" -ForegroundColor Yellow
    Write-Host ""
}

# ─── 3. 更新 VERSION 文件 ────────────────────────────────────
if (-not $Dry) {
    Set-Content "VERSION" $Version -NoNewline
    Write-Host "✓ VERSION → $Version" -ForegroundColor Green
}

# ─── 4. 同步版本号 ───────────────────────────────────────────
if (-not $Dry) {
    & powershell -File "scripts\sync-version.ps1"
}

# ─── 5. 更新 CHANGELOG.md ────────────────────────────────────
$today = Get-Date -Format "yyyy-MM-dd"
if (-not $Dry) {
    $changelog = Get-Content "CHANGELOG.md" -Raw
    $newEntry = "# Changelog`n`n## $Version ($today)`n`n- (请手动补充 changelog)`n"
    $changelog = $changelog -replace "^# Changelog", $newEntry
    Set-Content "CHANGELOG.md" $changelog -NoNewline
    Write-Host "✓ CHANGELOG.md 已添加 $Version 条目" -ForegroundColor Green
}

# ─── 6. Git commit + tag ─────────────────────────────────────
if (-not $Dry) {
    git add VERSION openagent/__init__.py npm/package.json CHANGELOG.md
    git commit -m "release: v$Version"
    git tag "v$Version"
    Write-Host "✓ git commit + tag v$Version" -ForegroundColor Green
}

# ─── 7. 构建 PyPI 包 ─────────────────────────────────────────
if (-not $Dry) {
    if (Test-Path dist) { Remove-Item dist -Recurse -Force }
    python -m build 2>&1 | Select-Object -Last 2
    Write-Host "✓ 构建完成" -ForegroundColor Green
}

# ─── 8. 发布到 PyPI ──────────────────────────────────────────
if (-not $Dry) {
    Write-Host ""
    Write-Host "📦 发布到 PyPI ..." -ForegroundColor Cyan
    twine upload dist/* 2>&1
    Write-Host "✓ PyPI 发布完成" -ForegroundColor Green
}

# ─── 9. 推送到 GitHub ────────────────────────────────────────
if ((-not $Dry) -and (-not $SkipPush)) {
    Write-Host ""
    Write-Host "📤 推送到 GitHub ..." -ForegroundColor Cyan
    git push origin main
    git push origin "v$Version"
    Write-Host "✓ 推送完成 (CI 将自动发布 npm)" -ForegroundColor Green
}

# ─── 完成 ─────────────────────────────────────────────────────
Write-Host ""
if ($Dry) {
    Write-Host "👀 DRY RUN 完成 — 以上为将要执行的操作" -ForegroundColor Yellow
} else {
    Write-Host "✅ Somnia v$Version 发布成功！" -ForegroundColor Green
    Write-Host ""
    Write-Host "  PyPI:  https://pypi.org/project/somnia/$Version/"
    Write-Host "  安装:  pip install somnia"
    Write-Host "  升级:  pip install --upgrade somnia"
    if ($SkipPush) {
        Write-Host ""
        Write-Host "  ⚠️  未推送到远程，手动推送:" -ForegroundColor Yellow
        Write-Host "    git push origin main"
        Write-Host "    git push origin v$Version"
    }
}
