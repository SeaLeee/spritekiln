#!/usr/bin/env python3
"""Static + runtime checks for a SpriteKiln install. Standard library only.

  python check_setup.py            # human-readable
  python check_setup.py --json     # machine-readable
  python check_setup.py --require-server
  python check_setup.py --url http://127.0.0.1:7788

Never reads data/settings.json, so API keys are never printed.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

MODULES = {
    "fastapi": True,
    "uvicorn": True,
    "pydantic": True,
    "multipart": True,
    "PIL": True,
    "numpy": True,
    "scipy": True,
    "av": False,  # only video_gen / mp4 export needs it
}


def find_root() -> Path | None:
    here = Path(__file__).resolve()
    for p in [here, *here.parents]:
        if (p / "backend" / "app" / "main.py").is_file():
            return p
    return None


def cmd_version(name: str) -> str | None:
    exe = shutil.which(name)
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=8)
        return (out.stdout or out.stderr).strip().splitlines()[0][:80] or "present"
    except Exception:  # noqa: BLE001
        return "present"


def get_json(url: str, timeout: float) -> tuple[bool, dict | str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return True, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("SPRITEKILN_URL", "http://127.0.0.1:7788"))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--require-server", action="store_true")
    a = ap.parse_args()
    url = a.url.rstrip("/")

    root = find_root()
    warnings: list[str] = []
    next_steps: list[str] = []

    py_ok = sys.version_info >= (3, 10)
    if not py_ok:
        next_steps.append("安装 Python 3.10+ 并重建 venv")

    modules = {name: importlib.util.find_spec(name) is not None for name in MODULES}
    missing_required = [n for n, required in MODULES.items() if required and not modules[n]]
    if missing_required:
        next_steps.append("pip install -r backend/requirements.txt（缺少 " + ", ".join(missing_required) + "）")
    missing_optional = [n for n, required in MODULES.items() if not required and not modules[n]]
    if missing_optional:
        warnings.append("可选依赖未安装：" + ", ".join(missing_optional) + "（影响视频导出）")

    node_version = cmd_version("node")
    npm_version = cmd_version("npm")
    if not node_version:
        warnings.append("未找到 Node.js：只影响前端构建，已构建的 web/dist 仍可运行")

    dist_ok = bool(root and (root / "web" / "dist" / "index.html").is_file())
    if not dist_ok:
        next_steps.append("构建前端：cd web && npm ci && npm run build")

    data_dir = Path(os.environ.get("SPRITEKILN_DATA") or (root / "data" if root else "./data")).resolve()
    data_writable = False
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        data_writable = True
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"数据目录不可写 {data_dir}: {type(exc).__name__}")

    env_file = bool(root and (root / ".env").is_file())

    server_ok, system = get_json(f"{url}/api/system", 5)
    health_ok, health = get_json(f"{url}/api/health?force=true", 30)
    routes = health.get("routes", {}) if health_ok and isinstance(health, dict) else {}
    unhealthy: list[str] = []
    disabled: list[str] = []
    if health_ok and isinstance(health, dict):
        for kind, provs in (health.get("providers") or {}).items():
            for name, info in provs.items():
                if info.get("ok"):
                    continue
                detail = str(info.get("detail", "")).strip()
                # disabled providers are an intentional config, not a fault — reporting them as
                # "unhealthy" trains the user to ignore the check (false warnings are worse than none)
                if detail in ("已禁用", "disabled"):
                    disabled.append(f"{kind}.{name}")
                else:
                    unhealthy.append(f"{kind}.{name}: {detail[:80]}")
    if not server_ok:
        next_steps.append("启动服务：python backend/run.py（或 .\\start.ps1 -NoComfy）")

    fallback = [kind for kind, name in routes.items()
                if name in ("mock", "procedural", "rules", "chroma")]
    if fallback:
        warnings.append("以下任务当前走离线兜底引擎：" + ", ".join(fallback) + "（产物仅用于验证流程）")

    core_ok = bool(root and py_ok and not missing_required)
    result = {
        "root": str(root) if root else None,
        "platform": platform.platform(),
        "python": {"version": platform.python_version(), "ok": py_ok},
        "modules": modules,
        "node": node_version,
        "npm": npm_version,
        "frontend_built": dist_ok,
        "data_dir": str(data_dir),
        "data_writable": data_writable,
        "env_file": env_file,
        "server": {"url": url, "ok": server_ok, "system": system if server_ok else system,
                   "health_ok": health_ok, "routes": routes, "unhealthy": unhealthy, "disabled": disabled},
        "core_ok": core_ok,
        "warnings": warnings,
        "next": next_steps,
    }

    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        mark = lambda ok: "OK  " if ok else "FAIL"  # noqa: E731
        print(f"SpriteKiln setup check  ({platform.system()} / Python {platform.python_version()})")
        print(f"repo: {root or '未找到（请在仓库内运行）'}")
        print(f"{mark(py_ok)} Python >= 3.10")
        for name in MODULES:
            if modules[name]:
                print(f"OK   import {name}")
            elif MODULES[name]:
                print(f"FAIL import {name}")
            else:
                print(f"WARN import {name}（可选）")
        print(f"{'OK  ' if node_version else 'WARN'} node: {node_version or '未安装'}")
        print(f"{'OK  ' if dist_ok else 'WARN'} web/dist: {'已构建' if dist_ok else '未构建'}")
        print(f"{'OK  ' if data_writable else 'FAIL'} data dir: {data_dir}")
        print(f"INFO .env: {'存在' if env_file else '不存在（可选）'}")
        if server_ok:
            print(f"OK   server: {url}  version={system.get('version') if isinstance(system, dict) else '?'}")
            print(f"{'OK  ' if health_ok else 'FAIL'} /api/health")
            if routes:
                print("      routes: " + ", ".join(f"{k}={v}" for k, v in routes.items()))
            if disabled:
                print("      disabled (intentional): " + ", ".join(disabled))
            for item in unhealthy:
                print(f"      unhealthy: {item}")
        else:
            print(f"FAIL server: {url} → {system}")
        for w in warnings:
            print(f"WARN {w}")
        for s in next_steps:
            print(f"NEXT {s}")
        print("RESULT", "core ok" if core_ok else "core broken")

    if not core_ok:
        return 1
    if a.require_server and not server_ok:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
