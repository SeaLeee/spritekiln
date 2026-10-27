"""Provider registry, health checks and routing (auto → first healthy provider in the preference list)."""
from __future__ import annotations

import asyncio
import time
from typing import Any

from ..config import get_settings, provider_cfg
from .base import ImageProvider, LLMProvider, Provider, ProviderError, ThreeDProvider, VideoProvider
from .ccswitch import CcSwitchLLM
from .cloud import ArkImageProvider, ArkVideoProvider, MiniMaxImageProvider, MiniMaxVideoProvider
from .comfyui import ComfyImageProvider, ComfyVideoProvider
from .mock import MockImageProvider, MockThreeDProvider, ProceduralVideoProvider, RulesLLM
from .openai_compat import OpenAICompatLLM, OpenAIImageProvider
from .pixal3d import Pixal3DProvider


class BgProvider(Provider):
    def __init__(self, name: str, label: str, lane: str):
        self.name, self.label, self.lane = name, label, lane

    async def health(self) -> dict[str, Any]:
        if self.name == "birefnet":
            from ..pixel.bg import birefnet
            ok = birefnet.available()
            return {"ok": ok, "detail": "本地 BiRefNet 权重已缓存" if ok else (birefnet.error or "未找到权重")[:120]}
        return {"ok": True, "detail": "纯色/洪水填充抠图"}


REGISTRY: dict[str, dict[str, Provider]] = {
    "image": {"comfyui": ComfyImageProvider(), "openai": OpenAIImageProvider(), "ark": ArkImageProvider(),
              "minimax": MiniMaxImageProvider(), "mock": MockImageProvider()},
    "video": {"comfyui": ComfyVideoProvider(), "ark": ArkVideoProvider(), "minimax": MiniMaxVideoProvider(),
              "procedural": ProceduralVideoProvider()},
    "llm": {"ccswitch": CcSwitchLLM(),
            "llm_local": OpenAICompatLLM("llm_local", "本地大模型 (Ollama/LM Studio)", "llm_local", "model", lane="gpu"),
            "openai": OpenAICompatLLM("openai", "OpenAI Chat", "openai", "llm_model"),
            "ark": OpenAICompatLLM("ark", "火山方舟 豆包", "ark", "llm_model"),
            "minimax": OpenAICompatLLM("minimax", "MiniMax Chat", "minimax", "llm_model"),
            "rules": RulesLLM()},
    "threed": {"pixal3d": Pixal3DProvider(), "mock": MockThreeDProvider()},
    "bg": {"birefnet": BgProvider("birefnet", "BiRefNet 本地神经抠图", "cpu"),
           "chroma": BgProvider("chroma", "纯色键控/洪水填充", "cpu")},
}
REGISTRY["image_edit"] = REGISTRY["image"]

_health_cache: dict[tuple[str, str], tuple[float, dict]] = {}
HEALTH_TTL = 15.0


async def health_of(kind: str, name: str, force: bool = False) -> dict[str, Any]:
    key = (kind, name)
    hit = _health_cache.get(key)
    if hit and not force and time.time() - hit[0] < HEALTH_TTL:
        return hit[1]
    prov = REGISTRY[kind][name]
    cfg_name = getattr(prov, "cfg_name", name)
    cfg = provider_cfg(cfg_name)
    if cfg and cfg.get("enabled") is False:
        res = {"ok": False, "detail": "已禁用"}
    else:
        try:
            res = await asyncio.wait_for(prov.health(), timeout=6)
        except Exception as exc:  # noqa: BLE001
            res = {"ok": False, "detail": f"{type(exc).__name__}"}
    res = {**res, "label": prov.label, "lane": prov.lane}
    _health_cache[key] = (time.time(), res)
    return res


async def all_health(force: bool = False) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    tasks = []
    for kind, provs in REGISTRY.items():
        if kind == "image_edit":
            continue
        for name in provs:
            tasks.append((kind, name, health_of(kind, name, force)))
    results = await asyncio.gather(*(t[2] for t in tasks))
    for (kind, name, _), res in zip(tasks, results):
        out.setdefault(kind, {})[name] = res
    return out


async def resolve(kind: str, override: str | None = None) -> str:
    provs = REGISTRY[kind]
    if override and override != "auto":
        if override not in provs:
            raise ProviderError(f"未知的 {kind} 提供方: {override}")
        return override
    s = get_settings()
    routed = s["routing"].get(kind, "auto")
    if routed and routed != "auto" and routed in provs:
        return routed
    for name in s["preference"].get(kind, list(provs)):
        if name in provs and (await health_of(kind, name))["ok"]:
            if kind == "image_edit" and not getattr(provs[name], "supports_edit", False):
                continue
            return name
    return list(provs)[-1]


async def resolve_providers(needs: list[str], params: dict[str, Any]) -> dict[str, str]:
    out = {}
    for kind in needs:
        override = params.get(f"{kind}_provider") or (params.get("provider") if kind in ("image", "image_edit") else None)
        if kind == "video":
            override = params.get("video_provider")
        if kind == "threed":
            override = params.get("threed_provider")
        if kind == "bg":
            m = params.get("bg_method") or params.get("remove_bg") or params.get("method")
            override = m if m in ("birefnet", "chroma") else None
        out[kind] = await resolve(kind, override)
    return out


def resolve_lane(providers: dict[str, str]) -> str:
    lanes = {REGISTRY[k][v].lane for k, v in providers.items() if k in REGISTRY and v in REGISTRY[k]}
    if "gpu" in lanes:
        return "gpu"
    if "cloud" in lanes:
        return "cloud"
    return "cpu"


def get_provider(kind: str, name: str | None):
    provs = REGISTRY[kind]
    if name and name in provs:
        return provs[name]
    return provs[list(provs)[-1]]


__all__ = ["ImageProvider", "VideoProvider", "LLMProvider", "ThreeDProvider", "ProviderError", "REGISTRY",
           "resolve", "resolve_providers", "resolve_lane", "get_provider", "all_health", "health_of"]
