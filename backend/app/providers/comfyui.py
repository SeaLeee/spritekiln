"""ComfyUI adapter: API-format workflow templates + field maps, HTTP submit, WS progress, output download."""
from __future__ import annotations

import asyncio
import copy
import io
import json
import random
import uuid
from pathlib import Path
from typing import Any

from PIL import Image

from ..config import WORKFLOW_DIR, provider_cfg
from .base import ImageProvider, ProviderError, VideoProvider
from .util import client, png_bytes


def load_workflow(name: str) -> tuple[dict, dict]:
    graph = json.loads((WORKFLOW_DIR / f"{name}.json").read_text(encoding="utf-8"))
    fmap = json.loads((WORKFLOW_DIR / f"{name}.map.json").read_text(encoding="utf-8"))
    return graph, fmap


def list_workflows() -> list[dict]:
    out = []
    for p in sorted(WORKFLOW_DIR.glob("*.map.json")):
        m = json.loads(p.read_text(encoding="utf-8"))
        out.append({"name": p.name[:-9], "kind": m.get("kind"), "label": m.get("label", p.name[:-9]),
                    "models": m.get("models", [])})
    return out


def patch(graph: dict, fmap: dict, values: dict[str, Any]) -> dict:
    g = copy.deepcopy(graph)
    for field, value in values.items():
        if value is None:
            continue
        for node_id, key in fmap.get("fields", {}).get(field, []):
            if node_id in g:
                g[node_id]["inputs"][key] = value
    return g


def _round16(v: int) -> int:
    return max(64, int(round(v / 16)) * 16)


class ComfyClient:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")

    async def health(self) -> dict[str, Any]:
        try:
            async with client(3) as c:
                r = await c.get(f"{self.base}/system_stats")
            if r.status_code != 200:
                return {"ok": False, "detail": f"HTTP {r.status_code}"}
            dev = (r.json().get("devices") or [{}])[0]
            free = dev.get("vram_free", 0) / 1024 ** 3
            return {"ok": True, "detail": f"{dev.get('name', 'GPU')} · 空闲显存 {free:.1f} GB"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "detail": f"未运行 ({type(exc).__name__})，可用 tools/start_comfyui.ps1 启动"}

    async def upload(self, img: Image.Image, name: str | None = None) -> str:
        name = name or f"spritekiln_{uuid.uuid4().hex[:10]}.png"
        async with client(120) as c:
            r = await c.post(f"{self.base}/upload/image", files={"image": (name, png_bytes(img), "image/png")},
                             data={"overwrite": "true", "type": "input"})
        r.raise_for_status()
        return r.json()["name"]

    async def free(self) -> None:
        try:
            async with client(10) as c:
                await c.post(f"{self.base}/free", json={"unload_models": True, "free_memory": True})
        except Exception:  # noqa: BLE001
            pass

    async def interrupt(self) -> None:
        try:
            async with client(10) as c:
                await c.post(f"{self.base}/interrupt", json={})
        except Exception:  # noqa: BLE001
            pass

    async def run(self, graph: dict, ctx: Any = None, label: str = "ComfyUI", timeout: float = 1800) -> dict:
        client_id = uuid.uuid4().hex
        async with client(60) as c:
            r = await c.post(f"{self.base}/prompt", json={"prompt": graph, "client_id": client_id})
        if r.status_code >= 400:
            raise ProviderError(f"ComfyUI 拒绝工作流: {r.text[:600]}")
        prompt_id = r.json()["prompt_id"]
        ws_task = asyncio.create_task(self._watch(client_id, prompt_id, ctx, label))
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        try:
            while True:
                if ctx is not None and ctx.canceled:
                    await self.interrupt()
                    ctx.check()
                async with client(30) as c:
                    h = await c.get(f"{self.base}/history/{prompt_id}")
                data = h.json() if h.status_code == 200 else {}
                if prompt_id in data:
                    entry = data[prompt_id]
                    status = entry.get("status", {})
                    if status.get("status_str") == "error":
                        msgs = [m for m in status.get("messages", []) if m[0] == "execution_error"]
                        detail = msgs[0][1].get("exception_message", "") if msgs else str(status)[:400]
                        raise ProviderError(f"ComfyUI 执行出错: {detail}")
                    if status.get("completed", True):
                        return entry.get("outputs", {})
                if loop.time() - t0 > timeout:
                    await self.interrupt()
                    raise ProviderError("ComfyUI 执行超时")
                await asyncio.sleep(1.0)
        finally:
            ws_task.cancel()

    async def _watch(self, client_id: str, prompt_id: str, ctx: Any, label: str) -> None:
        if ctx is None:
            return
        try:
            import websockets
            url = self.base.replace("http", "ws", 1) + f"/ws?clientId={client_id}"
            last = 0.1
            async with websockets.connect(url, max_size=None) as ws:
                async for msg in ws:
                    if isinstance(msg, bytes):
                        continue
                    data = json.loads(msg)
                    d = data.get("data", {})
                    if d.get("prompt_id") not in (None, prompt_id):
                        continue
                    if data.get("type") == "progress" and d.get("max"):
                        last = 0.1 + 0.8 * d["value"] / d["max"]
                        ctx.progress(last, f"{label} 采样 {d['value']}/{d['max']}")
                    elif data.get("type") == "executing" and d.get("node"):
                        ctx.progress(last, f"{label} 执行节点 {d['node']}")
        except Exception:  # noqa: BLE001
            return

    async def images_from(self, outputs: dict, node_ids: list[str] | None = None) -> list[Image.Image]:
        imgs: list[Image.Image] = []
        async with client(120) as c:
            for nid, out in outputs.items():
                if node_ids and nid not in node_ids:
                    continue
                for key in ("images", "gifs", "videos"):
                    for f in out.get(key, []) or []:
                        params = {"filename": f["filename"], "subfolder": f.get("subfolder", ""),
                                  "type": f.get("type", "output")}
                        r = await c.get(f"{self.base}/view", params=params)
                        r.raise_for_status()
                        if f["filename"].lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                            imgs.append(Image.open(io.BytesIO(r.content)).convert("RGBA"))
                        else:
                            from .util import extract_frames
                            imgs.extend(extract_frames(r.content, 10_000))
        return imgs


