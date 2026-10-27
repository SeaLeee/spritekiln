---
name: spritekiln-setup
description: Install, configure and verify the SpriteKiln (像素窑) local AI game-asset studio. Use when setting up a fresh machine or container, choosing/configuring model providers (ComfyUI Z-Image / MiniMax H3, Ollama/LM Studio, OpenAI/Ark/MiniMax, Pixal3D, BiRefNet), fixing "engine unavailable" or fallback-to-mock routing, building the frontend, or running an end-to-end smoke test. Never prints API keys; never sends masked secrets back to the settings API.
---

# SpriteKiln setup

SpriteKiln is a local FastAPI server (`http://127.0.0.1:7788`) with a React UI, a capability catalog, and four ways in: web, Skill/CLI, MCP, built-in agent. Setup means getting the server healthy **and** making the router land on the engine the user actually wants.

Work from the repository root (the folder containing `backend/app/main.py`, `web/`, `skills/`).

## Rules

- **Never print, echo, or commit API keys.** Do not read `data/settings.json` aloud. The settings API masks secrets as `••••••`; never send a masked value back in a `PUT` (it would overwrite the real key with dots).
- Ask before changing an existing working configuration. Back up `data/settings.json` first if you do change it.
- Prefer the web UI for secrets: tell the user exactly which field to fill instead of moving keys through the terminal/history.
- Do not commit `data/`, `.env`, `outputs/`, or personal absolute paths.
- A healthy `mock`/`procedural` result only proves the pipeline works — say so explicitly, never present it as finished art.

## 1 · Static check

```powershell
python skills\spritekiln-setup\scripts\check_setup.py
```

It checks Python version, required imports, Node/npm, built frontend, data-dir writability, `.env`, cc-switch discovery, and (if the server is up) `/api/system` + `/api/health` + `/api/ccswitch`. Add `--json` for machine-readable output.

Interpretation:

- `core_ok=false` → fix Python/deps/frontend before anything else.
- `server.ok=false` → the server is not running; start it (step 2).
- `health.routes` shows where each task type lands. `mock` / `procedural` / `rules` / `chroma` means fallback, not a real model.

## 2 · Install and start

Windows:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
.\start.ps1 -NoComfy        # first run: no ComfyUI needed
```

macOS/Linux:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cd web && npm ci && npm run build && cd ..
python backend/run.py --host 127.0.0.1 --port 7788
```

Docker: `docker compose up --build` (CPU-only image; ComfyUI/Pixal3D stay on the host).

Start the API in the background when you need to keep working, then re-run the static check. If the frontend is missing, open `/` and the API will say so.

## 3 · Configure providers

Read the **current** settings first (masked):

```powershell
Invoke-RestMethod http://127.0.0.1:7788/api/settings | ConvertTo-Json -Depth 8
```

macOS/Linux 用 `curl http://127.0.0.1:7788/api/settings`。

Choose the path that matches the user's hardware:

| Goal | Provider | Required |
|---|---|---|
| Local image + image-edit | `comfyui` | base_url, workflow names, model files under ComfyUI `models/` |
| Local animation | `comfyui` | H3 workflow + `MiniMaxH3*` custom nodes + weights |
| Agent planning (preferred) | `ccswitch` | cc-switch running with its Codex proxy enabled; auto-discovers provider/model, no key needed |
| Agent planning (fallback) | `llm_local` | OpenAI-compatible base_url, model, placeholder key |
| Cloud image/video | `openai` / `ark` / `minimax` | api_key + model names |
| Image → 3D | `pixal3d` | repo dir + its venv python |
| Neural matting | `birefnet` | torch/transformers + pre-downloaded HF weights |
| Offline validation | `mock` / `procedural` | nothing |

Model file names and workflow mapping: [docs/07-模型配置.md](../../docs/07-模型配置.md). Check bundled workflows with `GET /api/comfy/workflows` (includes required model paths).

**Configure non-secret fields via API** (merge patch; send only what changes):

