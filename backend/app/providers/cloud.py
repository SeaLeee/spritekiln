"""Volcengine Ark (Seedream image / Seedance video) and MiniMax (image-01 / Hailuo video) adapters."""
from __future__ import annotations

from typing import Any

from PIL import Image

from ..config import provider_cfg
from .base import ImageProvider, ProviderError, VideoProvider
from .util import b64_to_image, check_budget, client, data_uri, extract_frames, fetch_bytes, fetch_image, poll, require


def _ratio(w: int, h: int, options: list[str]) -> str:
    ar = w / h

    def val(s: str) -> float:
        a, b = s.split(":")
        return int(a) / int(b)

    return min(options, key=lambda s: abs(val(s) - ar))


# ---------------------------------------------------------------- Ark
class ArkImageProvider(ImageProvider):
    name = "ark"
    label = "火山方舟 Seedream"
    lane = "cloud"
    supports_refs = True
    supports_edit = True

    def _cfg(self) -> dict:
        return provider_cfg("ark")

    async def health(self) -> dict[str, Any]:
        ok = bool(self._cfg().get("api_key"))
        return {"ok": ok, "detail": "已配置密钥" if ok else "未配置密钥"}

    def estimate_cost(self, width: int, height: int, n: int = 1) -> float:
        return 0.03 * n

    async def generate(self, prompt: str, *, width: int = 1024, height: int = 1024, n: int = 1, seed=None,
                       refs=None, negative: str = "", quality: str = "standard", transparent: bool = False,
                       layout=None, ctx: Any = None) -> list[Image.Image]:
        cfg = self._cfg()
        key = require(cfg, "api_key", "火山方舟")
        out: list[Image.Image] = []
        for i in range(n):
            check_budget(self.estimate_cost(width, height), ctx)
            body: dict[str, Any] = {"model": cfg["image_model"], "prompt": prompt, "response_format": "b64_json",
                                    "size": f"{max(1024, width)}x{max(1024, height)}" if quality != "standard" else f"{width}x{height}",
                                    "watermark": False}
            if seed is not None:
                body["seed"] = int(seed) + i
            if refs:
                body["image"] = [data_uri(r) for r in refs[:10]]
                body["sequential_image_generation"] = "disabled"
            async with client(300) as c:
                r = await c.post(f"{cfg['base_url'].rstrip('/')}/images/generations", json=body,
                                 headers={"Authorization": f"Bearer {key}"})
            if r.status_code >= 400:
                raise ProviderError(f"Seedream 失败 {r.status_code}: {r.text[:400]}")
            for item in r.json().get("data", []):
                out.append(b64_to_image(item["b64_json"]) if item.get("b64_json") else await fetch_image(item["url"]))
            if ctx is not None:
                ctx.add_cost(self.estimate_cost(width, height))
        return out

    async def edit(self, image: Image.Image, prompt: str, *, refs=None, mask=None, strength: float = 0.65,
                   seed=None, width=None, height=None, ctx: Any = None) -> list[Image.Image]:
        return await self.generate(prompt, width=width or image.width, height=height or image.height, n=1,
                                   seed=seed, refs=[image, *(refs or [])], ctx=ctx)


class ArkVideoProvider(VideoProvider):
    name = "ark"
    label = "火山方舟 Seedance"
    lane = "cloud"
    supports_last_frame = True

    def _cfg(self) -> dict:
        return provider_cfg("ark")

    async def health(self) -> dict[str, Any]:
        ok = bool(self._cfg().get("api_key"))
        return {"ok": ok, "detail": "已配置密钥" if ok else "未配置密钥"}

    def estimate_cost(self, seconds: float) -> float:
        return 0.03 * seconds

    async def animate(self, first: Image.Image, prompt: str, *, last=None, num_frames: int = 16, fps: int = 8,
                      width: int = 512, height: int = 512, seed=None, ctx: Any = None) -> list[Image.Image]:
        cfg = self._cfg()
        key = require(cfg, "api_key", "火山方舟")
        seconds = 5 if num_frames / max(1, fps) <= 5 else 10
        check_budget(self.estimate_cost(seconds), ctx)
        text = f"{prompt} --resolution 480p --duration {seconds} --camerafixed true --watermark false"
        content: list[dict[str, Any]] = [{"type": "text", "text": text},
                                         {"type": "image_url", "image_url": {"url": data_uri(first.convert("RGB"))},
                                          "role": "first_frame"}]
        if last is not None:
            content.append({"type": "image_url", "image_url": {"url": data_uri(last.convert("RGB"))}, "role": "last_frame"})
        headers = {"Authorization": f"Bearer {key}"}
        base = cfg["base_url"].rstrip("/")
        async with client(60) as c:
            r = await c.post(f"{base}/contents/generations/tasks", json={"model": cfg["video_model"], "content": content},
                             headers=headers)
        if r.status_code >= 400:
            raise ProviderError(f"Seedance 提交失败 {r.status_code}: {r.text[:400]}")
        task_id = r.json()["id"]

        async def check():
            async with client(60) as c2:
                q = await c2.get(f"{base}/contents/generations/tasks/{task_id}", headers=headers)
            data = q.json()
            status = data.get("status")
            if status == "succeeded":
                return data["content"]["video_url"]
            if status in ("failed", "cancelled"):
                raise ProviderError(f"Seedance 任务失败: {data.get('error')}")
            return None

        url = await poll(check, interval=5, timeout=900, ctx=ctx, label="Seedance 生成视频")
        if ctx is not None:
            ctx.add_cost(self.estimate_cost(seconds))
        return extract_frames(await fetch_bytes(url), num_frames)


