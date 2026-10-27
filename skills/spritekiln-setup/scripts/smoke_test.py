#!/usr/bin/env python3
"""End-to-end smoke test: submit a mock pixel_gen job, wait, download, verify the PNG.

  python smoke_test.py [--url http://127.0.0.1:7788] [--timeout 180] [--json]

Uses the deterministic `mock` image provider, so no GPU, network model or API key is involved.
A pass proves the server, queue, storage, capability and download path work — not that a real
model produces good art.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

TERMINAL = {"succeeded", "failed", "canceled"}


def req(url: str, method: str, path: str, body=None, raw: bool = False, timeout: float = 60):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(url + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            payload = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")[:500]
        raise RuntimeError(f"HTTP {exc.code} {path}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接 SpriteKiln ({url})：{exc.reason}") from exc
    if raw:
        return payload
    return json.loads(payload.decode("utf-8")) if payload else None


def slug(text: str) -> str:
    return re.sub(r"[^\w-]+", "-", text, flags=re.ASCII).strip("-").lower()[:40] or "asset"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:7788")
    ap.add_argument("--timeout", type=float, default=180)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    url = a.url.rstrip("/")
    started = time.time()
    result: dict = {"url": url, "ok": False}

    try:
        # 1. server + capability
        req(url, "GET", "/api/system", timeout=8)
        caps = req(url, "GET", "/api/capabilities")["capabilities"]
        cap = next((c for c in caps if c["id"] == "pixel_gen"), None)
        if not cap:
            raise RuntimeError("能力目录里没有 pixel_gen")

        # 2. project (reuse inbox)
        projects = req(url, "GET", "/api/projects")
        inbox = next((p for p in projects if p.get("kind") == "inbox"), None)
        project = inbox["id"] if inbox else req(url, "POST", "/api/projects",
                                                {"name": "smoke-test", "kind": "inbox"})["id"]

        # 3. run with the deterministic provider
        job = req(url, "POST", "/api/capabilities/pixel_gen/run",
                  {"project_id": project, "source": "smoke-test",
                   # force the deterministic CPU matte too: a smoke test must not load BiRefNet/torch
                   "params": {"template": "px_icon_32", "prompt": "smoke test potion",
                              "provider": "mock", "bg_method": "chroma"}})
        result["job_id"] = job["id"]
        result["providers"] = job.get("providers")
        if (job.get("providers") or {}).get("image") != "mock":
            result["warning"] = f"预期 mock，实际路由到 {(job.get('providers') or {}).get('image')}；结果仍可继续验证"

        # 4. poll
        deadline = time.time() + a.timeout
        while True:
            job = req(url, "GET", f"/api/jobs/{job['id']}")
            if job["status"] in TERMINAL:
                break
            if time.time() > deadline:
                raise RuntimeError(f"超时；任务仍在运行，用 poll {job['id']} 恢复，不要重复提交")
            time.sleep(1.5)
        result["status"] = job["status"]
        if job["status"] != "succeeded":
            raise RuntimeError(f"任务 {job['status']}：{job.get('error')}")

        # 5. download the first final image
        assets = [x for x in job.get("assets") or [] if x.get("role") in ("output", "pack") and x.get("kind") == "image"]
        if not assets:
            raise RuntimeError("任务成功但没有最终图片产物")
        asset = assets[0]
        data = req(url, "GET", f"/api/assets/{asset['id']}/download", raw=True, timeout=120)
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("下载内容不是 PNG")
        out = Path("outputs") / f"smoke-{job['id'][-6:]}" / f"{slug(asset['name'])}_{asset['id'][-6:]}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        result.update({"asset_id": asset["id"], "file": str(out.resolve()), "bytes": len(data)})

        # 6. verify geometry
        try:
            from PIL import Image
            with Image.open(out) as img:
                result["size"] = list(img.size)
                alpha = img.convert("RGBA").getchannel("A")
                result["alpha_range"] = list(alpha.getextrema())
                if img.width != asset.get("width") or img.height != asset.get("height"):
                    raise RuntimeError(f"文件尺寸 {img.size} 与资产记录 {(asset.get('width'), asset.get('height'))} 不一致")
        except ImportError:
            result["warning_pillow"] = "Pillow 未安装，跳过尺寸/alpha 检查"

        result["ok"] = True
        result["elapsed_s"] = round(time.time() - started, 1)
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["elapsed_s"] = round(time.time() - started, 1)

    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for k in ("job_id", "status", "providers", "file", "size", "alpha_range", "bytes", "elapsed_s"):
            if k in result:
                print(f"{k}: {result[k]}")
        for k in ("warning", "warning_pillow", "error"):
            if k in result:
                print(f"{k}: {result[k]}")
        print("RESULT", "PASS" if result["ok"] else "FAIL")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
