"""OpenAI-compatible providers: GPT Image (generate/edit) and chat LLM (OpenAI / Ollama / LM Studio / any compatible)."""
from __future__ import annotations

import re
from typing import Any

from PIL import Image

from ..config import provider_cfg
from .base import ImageProvider, LLMProvider, ProviderError
from .util import b64_to_image, check_budget, client, fetch_image, png_bytes, require

GPT_SIZES = [(1024, 1024), (1536, 1024), (1024, 1536)]
QUALITY = {"standard": "low", "detailed": "medium", "ultimate": "high"}
PRICE = {"low": 0.011, "medium": 0.042, "high": 0.167}


def closest_size(w: int, h: int) -> str:
    ar = w / h
    best = min(GPT_SIZES, key=lambda s: abs(s[0] / s[1] - ar))
    return f"{best[0]}x{best[1]}"


class OpenAIImageProvider(ImageProvider):
    name = "openai"
    label = "OpenAI GPT Image (兼容接口)"
    lane = "cloud"
    supports_refs = True
    supports_edit = True
    native_transparency = True

    def _cfg(self) -> dict:
        return provider_cfg("openai")

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {require(self._cfg(), 'api_key', 'OpenAI')}"}

    def estimate_cost(self, width: int, height: int, n: int = 1, quality: str = "standard") -> float:
        return PRICE[QUALITY.get(quality, "low")] * n * (1.5 if width != height else 1)

    async def health(self) -> dict[str, Any]:
        return {"ok": bool(self._cfg().get("api_key")), "detail": "已配置密钥" if self._cfg().get("api_key") else "未配置密钥"}

    async def _parse(self, data: dict) -> list[Image.Image]:
        out = []
        for item in data.get("data", []):
            if item.get("b64_json"):
                out.append(b64_to_image(item["b64_json"]))
            elif item.get("url"):
                out.append(await fetch_image(item["url"]))
        if not out:
            raise ProviderError(f"OpenAI 返回为空: {str(data)[:300]}")
        return out

    async def generate(self, prompt: str, *, width: int = 1024, height: int = 1024, n: int = 1, seed=None,
                       refs=None, negative: str = "", quality: str = "standard", transparent: bool = False,
                       layout=None, ctx: Any = None) -> list[Image.Image]:
        cfg = self._cfg()
        check_budget(self.estimate_cost(width, height, n, quality), ctx)
        if refs:
            return await self._edit_call(refs, prompt, None, width, height, n, quality, transparent, ctx)
        body = {"model": cfg.get("image_model", "gpt-image-1"), "prompt": prompt, "n": n,
                "size": closest_size(width, height), "quality": QUALITY.get(quality, "low")}
        if transparent:
            body["background"] = "transparent"
        async with client(300) as c:
            r = await c.post(f"{cfg['base_url'].rstrip('/')}/images/generations", json=body, headers=self._headers())
        if r.status_code >= 400:
            raise ProviderError(f"OpenAI 生图失败 {r.status_code}: {r.text[:400]}")
        if ctx is not None:
            ctx.add_cost(self.estimate_cost(width, height, n, quality))
        return await self._parse(r.json())

    async def _edit_call(self, images: list[Image.Image], prompt: str, mask: Image.Image | None, width: int,
                         height: int, n: int, quality: str, transparent: bool, ctx) -> list[Image.Image]:
        cfg = self._cfg()
        files: list[tuple[str, tuple[str, bytes, str]]] = []
        for i, im in enumerate(images[:16]):
            files.append(("image[]", (f"ref{i}.png", png_bytes(im.convert("RGBA")), "image/png")))
        if mask is not None:
            # OpenAI mask semantics: transparent pixels = area to edit
            m = mask.convert("L").resize(images[0].size)
            rgba = Image.new("RGBA", m.size, (0, 0, 0, 255))
            rgba.putalpha(m.point(lambda v: 0 if v > 127 else 255))
            files.append(("mask", ("mask.png", png_bytes(rgba), "image/png")))
        data = {"model": cfg.get("image_model", "gpt-image-1"), "prompt": prompt, "n": str(n),
                "size": closest_size(width, height), "quality": QUALITY.get(quality, "low")}
        if transparent:
            data["background"] = "transparent"
        async with client(300) as c:
            r = await c.post(f"{cfg['base_url'].rstrip('/')}/images/edits", data=data, files=files,
                             headers=self._headers())
        if r.status_code >= 400:
            raise ProviderError(f"OpenAI 编辑失败 {r.status_code}: {r.text[:400]}")
        if ctx is not None:
            ctx.add_cost(self.estimate_cost(width, height, n, quality))
        return await self._parse(r.json())

    async def edit(self, image: Image.Image, prompt: str, *, refs=None, mask=None, strength: float = 0.65,
                   seed=None, width=None, height=None, ctx: Any = None) -> list[Image.Image]:
        check_budget(self.estimate_cost(image.width, image.height, 1), ctx)
        return await self._edit_call([image, *(refs or [])], prompt, mask, width or image.width,
                                     height or image.height, 1, "detailed", False, ctx)


THINK_RE = re.compile(r"<think>.*?</think>", re.S)


class OpenAICompatLLM(LLMProvider):
    """Chat completions on any OpenAI-compatible endpoint (OpenAI, Ollama, LM Studio, Ark, MiniMax...)."""

    def __init__(self, name: str, label: str, cfg_name: str, model_key: str = "model", lane: str = "cloud"):
        self.name = name
        self.label = label
        self.cfg_name = cfg_name
        self.model_key = model_key
        self.lane = lane

    def _cfg(self) -> dict:
        return provider_cfg(self.cfg_name)

    async def health(self) -> dict[str, Any]:
        cfg = self._cfg()
        if self.lane != "gpu":
            ok = bool(cfg.get("api_key"))
            return {"ok": ok, "detail": "已配置密钥" if ok else "未配置密钥"}
        try:
            async with client(4) as c:
                r = await c.get(f"{cfg['base_url'].rstrip('/')}/models")
            models = [m.get("id") for m in r.json().get("data", [])] if r.status_code == 200 else []
            ok = r.status_code == 200 and (not models or cfg.get(self.model_key) in models)
            return {"ok": ok, "detail": f"模型: {', '.join(models[:6])}" if models else f"HTTP {r.status_code}",
                    "models": models}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "detail": f"无法连接: {type(exc).__name__}"}

    async def chat(self, messages, *, temperature: float = 0.4, json_mode: bool = False, max_tokens: int = 2048) -> str:
        cfg = self._cfg()
        headers = {"Authorization": f"Bearer {cfg.get('api_key') or 'none'}"}
        body: dict[str, Any] = {"model": cfg.get(self.model_key), "messages": messages, "temperature": temperature,
                                "max_tokens": max_tokens, "stream": False}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        async with client(600) as c:
            r = await c.post(f"{cfg['base_url'].rstrip('/')}/chat/completions", json=body, headers=headers)
            if r.status_code >= 400 and json_mode:
                body.pop("response_format", None)
                r = await c.post(f"{cfg['base_url'].rstrip('/')}/chat/completions", json=body, headers=headers)
        if r.status_code >= 400:
            raise ProviderError(f"{self.label} 调用失败 {r.status_code}: {r.text[:300]}")
        content = r.json()["choices"][0]["message"].get("content") or ""
        return THINK_RE.sub("", content).strip()