# ---------------------------------------------------------------- MiniMax
class MiniMaxImageProvider(ImageProvider):
    name = "minimax"
    label = "MiniMax image-01"
    lane = "cloud"
    supports_refs = True

    def _cfg(self) -> dict:
        return provider_cfg("minimax")

    async def health(self) -> dict[str, Any]:
        ok = bool(self._cfg().get("api_key"))
        return {"ok": ok, "detail": "已配置密钥" if ok else "未配置密钥"}

    def estimate_cost(self, width: int, height: int, n: int = 1) -> float:
        return 0.0035 * n

    async def generate(self, prompt: str, *, width: int = 1024, height: int = 1024, n: int = 1, seed=None,
                       refs=None, negative: str = "", quality: str = "standard", transparent: bool = False,
                       layout=None, ctx: Any = None) -> list[Image.Image]:
        cfg = self._cfg()
        key = require(cfg, "api_key", "MiniMax")
        check_budget(self.estimate_cost(width, height, n), ctx)
        body: dict[str, Any] = {"model": cfg["image_model"], "prompt": prompt[:1500], "n": min(9, n),
                                "aspect_ratio": _ratio(width, height, ["1:1", "16:9", "4:3", "3:2", "2:3", "3:4", "9:16", "21:9"]),
                                "response_format": "base64", "prompt_optimizer": False}
        if seed is not None:
            body["seed"] = int(seed)
        if refs:
            body["subject_reference"] = [{"type": "character", "image_file": data_uri(refs[0].convert("RGB"))}]
        async with client(300) as c:
            r = await c.post(f"{cfg['base_url'].rstrip('/')}/image_generation", json=body,
                             headers={"Authorization": f"Bearer {key}"})
        data = r.json() if r.status_code < 500 else {}
        imgs = (data.get("data") or {}).get("image_base64") or []
        if r.status_code >= 400 or not imgs:
            raise ProviderError(f"MiniMax 生图失败 {r.status_code}: {r.text[:400]}")
        if ctx is not None:
            ctx.add_cost(self.estimate_cost(width, height, n))
        return [b64_to_image(b) for b in imgs]


class MiniMaxVideoProvider(VideoProvider):
    name = "minimax"
    label = "MiniMax Hailuo 视频"
    lane = "cloud"
    supports_last_frame = True

    def _cfg(self) -> dict:
        return provider_cfg("minimax")

    async def health(self) -> dict[str, Any]:
        ok = bool(self._cfg().get("api_key"))
        return {"ok": ok, "detail": "已配置密钥" if ok else "未配置密钥"}

    def estimate_cost(self, seconds: float) -> float:
        return 0.045 * seconds

    async def animate(self, first: Image.Image, prompt: str, *, last=None, num_frames: int = 16, fps: int = 8,
                      width: int = 512, height: int = 512, seed=None, ctx: Any = None) -> list[Image.Image]:
        cfg = self._cfg()
        key = require(cfg, "api_key", "MiniMax")
        check_budget(self.estimate_cost(6), ctx)
        headers = {"Authorization": f"Bearer {key}"}
        base = cfg["base_url"].rstrip("/")
        body: dict[str, Any] = {"model": cfg["video_model"], "prompt": prompt, "duration": 6, "resolution": "768P",
                                "first_frame_image": data_uri(first.convert("RGB")), "prompt_optimizer": False}
        if last is not None:
            body["last_frame_image"] = data_uri(last.convert("RGB"))
        async with client(60) as c:
            r = await c.post(f"{base}/video_generation", json=body, headers=headers)
        task_id = r.json().get("task_id") if r.status_code < 400 else None
        if not task_id:
            raise ProviderError(f"Hailuo 提交失败 {r.status_code}: {r.text[:400]}")

        async def check():
            async with client(60) as c2:
                q = await c2.get(f"{base}/query/video_generation", params={"task_id": task_id}, headers=headers)
            data = q.json()
            if data.get("status") == "Success":
                return data["file_id"]
            if data.get("status") == "Fail":
                raise ProviderError(f"Hailuo 任务失败: {data}")
            return None

        file_id = await poll(check, interval=6, timeout=1200, ctx=ctx, label="Hailuo 生成视频")
        async with client(60) as c:
            f = await c.get(f"{base}/files/retrieve", params={"file_id": file_id}, headers=headers)
        url = f.json()["file"]["download_url"]
        if ctx is not None:
            ctx.add_cost(self.estimate_cost(6))
        return extract_frames(await fetch_bytes(url), num_frames)
