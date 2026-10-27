# SpriteKiln - Pixal3D 本地修复脚本 (RTX 3090 / Windows)
#
# 根因:
#   1. Pixal3D 独立 venv (torch 2.6.0+cu124) 缺少编译型 3D 扩展 (cumesh / flex_gemm / o_voxel /
#      nvdiffrast / nvdiffrec_render / natten) -> ModuleNotFoundError: cumesh
#   2. 这些扩展的 cu124+torch2.6 预编译版本只装在 ComfyUI\.venv 中, 而 ComfyUI venv 已升级到
#      torch 2.11+cu130, ABI 不匹配, 在 ComfyUI 内也会加载失败
#   3. 预编译包是改名分叉版 (cumesh_vb / flex_gemm_ap), Pixal3D 源码 import 的是 cumesh / flex_gemm
#   4. flex_gemm 的 triton 内核需要 triton-windows, 独立 venv 未安装
#   5. 默认 ATTN_BACKEND=flash_attn, Windows 无 flash_attn -> 需 sdpa (由 SpriteKiln 调用时设置)
#
# 修复: 把 ComfyUI venv 中与 torch2.6/cu124 匹配的扩展拷贝进 Pixal3D venv, 注册别名, 安装 triton-windows 3.2

param(
  [string]$Pixal3D = $env:PIXAL3D_DIR,
  [string]$ComfyVenv = $(if ($env:COMFYUI_DIR) { Join-Path $env:COMFYUI_DIR ".venv" } else { "" }),
  [string]$Proxy = ""
)
$ErrorActionPreference = "Stop"
if (-not $Pixal3D -or -not $ComfyVenv) {
  throw @"
缺少路径参数。请显式传入，或先设置环境变量：
  .\tools\fix_pixal3d.ps1 -Pixal3D "D:\AI\Pixal3D" -ComfyVenv "D:\AI\ComfyUI\.venv"
或：
  `$env:PIXAL3D_DIR = "D:\AI\Pixal3D"; `$env:COMFYUI_DIR = "D:\AI\ComfyUI"; .\tools\fix_pixal3d.ps1
"@
}
$src = Join-Path $ComfyVenv "Lib\site-packages"
$dst = Join-Path $Pixal3D "venv\Lib\site-packages"
$py = Join-Path $Pixal3D "venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Pixal3D venv not found: $py" }

$pkgs = @('cumesh_vb', 'flex_gemm_ap', 'o_voxel', 'o_voxel_vb_ap', 'nvdiffrec_render', 'natten', 'nvdiffrast')
foreach ($p in $pkgs) {
  $from = Join-Path $src $p
  if (-not (Test-Path $from)) { Write-Warning "skip missing $p"; continue }
  $to = Join-Path $dst $p
  if (Test-Path $to) { Write-Host "exists: $p" } else {
    Copy-Item -Recurse $from $to
    Write-Host "copied: $p"
  }
  Get-ChildItem $src -Directory | Where-Object { $_.Name -like "$p-*.dist-info" } | ForEach-Object {
    $t = Join-Path $dst $_.Name
    if (-not (Test-Path $t)) { Copy-Item -Recurse $_.FullName $t }
  }
}
Get-ChildItem $src -Directory | Where-Object { $_.Name -like "diffrp_nvdiffrast-*.dist-info" } | ForEach-Object {
  $t = Join-Path $dst $_.Name; if (-not (Test-Path $t)) { Copy-Item -Recurse $_.FullName $t }
}

# 别名: cumesh -> cumesh_vb, flex_gemm -> flex_gemm_ap (支持子模块 import)
$alias = @'
import importlib, importlib.abc, importlib.util, sys

_ALIASES = {"cumesh": "cumesh_vb", "flex_gemm": "flex_gemm_ap"}


class _AliasLoader(importlib.abc.Loader):
    def __init__(self, real):
        self.real = real

    def create_module(self, spec):
        mod = importlib.import_module(self.real)
        sys.modules[spec.name] = mod
        return mod

    def exec_module(self, module):
        pass


class _AliasFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        head, _, rest = fullname.partition(".")
        if head not in _ALIASES:
            return None
        real = _ALIASES[head] + ("." + rest if rest else "")
        if importlib.util.find_spec(real) is None:
            return None
        return importlib.util.spec_from_loader(fullname, _AliasLoader(real))


if not any(isinstance(f, _AliasFinder) for f in sys.meta_path):
    sys.meta_path.insert(0, _AliasFinder())
'@
Set-Content -Encoding utf8 (Join-Path $dst "_spritekiln_aliases.py") $alias
Set-Content -Encoding ascii (Join-Path $dst "spritekiln_aliases.pth") "import _spritekiln_aliases"
Write-Host "alias shim installed"

$ErrorActionPreference = "Continue"
if ($Proxy) { $env:HTTP_PROXY = $Proxy; $env:HTTPS_PROXY = $Proxy }
& $py -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('triton') else 1)"
if ($LASTEXITCODE -ne 0) {
  Write-Host "installing triton-windows 3.2 (torch 2.6 compatible)..."
  & $py -m pip install "triton-windows>=3.2,<3.3"
}

& $py -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('einops') and importlib.util.find_spec('timm') else 1)"
if ($LASTEXITCODE -ne 0) {
  Write-Host "installing einops/timm (BiRefNet remote code deps)..."
  & $py -m pip install einops timm
}

& $py -c "import torch, cumesh, flex_gemm, o_voxel, nvdiffrast.torch, natten, triton; from flex_gemm.ops.spconv import sparse_submanifold_conv3d; print('OK torch', torch.__version__, 'cuda', torch.cuda.is_available())"
