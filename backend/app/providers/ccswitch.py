"""cc-switch integration: the local cc-switch proxy as the preferred LLM.

cc-switch is a Tauri app that switches the provider used by Claude Code / Codex. When its
Codex proxy is enabled it exposes an OpenAI-compatible chat endpoint that forwards to the
*currently selected* provider and injects that provider's credential itself.

SpriteKiln reads `~/.cc-switch/cc-switch.db` **read-only** to learn the proxy port and the
current provider's model name. It never copies API keys: the proxy owns them. If the proxy
is off (or cc-switch is not installed) the provider reports unhealthy and routing falls
through to the next entry in `preference.llm` (local Ollama by default).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from ..config import provider_cfg
from .base import LLMProvider, ProviderError
from .util import client, openai_sse_deltas

DEFAULT_PORT = 15721
CACHE_TTL = 10.0
_model_re = re.compile(r'(?m)^\s*model\s*=\s*"([^"]+)"')
_cache: tuple[float, dict[str, Any]] | None = None


def db_path() -> Path:
    """Where cc-switch keeps its SQLite DB. Overridable for tests / non-default installs."""
    explicit = os.environ.get("SPRITEKILN_CCSWITCH_DB")
    if explicit:
        return Path(explicit).expanduser()
    base = os.environ.get("CCSWITCH_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".cc-switch"
    return root / "cc-switch.db"


def _connect(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=2)


def _model_from_settings_config(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        cfg = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return ""
    catalog = cfg.get("modelCatalog") or {}
    for item in catalog.get("models") or []:
        if isinstance(item, dict) and item.get("model"):
            return str(item["model"])
    text = cfg.get("config")
    if isinstance(text, str):
        m = _model_re.search(text)
        if m:
            return m.group(1)
    return ""


def _discover() -> dict[str, Any]:
    cfg = provider_cfg("ccswitch")
    base_override = str(cfg.get("base_url") or "").strip().rstrip("/")
    model_override = str(cfg.get("model") or "").strip()
    path = db_path()

    proxy_enabled = False
    base_url = base_override
    provider_name = ""
    db_model = ""
    error = ""

    if path.is_file():
        try:
            with closing(_connect(path)) as conn:
                prow = conn.execute(
                    "SELECT enabled, listen_address, listen_port FROM proxy_config WHERE app_type='codex' LIMIT 1"
                ).fetchone()
                if prow:
                    proxy_enabled = bool(prow[0])
                    addr = str(prow[1] or "127.0.0.1")
                    if addr in ("0.0.0.0", "::"):
                        addr = "127.0.0.1"
                    port = int(prow[2] or DEFAULT_PORT)
                    if not base_url and proxy_enabled:
                        base_url = f"http://{addr}:{port}/v1"
                row = conn.execute(
                    "SELECT name, settings_config FROM providers "
                    "WHERE app_type='codex' AND is_current=1 ORDER BY sort_index LIMIT 1"
                ).fetchone()
                if row:
                    provider_name = str(row[0] or "")
                    db_model = _model_from_settings_config(row[1])
        except Exception as exc:  # noqa: BLE001 — DB locked/old schema must not break the app
            error = f"{type(exc).__name__}: {exc}"

    if not base_url and proxy_enabled:
        base_url = f"http://127.0.0.1:{DEFAULT_PORT}/v1"
    model = model_override or db_model
    # A custom base_url + model is enough even without a readable DB (e.g. another local proxy).
    usable = bool(base_url and model and (proxy_enabled or base_override))

    if usable:
        detail = f"{provider_name or 'cc-switch'} · {model}"
        if base_override:
            detail += "（自定义地址）"
    elif not path.is_file():
        detail = f"未找到 cc-switch 数据库（{path}）"
    elif error:
        detail = f"读取 cc-switch 失败：{error}"
    elif not proxy_enabled:
        detail = "cc-switch 的 Codex 本地代理未开启"
    elif not provider_name:
        detail = "cc-switch 没有当前 Codex provider"
    else:
        detail = f"未读到模型名（{provider_name}）"

    return {"ok": usable, "base_url": base_url, "model": model, "provider": provider_name,
            "proxy": proxy_enabled, "db": str(path), "detail": detail}


def discover(force: bool = False) -> dict[str, Any]:
    """Cached (10 s) view of cc-switch's live selection. Never returns API keys."""
    global _cache
    now = time.time()
    if not force and _cache and now - _cache[0] < CACHE_TTL:
        return _cache[1]
    info = _discover()
    _cache = (now, info)
    return info


