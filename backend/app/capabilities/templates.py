"""Asset templates (presets) — the 'template contract': fixed size, count and style per preset."""
from __future__ import annotations

PIXEL_STYLE = ("pixel art game sprite, crisp hard-edged pixels, clean dark outline, limited color palette, "
               "flat cel shading, readable silhouette, no anti-aliasing, no text")
HD_STYLE = ("high quality 2D game asset illustration, clean lineart, soft cel shading, vibrant colors, "
            "consistent lighting from top-left, no text, no watermark")

PIXEL_TEMPLATES = [
    {"id": "px_char_64", "name": "精致像素角色", "category": "full-body game characters", "w": 64, "h": 64, "count": 4,
     "layout": [2, 2], "anchor": "bottom", "colors": 24, "view": "front three-quarter view, standing idle pose"},
    {"id": "px_char_32", "name": "迷你像素角色", "category": "tiny chibi game characters", "w": 32, "h": 32, "count": 4,
     "layout": [2, 2], "anchor": "bottom", "colors": 16, "view": "front view, standing"},
    {"id": "px_char_128", "name": "大尺寸像素角色", "category": "detailed full-body game character", "w": 128, "h": 128,
     "count": 1, "layout": [1, 1], "anchor": "bottom", "colors": 32, "view": "front three-quarter view"},
    {"id": "px_monster_64", "name": "像素怪物", "category": "fantasy monsters / enemies", "w": 64, "h": 64, "count": 4,
     "layout": [2, 2], "anchor": "bottom", "colors": 24, "view": "side three-quarter view"},
    {"id": "px_animal_64", "name": "精致像素动物", "category": "cute animals / pets", "w": 64, "h": 64, "count": 4,
     "layout": [2, 2], "anchor": "bottom", "colors": 24, "view": "side three-quarter view"},
    {"id": "px_prop_32x64", "name": "精致像素道具(竖)", "category": "tall environment props (lamps, banners, statues)",
     "w": 32, "h": 64, "count": 4, "layout": [4, 1], "anchor": "bottom", "colors": 20, "view": "front view"},
    {"id": "px_item_64", "name": "精致像素道具", "category": "inventory items / props", "w": 64, "h": 64, "count": 4,
     "layout": [2, 2], "anchor": "center", "colors": 24, "view": "slightly tilted icon view"},
    {"id": "px_weapon_64", "name": "精致像素武器", "category": "weapons", "w": 64, "h": 64, "count": 4, "layout": [2, 2],
     "anchor": "center", "colors": 20, "view": "diagonal icon view"},
    {"id": "px_food_64", "name": "精致像素食物", "category": "food items", "w": 64, "h": 64, "count": 4, "layout": [2, 2],
     "anchor": "center", "colors": 24, "view": "icon view"},
    {"id": "px_icon_32", "name": "像素图标包", "category": "inventory icons", "w": 32, "h": 32, "count": 9,
     "layout": [3, 3], "anchor": "center", "colors": 16, "view": "icon view"},
    {"id": "px_building_128", "name": "像素建筑", "category": "game building", "w": 128, "h": 128, "count": 1,
     "layout": [1, 1], "anchor": "bottom", "colors": 32, "view": "top-down three-quarter RPG view"},
    {"id": "px_portrait_96", "name": "像素头像", "category": "character portrait bust", "w": 96, "h": 96, "count": 1,
     "layout": [1, 1], "anchor": "bottom", "colors": 32, "view": "front bust portrait"},
]

HD_TEMPLATES = [
    {"id": "hd_char_2x2", "name": "高清角色", "category": "full-body game characters", "count": 4, "layout": [2, 2],
     "anchor": "bottom", "view": "front three-quarter view, standing"},
    {"id": "hd_pack_4x4", "name": "高清素材包", "category": "game props and items", "count": 16, "layout": [4, 4],
     "anchor": "center", "view": "icon view"},
    {"id": "hd_icon_3x3", "name": "高清图标", "category": "skill / inventory icons", "count": 9, "layout": [3, 3],
     "anchor": "center", "view": "icon view"},
    {"id": "hd_single", "name": "高清单体", "category": "game asset", "count": 1, "layout": [1, 1],
     "anchor": "center", "view": "front three-quarter view"},
]


def find(template_id: str) -> dict:
    for t in PIXEL_TEMPLATES + HD_TEMPLATES:
        if t["id"] == template_id:
            return t
    raise KeyError(template_id)


def choices(kind: str) -> list[dict]:
    src = PIXEL_TEMPLATES if kind == "pixel" else HD_TEMPLATES
    out = []
    for t in src:
        size = f"{t['w']}x{t['h']}" if "w" in t else "1K/2K"
        out.append({"value": t["id"], "label": f"{t['name']} · {t['count']}张 · {size}"})
    return out


def sheet_prompt(subject: str, t: dict, style: str, bg: str = "plain pure white background") -> str:
    n = t["count"]
    cols, rows = t["layout"]
    if n == 1:
        return (f"A single {t['category']}: {subject}. {t['view']}, centered, whole object fully visible with margin, "
                f"isolated on {bg}. {style}")
    return (f"A set of {n} different {t['category']} arranged in a {cols} by {rows} grid, evenly spaced, "
            f"each one isolated with generous empty space around it, not touching, on {bg}. "
            f"Theme: {subject}. All share one consistent art style, palette and scale. {t['view']}. {style}")
