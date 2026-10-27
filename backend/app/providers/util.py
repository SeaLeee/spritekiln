"""Shared helpers for providers: http, base64 images, video frame extraction, budget."""
from __future__ import annotations

import base64
import io
import time
from datetime import datetime
from pathlib import Path

import httpx
from PIL import Image

from .. import db
from ..config import get_settings
from .base import ProviderError


def client(timeout: float = 180.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=15.0), trust_env=True, follow_redirects=True)


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def data_uri(img: Image.Image) -> str:
    return "data:image/png;base64," + base64.b64encode(png_bytes(img)).decode()


def b64_to_image(data: str) -> Image.Image:
    if data.startswith("data:"):
        data = data.split(",", 1)[1]
    return Image.open(io.BytesIO(base64.b64decode(data))).convert("RGBA")


async def fetch_image(url: str) -> Image.Image:
    async with client() as c:
        r = await c.get(url)
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert("RGBA")


async def fetch_bytes(url: str, timeout: float = 300) -> bytes:
    async with client(timeout) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.content


def extract_frames(video: bytes | Path, num_frames: int, skip_head: float = 0.0) -> list[Image.Image]:
    """Evenly sample ``num_frames`` frames from a video (mp4/webm/gif)."""
    import av

    src = io.BytesIO(video) if isinstance(video, (bytes, bytearray)) else str(video)
    with av.open(src) as container:
        frames = [f.to_image().convert("RGBA") for f in container.decode(video=0)]
    if not frames:
        raise ProviderError("video contains no frames")
    start = int(len(frames) * skip_head)
    frames = frames[start:] or frames
    if num_frames >= len(frames):
        return frames
    step = len(frames) / num_frames
    return [frames[min(len(frames) - 1, int(i * step))] for i in range(num_frames)]


def require(cfg: dict, key: str, provider: str) -> str:
    val = cfg.get(key)
    if not val:
        raise ProviderError(f"{provider}: 未配置 {key}，请在 设置 → 模型服务 中填写")
    return val


def spent_today() -> float:
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    rows = db.query("SELECT COALESCE(SUM(cost_usd),0) AS s FROM jobs WHERE created_at>=?", (start,))
    return float(rows[0]["s"] or 0)


def check_budget(estimate: float, ctx=None) -> None:
    limit = float(get_settings()["budget"].get("daily_cloud_usd") or 0)
    if limit <= 0:
        return
    pending = ctx.cost_usd if ctx is not None else 0.0
    if spent_today() + pending + estimate > limit:
        raise ProviderError(f"超出每日云端预算 ${limit:.2f}（今日已用 ${spent_today():.2f}），可在设置中调整")


async def poll(fn, *, interval: float = 4.0, timeout: float = 900.0, ctx=None, label: str = "生成中"):
    """Call async ``fn`` until it returns a non-None value."""
    t0 = time.time()
    while True:
        if ctx is not None:
            ctx.check()
        res = await fn()
        if res is not None:
            return res
        elapsed = time.time() - t0
        if elapsed > timeout:
            raise ProviderError("云端任务超时")
        if ctx is not None:
            ctx.progress(min(0.9, 0.2 + elapsed / timeout), f"{label}… {int(elapsed)}s")
        import asyncio
        await asyncio.sleep(interval)