```powershell
$body = @{
  providers = @{ comfyui = @{ base_url = "http://127.0.0.1:8188"; image_workflow = "zimage_turbo_t2i" } }
  routing   = @{ image = "auto" }
} | ConvertTo-Json -Depth 6
Invoke-RestMethod -Method Put -Uri "http://127.0.0.1:7788/api/settings" `
  -ContentType "application/json" -Body $body
```

macOS/Linux 用 `curl -X PUT ... -d '<json>'`。注意：只发送要改的字段，这是深合并，不是整份替换。

**Secrets**: ask the user to paste the key into 设置 → 模型服务 in the browser. If the user explicitly wants an env-var/API path, accept it from a file or environment variable and never echo it.

Set `routing` explicitly only when the user wants a fixed engine; otherwise keep `auto` and order the preference list. Per-job overrides: `provider` (image/edit), `video_provider`, `threed_provider`, `bg_method`.

**cc-switch is the agent's first-priority LLM.** SpriteKiln reads `~/.cc-switch/cc-switch.db` **read-only** for the current Codex provider's name, model ID and proxy port, then calls the cc-switch Codex proxy (default `127.0.0.1:15721`, OpenAI-compatible). Keys stay with cc-switch; never copy them. Verify with `GET /api/ccswitch` (never returns secrets). If it reports `ok:false`, the agent falls back to `llm_local` → cloud LLMs → `rules`. Leave `providers.ccswitch.base_url` / `model` empty to follow cc-switch live; set them only for a different local proxy. Switching providers in cc-switch takes effect within ~10 s (or force `/api/health?force=true`).

## 4 · Verify

1. Force a health refresh: `curl.exe http://127.0.0.1:7788/api/health?force=true`（macOS/Linux 用 `curl`），或再跑一次 `check_setup.py`。
2. Confirm `routes` matches intent and the chosen provider is `ok=true`.
3. Offline smoke test (no GPU, deterministic):

   ```powershell
   python skills\spritekiln-setup\scripts\smoke_test.py
   ```

   It submits a `pixel_gen` job with `provider=mock`, waits, downloads the PNG, and verifies size/alpha. Use it to separate "server broken" from "model broken".

4. Real smoke test: run the same capability **without** the mock override:

   ```powershell
   python skills\spritekiln-game-assets\kiln_api.py run pixel_gen --param template=px_icon_32 --param "prompt=red potion" --output-dir .\out\setup-check
   ```

   Open the file and verify what you claim (dimensions, alpha, content). If it silently succeeds via fallback, `final_outputs.json` / job meta will reveal the provider — check `/api/jobs/<id>`.

## 5 · Report

End with a short table:

| Item | State | Evidence |
|---|---|---|
| Server | up/down | `/api/system` |
| Image route | comfyui/mock/… | `/api/health` → routes.image |
| Video route | … | routes.video |
| LLM route | … | routes.llm |
| Smoke test | pass/fail | output path |
| Not configured | … | what still falls back |

Mention every fallback explicitly, plus the next action to fix it. Do not claim a model works because the health check is green — a green route with a `mock` fallback still produces placeholder art.

## Common failures

| Symptom | Likely cause | Fix |
|---|---|---|
| `无法连接 SpriteKiln` | server not running / wrong port | start `backend/run.py`, check `SPRITEKILN_URL` |
| ComfyUI `ok=false` | not running, wrong URL, missing model/node | open `http://127.0.0.1:8188/system_stats`; compare `/api/comfy/workflows` models with disk |
| Agent replies “已用规则路由” | cc-switch and local LLM both down, or bad JSON | `GET /api/ccswitch` for the cc-switch reason; then `ollama serve`, `ollama pull <model>`, match model ID |
| Everything routes to `mock` | no healthy real provider | health detail tells which check failed |
| `npm` missing | Node not installed | install Node 18+, rebuild `web/` |
| Pixal3D “未配置” | repo/python empty | set in 设置 or `SPRITEKILN_PIXAL3D_*` |
| BiRefNet unavailable | no torch or weights | install extras + `huggingface-cli download ZhengPeng7/BiRefNet` |
| Frontend 404 after pull | `web/dist` missing | `cd web && npm ci && npm run build` |
