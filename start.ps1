# SpriteKiln 像素窑 一键启动
#   .\start.ps1               启动 SpriteKiln (端口 7788)，若 ComfyUI 未运行则在新窗口启动
#   .\start.ps1 -NoComfy      不启动 ComfyUI（使用云端/离线引擎）
#   .\start.ps1 -Build        先重新构建前端
param([switch]$NoComfy, [switch]$Build, [int]$Port = 7788)
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONIOENCODING = "utf-8"

if ($Build -or -not (Test-Path "$root\web\dist\index.html")) {
  Push-Location "$root\web"
  if (-not (Test-Path node_modules)) { npm install }
  npm run build
  Pop-Location
}

if (-not $NoComfy) {
  $up = $false
  try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:8188/system_stats | Out-Null; $up = $true } catch {}
  $comfyDir = $env:COMFYUI_DIR
  if (-not $up -and $comfyDir -and (Test-Path (Join-Path $comfyDir "main.py"))) {
    Write-Host "启动 ComfyUI (新窗口)…"
    Start-Process powershell -ArgumentList "-NoExit", "-File", "`"$root\tools\start_comfyui.ps1`""
  } elseif (-not $up) {
    Write-Host "ComfyUI 未运行，且未设置 COMFYUI_DIR；本次使用云端/离线引擎。"
    Write-Host "  如需本地生图：`$env:COMFYUI_DIR = 'D:\AI\ComfyUI'; .\start.ps1"
  }
}

Start-Job -ScriptBlock { param($p) Start-Sleep 4; Start-Process "http://127.0.0.1:$p" } -ArgumentList $Port | Out-Null
Write-Host "SpriteKiln → http://127.0.0.1:$Port   (API 文档: /docs)"
python "$root\backend\run.py" --port $Port
