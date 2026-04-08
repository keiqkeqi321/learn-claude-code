# =============================================================
#  OpenAgent — 一键安装脚本 (Windows PowerShell)
# =============================================================
#  用法:
#    irm https://raw.githubusercontent.com/your-org/openagent/main/install.ps1 | iex
#
#  做什么:
#    1. 检测 Python 3.11+，没有则提示安装方式
#    2. pip install openagent
#    3. 验证安装成功
# =============================================================

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "🤖 OpenAgent Installer" -ForegroundColor Cyan
Write-Host ""

# ─── Step 1: Find Python ─────────────────────────────────────
$pythonCmd = $null

foreach ($cmd in @("python", "python3")) {
    try {
        $out = & $cmd --version 2>&1
        if ($out -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -eq 3 -and $minor -ge 11) {
                $pythonCmd = $cmd
                Write-Host "✓ Found $($out.Trim()) ($cmd)" -ForegroundColor Green
                break
            }
        }
    } catch { }
}

if (-not $pythonCmd) {
    Write-Host "✗ Python 3.11+ not found" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Please install Python 3.11+ first:" 
    Write-Host ""
    Write-Host "    winget:  " -NoNewline; Write-Host "winget install Python.Python.3.12" -ForegroundColor Cyan
    Write-Host "    choco:   " -NoNewline; Write-Host "choco install python312" -ForegroundColor Cyan
    Write-Host "    Download:" -NoNewline; Write-Host " https://www.python.org/downloads/" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Then re-run this script."
    exit 1
}

# ─── Step 2: Install openagent ────────────────────────────────
Write-Host ""
Write-Host "📦 Installing openagent ..." -ForegroundColor Cyan
& $pythonCmd -m pip install --upgrade openagent

# ─── Step 3: Verify ──────────────────────────────────────────
Write-Host ""
try {
    & $pythonCmd -m openagent --help | Out-Null
    Write-Host "✅ OpenAgent installed successfully!" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Run:"
    Write-Host "    openagent"              -ForegroundColor Cyan -NoNewline; Write-Host "              # interactive REPL"
    Write-Host "    openagent chat 'hello'"  -ForegroundColor Cyan -NoNewline; Write-Host "  # one-shot"
    Write-Host ""
} catch {
    Write-Host "⚠  Installation completed but verification failed." -ForegroundColor Yellow
    Write-Host "  Try: " -NoNewline; Write-Host "python -m openagent" -ForegroundColor Cyan
}
