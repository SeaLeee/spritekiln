"""Provider interfaces. Every model backend (local or cloud) implements one or more of these."""
from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from PIL import Image


class ProviderError(RuntimeError):
    pass


class NotSupported(ProviderError):
    pass


class Provider:
    name = "base"
    label = "base"
    lane = "cpu"  # gpu | cloud | cpu

    async def health(self) -> dict[str, Any]:
        return {"ok": True, "detail": "内置，始终可用"}


class ImageProvider(Provider):
    supports_refs = False
    supports_edit = False
    native_transparency = False

    async def generate(self, prompt: str, *, width: int = 1024, height: int = 1024, n: int = 1,
                       seed: int | None = None, refs: list[Image.Image] | None = None, negative: str = "",
                       quality: str = "standard", transparent: bool = False, layout: tuple[int, int] | None = None,
                       ctx: Any = None) -> list[Image.Image]:
        raise NotSupported(f"{self.name} cannot generate images")

    async def edit(self, image: Image.Image, prompt: str, *, refs: list[Image.Image] | None = None,
                   mask: Image.Image | None = None, strength: float = 0.65, seed: int | None = None,
                   width: int | None = None, height: int | None = None, ctx: Any = None) -> list[Image.Image]:
        raise NotSupported(f"{self.name} cannot edit images")

    def estimate_cost(self, width: int, height: int, n: int = 1) -> float:
        return 0.0


class VideoProvider(Provider):
    supports_last_frame = False

    async def animate(self, first: Image.Image, prompt: str, *, last: Image.Image | None = None,
                      num_frames: int = 16, fps: int = 8, width: int = 512, height: int = 512,
                      seed: int | None = None, ctx: Any = None) -> list[Image.Image]:
        raise NotSupported(f"{self.name} cannot animate")

    def estimate_cost(self, seconds: float) -> float:
        return 0.0


class LLMProvider(Provider):
    async def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.4, json_mode: bool = False,
                   max_tokens: int = 2048) -> str:
        raise NotSupported(f"{self.name} cannot chat")

    async def chat_stream(self, messages: list[dict[str, str]], *, temperature: float = 0.4,
                          json_mode: bool = False, max_tokens: int = 2048) -> AsyncIterator[tuple[str, str]]:
        """Yield ``(kind, delta)`` with kind ``reasoning`` or ``content``.

        Providers without real streaming fall back to one full-content chunk, so callers
        can use the same code path and still render progressive feedback where available.
        """
        text = await self.chat(messages, temperature=temperature, json_mode=json_mode, max_tokens=max_tokens)
        if text:
            yield "content", text


class ThreeDProvider(Provider):
    async def image_to_3d(self, image: Image.Image, out_dir: Path, *, seed: int = 42, quality: str = "standard",
                          ctx: Any = None) -> Path:
        raise NotSupported(f"{self.name} cannot create 3D")
