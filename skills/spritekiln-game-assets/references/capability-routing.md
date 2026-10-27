# Capability routing

Pick one primary capability. Inspect it with `kiln_api.py describe <id>`.

| User intent | Capability | Key params |
|---|---|---|
| Pixel characters / monsters / animals / props / weapons / food / icons as a fixed-size pack | `pixel_gen` | `template` (px_char_64, px_char_32, px_char_128, px_monster_64, px_animal_64, px_prop_32x64, px_item_64, px_weapon_64, px_food_64, px_icon_32, px_building_128, px_portrait_96), `prompt` (describe the whole set), `reference` |
| Free pixel composition: scene, illustration, building stages, HD→pixel reinterpretation, top-down image | `pixel_universal` | `aspect_ratio`, `view` (standard/top-down), `pixel_size` (long edge) |
| One object at an exact pixel width × height | `custom_size_pixel` | `width`, `height`, `colors`, `anchor` |
| HD character sheet (2×2), asset pack (4×4), icon set (3×3), single | `hd_gen` | `template`, `resolution` 1K/2K |
| Anything else / maximum freedom / mixed batch / backgrounds | `general_image` | `prompt`, `references[]`, `aspect_ratio`, `count`, `provider` |
| 8-direction character sheet (5 generated views + mirrors) | `character_multi_view` | `source` or `prompt`, `mode`, `size` |
| Strictly consistent directions | `image_to_3d` → web 3D workbench render → `render_sprites` | `renders[]`, `directions`, `size` |
| HUD / menu / buttons / icon sheet with component split | `ui_gen` | `mode`, `aspect_ratio` |
| Same-style new assets from one reference (1/4/9/16/25/36) | `asset_clone` | `reference`, `clone_count`, `mode` |
| Upgrade tiers / colour / material variants of one asset | `asset_variants` | `source`, `prompts` (one change per line) |
| One precise change to an image (optionally masked) | `image_edit` | `source`, `prompt`, `mask`, `references` |
| Remove background (image or animation) | `remove_background` | `mode` pixel/hd, `method` auto/chroma/birefnet |
| Convert art to clean pixel art / lock a palette | `pixelate` | `width`, `height`, `colors`, `palette_from` |
| Recolour with another asset's palette (skins, factions, seasons) | `palette_swap` | `source`, `palette_from` |
| Split an aggregate sheet into separate PNGs | `split_components` | `min_area`, `merge_distance` |
| Seamless ground/material texture | `texture_gen` | `mode`, `size` (16–512) |
| Top-down terrain autotile atlas (16 tiles, corner/dual-grid) | `tileset_gen` | `foreground`/`foreground_prompt`, `background`/`background_prompt`, `tile_size` |
| Isometric diamond / block tile (2:1, default 128×64) | `isometric_tile` | `texture` or `prompt`, `width`, `block_height` |
| Side-scrolling parallax (background / midground / foreground) | `side_scrolling_map` | `prompt`, `pixel_height`, `loop` |
| Make any image tile horizontally / vertically | `self_loop` | `axis` |
| Frame animation from a finished still | `animate` | `source`, `prompt`, `frames`, `fps`, `loop`, `video_provider`, `quality_gate`, `retakes` |
| Complex motion controlled by key poses | `keyframes_animate` | `keyframes[]` (ordered), `segment_prompts`, `frames_per_segment` |
| Short mp4 clip from first (and last) frame | `video_gen` | `first_frame`, `last_frame`, `seconds` |
| Image or text → textured GLB | `image_to_3d` | `source` or `prompt`, `quality` |
| Multi-view reference sheet + GLB | `multiview_3d` | `source` or `prompt` |
| Game concept, systems, balance, asset list, critique | `game_design` | `prompt`, `doc_type` (gdd/core_loop/asset_list/balance/level/critique) |

## Engine selection

Each job resolves engines at submit time (shown as `providers` in the job). Default `auto` = first healthy engine
in this order — image: ComfyUI(Z-Image) → GPT Image → Seedream → MiniMax → offline; video: ComfyUI(MiniMax H3 FL2V)
→ Seedance → Hailuo → procedural; 3D: Pixal3D → billboard; LLM: local Ollama → cloud → rules.

Override per job only when the user asks or the output needs it:

- `provider=openai|ark|minimax` when **reference images** must drive identity (Z-Image has no reference input; it
  falls back to img2img from the first reference).
- `video_provider=procedural` for instant, zero-VRAM placeholder motion (idle bob, squash, lunge, hurt flash…).
- `video_provider=ark|minimax` when the local GPU is busy or a longer/HD clip is needed (costs money; budget-checked).

## Animation choices

- Animate only stable, final stills. Pixel sprites ≤ 128×128 animate best.
- `animate` keys the sprite onto a solid colour that does not occur in the sprite, runs first/last-frame video
  generation (loop → last = first), keys out every frame, re-pixelates with the **source palette**, and keeps one
  canvas so the anchor never jumps. Leave `padding=-1` (auto: extra top room for jumps, side room for attacks).
- Use `keyframes_animate` for attacks, combos and anything where the in-between pose matters.
- Keep `quality_gate=standard` and `retakes=1` for real animation. The gate is deterministic and rejects empty
  frames, strong area/bbox drift and frozen (duplicate) frames; centre drift is reported but not failed, because
  jump/attack motion is supposed to move. Inspect `meta.qa` and `meta.qa_attempts` in the result and mention any
  remaining issues instead of declaring success blindly.

## Engine exports

Animations write, next to `sheet.png`: `sheet.json` (absolute frame rects, duration, pivot), `aseprite.json`,
`phaser.json`, plus `spriteframes.tres` for Godot. `tileset_gen` and isometric tiles get a `.tsj` in ZIP exports.
Frame rectangles are absolute — do not recompute rows/columns in the engine.

## Batch manifests

`kiln_api.py batch pack.json --output-dir ./out/pack` runs items sequentially, continues past failures by default,
writes each item to `<out>/<name>/final_outputs.json` and a summary `batch_report.json`. Use it for asset lists from
`game_design`; pass `--stop-on-error` only when later items depend on earlier ones.
