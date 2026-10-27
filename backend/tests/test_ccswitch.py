"""cc-switch discovery, LLM preference order and configurable ComfyUI model files."""
import asyncio
import copy
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("SPRITEKILN_DATA", tempfile.mkdtemp(prefix="spritekiln_test_"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import providers  # noqa: E402
from app.config import DEFAULT_SETTINGS, _migrate, update_settings  # noqa: E402
from app.providers import ccswitch  # noqa: E402
from app.providers.comfyui import apply_model_overrides, load_workflow, patch  # noqa: E402


def make_ccswitch_db(path: Path, *, current: bool = True, proxy: bool = True,
                     catalog_model: str | None = None) -> None:
    config = 'model_provider = "custom"\nmodel = "deepseek-v4-pro"\n'
    settings_config = {"auth": {"OPENAI_API_KEY": "should-never-be-read"}, "config": config}
    if catalog_model:
        settings_config["modelCatalog"] = {"models": [{"model": catalog_model}]}
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE providers (id TEXT, app_type TEXT, name TEXT, settings_config TEXT, "
                 "is_current INTEGER, sort_index INTEGER)")
    conn.execute("CREATE TABLE proxy_config (app_type TEXT, enabled INTEGER, listen_address TEXT, listen_port INTEGER)")
    conn.execute("INSERT INTO proxy_config VALUES ('codex', ?, '127.0.0.1', 15799)", (1 if proxy else 0,))
    conn.execute("INSERT INTO providers VALUES ('p1', 'codex', 'DeepSeek', ?, ?, 0)",
                 (json.dumps(settings_config), 1 if current else 0))
    conn.commit()
    conn.close()


def test_discovers_current_codex_provider(monkeypatch, tmp_path):
    db = tmp_path / "cc-switch.db"
    make_ccswitch_db(db)
    monkeypatch.setenv("SPRITEKILN_CCSWITCH_DB", str(db))
    ccswitch.clear_cache()
    info = ccswitch.discover(force=True)
    assert info["ok"], info
    assert info["model"] == "deepseek-v4-pro"
    assert info["provider"] == "DeepSeek"
    assert info["base_url"] == "http://127.0.0.1:15799/v1"
    assert "should-never-be-read" not in json.dumps(info)


def test_model_catalog_wins_over_toml(monkeypatch, tmp_path):
    db = tmp_path / "cc-switch.db"
    make_ccswitch_db(db, catalog_model="deepseek-v4-flash")
    monkeypatch.setenv("SPRITEKILN_CCSWITCH_DB", str(db))
    ccswitch.clear_cache()
    assert ccswitch.discover(force=True)["model"] == "deepseek-v4-flash"


def test_missing_or_disabled_proxy_is_unhealthy(monkeypatch, tmp_path):
    db = tmp_path / "cc-switch.db"
    make_ccswitch_db(db, proxy=False)
    monkeypatch.setenv("SPRITEKILN_CCSWITCH_DB", str(db))
    ccswitch.clear_cache()
    info = ccswitch.discover(force=True)
    assert not info["ok"] and "代理未开启" in info["detail"]

    monkeypatch.setenv("SPRITEKILN_CCSWITCH_DB", str(tmp_path / "nope.db"))
    ccswitch.clear_cache()
    assert not ccswitch.discover(force=True)["ok"]


def test_settings_migration_puts_ccswitch_first_once():
    merged = copy.deepcopy(DEFAULT_SETTINGS)
    merged["preference"]["llm"] = ["llm_local", "openai", "rules"]
    merged.pop("schema", None)
    out = _migrate(merged, {})
    assert out["preference"]["llm"][:2] == ["ccswitch", "llm_local"]
    assert out["schema"] == 2

    # A v2 file keeps a deliberate removal.
    kept = copy.deepcopy(DEFAULT_SETTINGS)
    kept["preference"]["llm"] = ["llm_local", "rules"]
    _migrate(kept, {"schema": 2})
    assert "ccswitch" not in kept["preference"]["llm"]


def test_llm_route_prefers_ccswitch_then_local(monkeypatch):
    update_settings({"routing": {"llm": "auto"},
                     "preference": {"llm": ["ccswitch", "llm_local", "openai", "ark", "minimax", "rules"]}})

    async def fake_health(kind, name, force=False):
        return {"ok": name == "ccswitch", "label": name, "lane": "cloud"}

    monkeypatch.setattr(providers, "health_of", fake_health)
    assert asyncio.run(providers.resolve("llm")) == "ccswitch"

    async def no_ccswitch(kind, name, force=False):
        return {"ok": name == "llm_local", "label": name, "lane": "gpu"}

    monkeypatch.setattr(providers, "health_of", no_ccswitch)
    assert asyncio.run(providers.resolve("llm")) == "llm_local"


def test_comfyui_model_overrides_keep_defaults_when_empty():
    graph, fmap = load_workflow("zimage_turbo_t2i")
    g = patch(graph, fmap, {"prompt": "slime"})
    apply_model_overrides(g, fmap, {"image_model": "custom/unet.safetensors", "text_encoder": "", "vae": "vae/x.safetensors"})
    assert g["28"]["inputs"]["unet_name"] == "custom/unet.safetensors"
    assert g["29"]["inputs"]["vae_name"] == "vae/x.safetensors"
    assert g["30"]["inputs"]["clip_name"] == "qwen_3_4b.safetensors"

    video, vmap = load_workflow("minimax_h3_fl2v")
    vg = patch(video, vmap, {"prompt": "run"})
    apply_model_overrides(vg, vmap, {"video_model": "h3_custom.safetensors", "video_lora": ""})
    assert vg["1"]["inputs"]["unet_name"] == "h3_custom.safetensors"
    assert "minimax_h3_turbo" in vg["2"]["inputs"]["lora_name"]
