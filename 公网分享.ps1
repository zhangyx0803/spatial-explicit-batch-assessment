# 一键启动本地服务 + 公网临时隧道
# 用法：右键「使用 PowerShell 运行」
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  空间显式批量评估工作台 V1.0  (SEBA)  公网分享" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

$py = if (Test-Path ".\.venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" } else { "python" }
Write-Host "[环境] $py" -ForegroundColor DarkGray

# 1) 检查 cloudflared
$cf = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cf) {
    Write-Host "[提示] 未安装 cloudflared，正在安装（winget）…" -ForegroundColor Yellow
    winget install --id Cloudflare.cloudflared -e --accept-source-agreements --accept-package-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")
    $cf = Get-Command cloudflared -ErrorAction SilentlyContinue
    if (-not $cf) {
        Write-Host "[失败] cloudflared 装不上。可手动下载：https://github.com/cloudflare/cloudflared/releases" -ForegroundColor Red
        Read-Host "按回车退出"
        exit 1
    }
}

# 2) 后台启动本地服务
Write-Host "[1/2] 启动本地服务（127.0.0.1:8765）…" -ForegroundColor Green
$server = Start-Process -FilePath $py `
    -ArgumentList "run_web.py","--no-open","--bundle","data/demo_xuhui.bundle","--port","8765" `
    -PassThru -WindowStyle Minimized

Start-Sleep -Seconds 12
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8765/api/bootstrap" -UseBasicParsing -TimeoutSec 30
    $j = $r.Content | ConvertFrom-Json
    Write-Host "      本地服务正常：$($j.project.n_units) 个单元" -ForegroundColor Green
} catch {
    Write-Host "[失败] 本地服务没起来，先单独跑 启动.bat 看报错" -ForegroundColor Red
    Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
    Read-Host "按回车退出"
    exit 1
}

# 3) 开公网隧道
Write-Host "[2/2] 建立公网隧道…（下面出现的 trycloudflare.com 地址就是分享链接）" -ForegroundColor Green
Write-Host ""
Write-Host "------------------------------------------------------------" -ForegroundColor DarkGray
& cloudflared tunnel --url http://127.0.0.1:8765

# 隧道退出后清理
Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
Write-Host "已停止本地服务。" -ForegroundColor DarkGray