def clear_cache() -> None:
    global _cache
    _cache = None


class CcSwitchLLM(LLMProvider):
    name = "ccswitch"
    label = "cc-switch 本地代理（首选）"
    lane = "cloud"

    async def health(self) -> dict[str, Any]:
        info = discover(force=True)
        if not info["ok"]:
            return {"ok": False, "detail": info["detail"]}
        try:
            async with client(4) as c:
                r = await c.get(f"{info['base_url']}/models")
            if r.status_code != 200:
                return {"ok": False, "detail": f"代理 HTTP {r.status_code}：{info['detail']}"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "detail": f"连不上 cc-switch 代理（{type(exc).__name__}）：{info['detail']}"}
        return {"ok": True, "detail": info["detail"], "model": info["model"], "base_url": info["base_url"]}

    async def chat(self, messages, *, temperature: float = 0.4, json_mode: bool = False, max_tokens: int = 2048) -> str:
        info = discover()
        if not info["ok"]:
            raise ProviderError(f"cc-switch 不可用：{info['detail']}")
        cfg = provider_cfg("ccswitch")
        headers = {"Authorization": f"Bearer {cfg.get('api_key') or 'PROXY_MANAGED'}"}
        body: dict[str, Any] = {"model": info["model"], "messages": messages, "temperature": temperature,
                                "max_tokens": max_tokens, "stream": False}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        url = f"{info['base_url']}/chat/completions"
        async with client(float(cfg.get("timeout") or 600)) as c:
            r = await c.post(url, json=body, headers=headers)
            if r.status_code >= 400 and json_mode:
                # Some upstreams behind the proxy reject response_format; retry as plain chat.
                body.pop("response_format", None)
                r = await c.post(url, json=body, headers=headers)
        if r.status_code >= 400:
            raise ProviderError(f"cc-switch 调用失败 {r.status_code}: {r.text[:300]}")
        message = (r.json().get("choices") or [{}])[0].get("message") or {}
        content = message.get("content") or message.get("reasoning_content") or ""
        return content.strip()

    async def chat_stream(self, messages, *, temperature: float = 0.4, json_mode: bool = False,
                          max_tokens: int = 2048):
        """Stream reasoning + content deltas so the UI can show progress while it thinks."""
        info = discover()
        if not info["ok"]:
            raise ProviderError(f"cc-switch 不可用：{info['detail']}")
        cfg = provider_cfg("ccswitch")
        headers = {"Authorization": f"Bearer {cfg.get('api_key') or 'PROXY_MANAGED'}"}
        url = f"{info['base_url']}/chat/completions"
        async with client(float(cfg.get("timeout") or 600)) as c:
            for attempt in range(2 if json_mode else 1):
                body: dict[str, Any] = {"model": info["model"], "messages": messages, "temperature": temperature,
                                        "max_tokens": max_tokens, "stream": True}
                if json_mode and attempt == 0:
                    body["response_format"] = {"type": "json_object"}
                async with c.stream("POST", url, json=body, headers=headers) as r:
                    if r.status_code >= 400:
                        detail = (await r.aread()).decode("utf-8", "replace")[:300]
                        if attempt == 0 and json_mode:
                            continue  # upstream rejected response_format; retry as plain chat
                        raise ProviderError(f"cc-switch 调用失败 {r.status_code}: {detail}")
                    async for kind, delta in openai_sse_deltas(r):
                        yield kind, delta
                    return