def _client() -> ComfyClient:
    return ComfyClient(provider_cfg("comfyui").get("base_url", "http://127.0.0.1:8188"))


class ComfyImageProvider(ImageProvider):
    name = "comfyui"
    label = "本地 ComfyUI (Z-Image Turbo)"
    lane = "gpu"
    supports_refs = False
    supports_edit = True

    async def health(self) -> dict[str, Any]:
        return await _client().health()

    async def generate(self, prompt: str, *, width: int = 1024, height: int = 1024, n: int = 1, seed=None,
                       refs=None, negative: str = "", quality: str = "standard", transparent: bool = False,
                       layout=None, ctx: Any = None) -> list[Image.Image]:
        cfg = provider_cfg("comfyui")
        if refs:
            # Z-Image has no reference conditioning: fall back to img2img from the first reference
            return await self.edit(refs[0], prompt, strength=0.78, seed=seed, width=width, height=height, ctx=ctx)
        graph, fmap = load_workflow(cfg.get("image_workflow", "zimage_turbo_t2i"))
        steps = {"standard": 8, "detailed": 10, "ultimate": 12}.get(quality, 8)
        g = patch(graph, fmap, {"prompt": prompt, "negative": negative or None,
                                "seed": seed if seed is not None else random.randint(0, 2 ** 31),
                                "width": _round16(width), "height": _round16(height), "batch": n, "steps": steps})
        outputs = await _client().run(g, ctx, "Z-Image", cfg.get("timeout", 1800))
        imgs = await _client().images_from(outputs, fmap.get("output"))
        if not imgs:
            raise ProviderError("ComfyUI 未返回图片")
        return imgs

    async def edit(self, image: Image.Image, prompt: str, *, refs=None, mask=None, strength: float = 0.65,
                   seed=None, width=None, height=None, ctx: Any = None) -> list[Image.Image]:
        cfg = provider_cfg("comfyui")
        graph, fmap = load_workflow(cfg.get("img2img_workflow", "zimage_turbo_i2i"))
        w, h = _round16(width or image.width), _round16(height or image.height)
        src = image.convert("RGBA")
        bg = Image.new("RGBA", src.size, (255, 255, 255, 255))
        bg.alpha_composite(src)
        name = await _client().upload(bg.convert("RGB").resize((w, h), Image.Resampling.LANCZOS))
        g = patch(graph, fmap, {"prompt": prompt, "image": name, "denoise": float(max(0.05, min(1.0, strength))),
                                "seed": seed if seed is not None else random.randint(0, 2 ** 31)})
        outputs = await _client().run(g, ctx, "Z-Image 重绘", cfg.get("timeout", 1800))
        return await _client().images_from(outputs, fmap.get("output"))


class ComfyVideoProvider(VideoProvider):
    name = "comfyui"
    label = "本地 ComfyUI 视频 (MiniMax H3 / Wan2.2)"
    lane = "gpu"
    supports_last_frame = True

    async def health(self) -> dict[str, Any]:
        return await _client().health()

    async def animate(self, first: Image.Image, prompt: str, *, last=None, num_frames: int = 16, fps: int = 8,
                      width: int = 512, height: int = 512, seed=None, ctx: Any = None) -> list[Image.Image]:
        cfg = provider_cfg("comfyui")
        wf = cfg.get("video_workflow", "minimax_h3_fl2v")
        graph, fmap = load_workflow(wf)
        c = _client()
        first_name = await c.upload(first.convert("RGB").resize((width, height), Image.Resampling.LANCZOS))
        last_img = last if last is not None else first
        last_name = await c.upload(last_img.convert("RGB").resize((width, height), Image.Resampling.LANCZOS))
        seconds = max(1.0, num_frames / max(1, fps))
        native = int(fmap.get("native_fps", 24))
        x = max(5, round(seconds * native))
        if fmap.get("length_rule") == "h3":
            length = x + (5 - x % 17) % 17
        elif fmap.get("length_rule") == "4n+1":
            length = (x // 4) * 4 + 1
        else:
            length = x
        g = patch(graph, fmap, {
            "prompt": prompt, "image": first_name, "last_image": last_name, "width": width, "height": height,
            "seed": seed if seed is not None else random.randint(0, 2 ** 31), "length": length,
            "steps": cfg.get("video_steps") or None,
        })
        outputs = await c.run(g, ctx, fmap.get("label", "视频模型"), cfg.get("timeout", 1800))
        frames = await c.images_from(outputs, fmap.get("output"))
        if not frames:
            raise ProviderError("ComfyUI 视频工作流未返回帧")
        if len(frames) > num_frames:
            step = len(frames) / num_frames
            frames = [frames[min(len(frames) - 1, int(i * step))] for i in range(num_frames)]
        return frames


async def free_vram() -> None:
    await _client().free()
