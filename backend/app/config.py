"""Runtime settings for SpriteKiln.

Settings are persisted in ``data/settings.json``. Secrets (API keys) are stored only
locally and are masked whenever they are sent to the browser.
"""
from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (stdlib only): KEY=VALUE, # comments, no interpolation. Existing env wins."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.environ.get("SPRITEKILN_DATA", ROOT / "data")).resolve()
PROJECTS_DIR = DATA_DIR / "projects"
TMP_DIR = DATA_DIR / "tmp"
WEB_DIST = ROOT / "web" / "dist"
WORKFLOW_DIR = ROOT / "backend" / "workflows"
SETTINGS_FILE = DATA_DIR / "settings.json"
MASK = "••••••"

for _d in (DATA_DIR, PROJECTS_DIR, TMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

DEFAULT_SETTINGS: dict[str, Any] = {
    "routing": {
        # auto = first healthy enabled provider in the preference list, else mock
        "image": "auto",
        "image_edit": "auto",
        "video": "auto",
        "llm": "auto",
        "threed": "auto",
        "bg": "auto",
    },
    "preference": {
        "image": ["comfyui", "openai", "ark", "minimax", "mock"],
        "image_edit": ["openai", "ark", "comfyui", "mock"],
        "video": ["comfyui", "ark", "minimax", "procedural"],
        "llm": ["llm_local", "openai", "ark", "minimax", "rules"],
        "threed": ["pixal3d", "mock"],
        "bg": ["birefnet", "chroma"],
    },
    "providers": {
        "comfyui": {
            "enabled": True,
            "base_url": os.environ.get("SPRITEKILN_COMFYUI_URL", "http://127.0.0.1:8188"),
            "image_workflow": "zimage_turbo_t2i",
            "img2img_workflow": "zimage_turbo_i2i",
            "video_workflow": "minimax_h3_fl2v",
            "video_steps": 8,
            "timeout": 1800,
        },
        "openai": {
            "enabled": False,
            "base_url": "https://api.openai.com/v1",
            "api_key": "",
            "image_model": "gpt-image-1",
            "llm_model": "gpt-4o-mini",
        },
        "ark": {
            "enabled": False,
            "base_url": "https://ark.cn-beijing.volces.com/api/v3",
            "api_key": "",
            "image_model": "doubao-seedream-4-0-250828",
            "video_model": "doubao-seedance-1-0-pro-250528",
            "llm_model": "doubao-seed-1-6-250615",
        },
        "minimax": {
            "enabled": False,
            "base_url": "https://api.minimaxi.com/v1",
            "api_key": "",
            "image_model": "image-01",
            "video_model": "MiniMax-Hailuo-02",
            "llm_model": "MiniMax-M1",
        },
        "llm_local": {
            "enabled": True,
            "base_url": os.environ.get("SPRITEKILN_LLM_URL", "http://127.0.0.1:11434/v1"),
            "api_key": os.environ.get("SPRITEKILN_LLM_KEY", "ollama"),
            "model": os.environ.get("SPRITEKILN_LLM_MODEL", "deepseek-r1:8b"),
        },
        "pixal3d": {
            # Empty by default: set them in 设置 or with SPRITEKILN_PIXAL3D_REPO / SPRITEKILN_PIXAL3D_PYTHON.
            # A missing/empty repo simply reports "not configured" and lets the 3D route fall back to mock.
            "enabled": bool(os.environ.get("SPRITEKILN_PIXAL3D_REPO")),
            "repo": os.environ.get("SPRITEKILN_PIXAL3D_REPO", ""),
            "python": os.environ.get("SPRITEKILN_PIXAL3D_PYTHON", ""),
            "low_vram": True,
            "resolution": 1024,
            "timeout": 2400,
        },
        "birefnet": {"enabled": True, "model": "ZhengPeng7/BiRefNet", "device": "auto"},
        "mock": {"enabled": True},
    },
    "budget": {"daily_cloud_usd": 5.0},
    "queue": {"gpu": 1, "cloud": 4, "cpu": 2},
    "godot": {"project_path": "", "asset_dir": "assets/spritekiln"},
}

SECRET_KEYS = {"api_key"}

_lock = threading.Lock()
_settings: dict[str, Any] | None = None


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def get_settings() -> dict[str, Any]:
    global _settings
    with _lock:
        if _settings is None:
            stored = {}
            if SETTINGS_FILE.exists():
                try:
                    stored = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    stored = {}
            _settings = _merge(DEFAULT_SETTINGS, stored)
        return _settings


def _strip_masked(patch: Any) -> Any:
    if isinstance(patch, dict):
        return {k: _strip_masked(v) for k, v in patch.items() if not (k in SECRET_KEYS and v == MASK)}
    return patch


def update_settings(patch: dict[str, Any]) -> dict[str, Any]:
    global _settings
    current = get_settings()
    with _lock:
        _settings = _merge(current, _strip_masked(patch))
        SETTINGS_FILE.write_text(json.dumps(_settings, ensure_ascii=False, indent=2), encoding="utf-8")
        return _settings


def public_settings() -> dict[str, Any]:
    def mask(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: (MASK if k in SECRET_KEYS and v else mask(v)) for k, v in obj.items()}
        return obj

    return mask(copy.deepcopy(get_settings()))


def provider_cfg(name: str) -> dict[str, Any]:
    return get_settings()["providers"].get(name, {})
