# Start a local ComfyUI for SpriteKiln.
#   .\tools\start_comfyui.ps1 -ComfyDir "D:\AI\ComfyUI"
#   $env:COMFYUI_DIR = "D:\AI\ComfyUI"; .\tools\start_comfyui.ps1
# Uses <ComfyDir>\.venv when present, otherwise `python` from PATH. An existing
# extra_model_paths.yaml is passed through; a missing one is not required.
param(
  [string]$ComfyDir = $env:COMFYUI_DIR,
  [int]$Port = 8188,
  [string]$Python = ""
)
$ErrorActionPreference = "Stop"
if (-not $ComfyDir) {
  throw '缺少 ComfyUI 目录。请传入 -ComfyDir "D:\AI\ComfyUI"，或设置环境变量 COMFYUI_DIR。'
}
if (-not (Test-Path (Join-Path $ComfyDir "main.py"))) {
  throw "不是 ComfyUI 目录（缺少 main.py）: $ComfyDir"
}

$py = $Python
if (-not $py) {
  $venvPy = Join-Path $ComfyDir ".venv\Scripts\python.exe"
  $py = if (Test-Path $venvPy) { $venvPy } else { "python" }
}

$env:PYTHONUTF8 = "1"
$env:PYTORCH_CUDA_ALLOC_CONF = "expandable_segments:True"
$torchLib = Join-Path $ComfyDir ".venv\Lib\site-packages\torch\lib"
if (Test-Path $torchLib) { $env:PATH = "$torchLib;$env:PATH" }

$cli = @("main.py")
$extra = Join-Path $ComfyDir "extra_model_paths.yaml"
if (Test-Path $extra) { $cli += @("--extra-model-paths-config", $extra) }
$cli += @("--disable-cuda-malloc", "--port", "$Port")

Set-Location $ComfyDir
Write-Host "ComfyUI → http://127.0.0.1:$Port   ($py)"
& $py @cli
