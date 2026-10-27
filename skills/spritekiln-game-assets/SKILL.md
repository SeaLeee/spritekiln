---
name: spritekiln-game-assets
description: Create, edit, animate and export game-ready 2D/3D assets with the local SpriteKiln studio (像素窑). Use for pixel or HD sprites and asset packs, consistent character variants, 8-direction characters, sprite/keyframe animation, seamless textures, dual-grid tilesets, isometric tiles, parallax layers, UI sheets, background removal, pixelation, image→3D (Pixal3D GLB) and 3D→directional sprites, game-design documents, and writing finished assets into a Godot 4 project. Runs on local models (ComfyUI Z-Image / MiniMax H3 / Pixal3D / Ollama) with optional cloud APIs (GPT Image, Seedream/Seedance, MiniMax).
---

# SpriteKiln game assets

SpriteKiln is a local server (default `http://127.0.0.1:7788`, override with `SPRITEKILN_URL`). Every asset operation
is a **capability** with a typed parameter schema, executed as an async job (submit → poll → download). Everything you
create also appears on the user's web canvas (`/studio/<project>`), so the user can inspect and take over at any time.

Run all commands with `python <skill-dir>/kiln_api.py ...` (standard library only).

## 0 · Before the first job

1. `kiln_api.py health` — the server must answer. If it does not, ask the user to run `start.ps1` in the SpriteKiln
   folder. Note which engines are healthy (`routes`): local GPU jobs run one at a time; cloud jobs need keys in 设置.
2. Pick or create a project: `kiln_api.py projects` / `kiln_api.py create-project "<game name>"`. Reuse it for the
   whole session so lineage (source → derived asset) stays on one canvas. Without `--project`, results go to the inbox.

## 1 · Fix the asset contract first

Decide, and state to the user, before choosing a capability:

- **Runtime role**: sprite, prop, icon, UI, texture, tileset, map layer, animation, video, 3D model, design doc.
- **Representation**: pixel (exact pixel size, limited palette, nearest-neighbour) or HD (smooth, soft alpha).
- **Size / count / transparency / format**: e.g. "4 × 64×64 transparent PNG sharing one palette".
- **Deliverable shape**: single asset, variant pack, directional set, sprite sheet + SpriteFrames, atlas + mapping.

Template presets fix size and count — prompt wording cannot override them. If no preset fits, say so and use the
closest flexible capability (`custom_size_pixel`, `pixel_universal`, `general_image`).

## 2 · Route to ONE primary capability

Read [references/capability-routing.md](references/capability-routing.md). Inspect the live schema before running:
`kiln_api.py describe <capability>` (choices/defaults change with the server version).

Common chains (only when each step really needs the previous output):

- Pixel character: `pixel_gen` → (`image_edit` / `asset_variants`) → `character_multi_view` → `animate`
- Strictly consistent directions: `image_to_3d` → render 8 directions in the web 3D workbench → `render_sprites`
- Environment: `texture_gen` (fg + bg) → `tileset_gen` → export to Godot TileSet
- Complex motion: draw/generate 2–6 key poses → `keyframes_animate`
- Game from scratch: `game_design` (asset list) → batch the list → `export-godot`

Every generative step can drift identity, palette and scale. Do not chain without a reason.

## 3 · Prompts

Use short natural language (Chinese or English): subject, action, viewpoint, material. No keyword stacks, weights,
negative-prompt blocks or sampler jargon — the capabilities already add the style, layout and background
instructions. Add one constraint at a time only after inspecting a result.

## 4 · Run, recover, validate

```
python kiln_api.py run <capability> --project <prj> --param key=value ... --output-dir ./outputs/<new-folder>
```

- Image params accept an asset id (`ast_...`) or a local file path (auto-uploaded). Lists: `images` → `a,b,c`;
  `lines` → `a|b|c`. Complex params: `--params-json file.json`.
- Local GPU jobs take time (Z-Image ≈ 1 min, H3 animation ≈ 4 min, Pixal3D ≈ 6–8 min). If the command times out
  or the session is interrupted, **never resubmit** — run `kiln_api.py poll <job_id>`.
- Only final deliverables are downloaded (`role` = output / pack) with `final_outputs.json`. Raw generations,
  previews and uploaded inputs stay on the server.
- For a whole asset list use `kiln_api.py batch pack.json --output-dir ./out/pack` (see
  [references/capability-routing.md](references/capability-routing.md#batch-manifests)). It writes
  `batch_report.json`; failures do not abort later items unless `--stop-on-error` is set.
- Animation results carry `meta.qa` (and `meta.qa_attempts`). Read them and report what was rejected/re-taken.
  The deterministic gate flags empty frames, area/bbox drift and duplicate frames; centre drift is not a failure.
- Open the files and verify what you promise (pixel size, alpha, frame count, seamlessness, direction) before
  reporting success. Pixel assets must be previewed at integer zoom with nearest-neighbour sampling.

## 5 · Hand-off to engines

`kiln_api.py export-godot --project <prj> --godot <path-to-godot-project> [--assets ast_a,ast_b]` writes PNGs, sprite
sheets, `SpriteFrames` (.tres) and `AnimatedSprite2D` scenes under `res://assets/spritekiln/<project>/`, plus
`game-assets.json`, and sets the canvas texture filter to Nearest. With a Godot MCP (e.g. godot-ai) you can then
instance the generated `sprite.tscn` scenes or create `Sprite2D` nodes pointing at the PNGs. See
[references/godot.md](references/godot.md).

Animations also ship `aseprite.json` and `phaser.json` (absolute frame rects, duration, pivot, frame tags), and
tilesets ship a Tiled `.tsj` inside ZIP exports — no row/column math needed. These formats are covered by unit
tests but have not been verified by running the engine; say so if the user needs runtime guarantees.

## Rules

- Never ask for or print API keys; cloud keys are configured by the user in the web UI (设置).
- Respect the daily cloud budget errors — switch to a local engine or ask the user; do not retry blindly.
- Do not overwrite or re-pixelate outputs of pixel capabilities (they are already grid-clean and palette-locked).
- Keep transparency only when the runtime needs it; terrain textures and backgrounds stay opaque.
- Report job ids, output folder and any contract gap (e.g. "model drew 5 figures for a 4-figure preset").
