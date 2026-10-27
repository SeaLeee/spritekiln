"""Pixal3D (TencentARC) local image→3D adapter, run as an isolated subprocess in its own venv.

3090 strategy: GPU lane concurrency = 1, free ComfyUI/BiRefNet VRAM before starting, ``--low_vram`` stage-wise
loading (peak ≈ 12-14 GB at 1024), SDPA attention (no flash-attn on Windows), offline HF cache.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from pathlib import Path
from typing import Any

from PIL import Image

from ..config import provider_cfg
from .base import ProviderError, ThreeDProvider

STAGES = [("Loading", 0.05, "加载模型"), ("Sparse", 0.25, "稀疏结构采样"), ("shape", 0.45, "几何采样"),
          ("tex", 0.65, "PBR 纹理采样"), ("Decod", 0.8, "解码网格"), ("glb", 0.9, "导出 GLB"),
          ("GLB", 0.9, "导出 GLB")]


class Pixal3DProvider(ThreeDProvider):
    name = "pixal3d"
    label = "Pixal3D 本地 (单图→PBR GLB)"
    lane = "gpu"

    def _cfg(self) -> dict:
        return provider_cfg("pixal3d")

    async def health(self) -> dict[str, Any]:
        cfg = self._cfg()
        py = Path(cfg.get("python", ""))
        repo = Path(cfg.get("repo", ""))
        if not py.exists() or not (repo / "inference.py").exists():
            return {"ok": False, "detail": "未找到 Pixal3D 仓库或 venv"}
        site = py.parent.parent / "Lib" / "site-packages"
        if not (site / "cumesh_vb").exists() and not (site / "cumesh").exists():
            return {"ok": False, "detail": "venv 缺少编译扩展，请运行 tools/fix_pixal3d.ps1"}
        return {"ok": True, "detail": f"{repo.name} · low_vram={cfg.get('low_vram')} · {cfg.get('resolution')}"}

    async def image_to_3d(self, image: Image.Image, out_dir: Path, *, seed: int = 42, quality: str = "standard",
                          ctx: Any = None) -> Path:
        cfg = self._cfg()
        out_dir.mkdir(parents=True, exist_ok=True)
        src = out_dir / "input.png"
        image.convert("RGBA").save(src)
        glb = out_dir / "model.glb"
        resolution = 1536 if quality == "ultimate" and not cfg.get("low_vram") else int(cfg.get("resolution", 1024))
        args = [cfg["python"], "inference.py", "--image", str(src), "--output", str(glb), "--seed", str(seed),
                "--resolution", str(resolution)]
        if cfg.get("low_vram", True):
            args.append("--low_vram")
        env = dict(os.environ, ATTN_BACKEND="sdpa", HF_HUB_OFFLINE="1", PYTHONIOENCODING="utf-8",
                   PYTHONUNBUFFERED="1", PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True",
                   OPENCV_IO_ENABLE_OPENEXR="1")
        # make room on the single 24 GB GPU
        from ..pixel.bg import birefnet
        from .comfyui import free_vram
        birefnet.unload()
        await free_vram()

        log_path = out_dir / "pixal3d.log"
        proc = await asyncio.create_subprocess_exec(*args, cwd=cfg["repo"], env=env, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.STDOUT)
        t0 = time.time()
        progress = 0.02
        tail: list[str] = []
        with open(log_path, "wb") as log:
            assert proc.stdout is not None
            while True:
                if ctx is not None and ctx.canceled:
                    proc.kill()
                    ctx.check()
                try:
                    chunk = await asyncio.wait_for(proc.stdout.read(4096), timeout=2.0)
                except asyncio.TimeoutError:
                    chunk = b""
                    if proc.returncode is not None:
                        break
                    if time.time() - t0 > cfg.get("timeout", 2400):
                        proc.kill()
                        raise ProviderError("Pixal3D 超时")
                    continue
                if not chunk:
                    break
                log.write(chunk)
                text = chunk.decode("utf-8", "ignore")
                for line in re.split(r"[\r\n]+", text):
                    if not line.strip():
                        continue
                    tail = (tail + [line])[-30:]
                    for key, val, label in STAGES:
                        if key in line and val > progress:
                            progress = val
                            if ctx is not None:
                                ctx.progress(progress, f"Pixal3D · {label} ({int(time.time() - t0)}s)")
            await proc.wait()
        if proc.returncode != 0 or not glb.exists():
            raise ProviderError("Pixal3D 失败: " + " | ".join(tail[-6:])[-800:])
        return glb
