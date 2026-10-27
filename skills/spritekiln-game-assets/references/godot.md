# Godot hand-off

## Export

```
python kiln_api.py export-godot --project <prj> --godot "D:/Games/MyGame" [--assets ast_a,ast_b]
```

Result (also returned as JSON):

```
res://assets/spritekiln/<project-slug>/
  images/<name>_<id>.png
  animations/<name>_<id>/sheet.png          # sprite sheet
  animations/<name>_<id>/spriteframes.tres  # SpriteFrames, one AtlasTexture per frame, fps + loop set
  animations/<name>_<id>/sprite.tscn        # AnimatedSprite2D (texture_filter=nearest, autoplay)
  animations/<name>_<id>/frames/frame_000.png …
  model3ds/<name>_<id>.glb
  game-assets.json                          # manifest: kind, size, pixel, fps, directions, tile mapping…
```

`project.godot` gets `textures/canvas_textures/default_texture_filter=0` (Nearest) if it was not set.

## Placing assets with a Godot MCP

With **godot-ai** (`http://127.0.0.1:8000/mcp`, plugin-managed, Godot 4.5+):

1. After export, let the editor import (or call the editor rescan tool).
2. Animated sprite: instance the generated scene — or create an `AnimatedSprite2D` with `node_create` and
   `node_set_property sprite_frames = res://…/spriteframes.tres`, `autoplay = "default"`.
3. Static sprite: `Sprite2D` with `texture = res://…/<name>.png`.
4. Tileset: create a `TileSet` with an atlas source from the 4×4 atlas; tile index = TL·1 + TR·2 + BL·4 + BR·8 (a set
   bit means that corner is the foreground terrain). Use the companion `_mapping.json` for the cell → corner table.
5. Isometric: diamond `128×64`, neighbour offsets `(64, 32)` and `(-64, 32)`; set `TileSet.tile_shape = Isometric`.
6. Parallax: put the three layers in `Parallax2D` nodes with scroll scale ≈ 0.2 / 0.5 / 1.0 and `repeat_size.x` =
   layer width when `loop_x` is true.

Prefer instancing over rebuilding resources by hand, and validate in-game at the intended zoom.
