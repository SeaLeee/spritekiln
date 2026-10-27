"""Split an aggregate sheet into individual transparent assets."""
from __future__ import annotations

import numpy as np
from PIL import Image
from scipy import ndimage


def split_components(img: Image.Image, min_area: int = 24, merge_distance: int = 2, margin: int = 1,
                     max_parts: int = 64) -> list[tuple[Image.Image, tuple[int, int, int, int]]]:
    rgba = img.convert("RGBA")
    a = np.asarray(rgba.getchannel("A")) > 16
    if merge_distance > 0:
        grown = ndimage.binary_dilation(a, iterations=merge_distance)
    else:
        grown = a
    labels, n = ndimage.label(grown, structure=np.ones((3, 3)))
    boxes = ndimage.find_objects(labels)
    parts = []
    for i, sl in enumerate(boxes, start=1):
        if sl is None:
            continue
        region = (labels[sl] == i) & a[sl]
        if region.sum() < min_area:
            continue
        y0, y1 = sl[0].start, sl[0].stop
        x0, x1 = sl[1].start, sl[1].stop
        box = (max(0, x0 - margin), max(0, y0 - margin), min(rgba.width, x1 + margin), min(rgba.height, y1 + margin))
        crop = np.asarray(rgba.crop(box)).copy()
        keep = np.zeros(a.shape, dtype=bool)
        keep[sl] = region
        keep_crop = keep[box[1]:box[3], box[0]:box[2]]
        crop[~keep_crop] = 0
        parts.append((Image.fromarray(crop, "RGBA"), box))
    # reading order: rows (by vertical centre bands) then columns
    if parts:
        hs = np.median([p[1][3] - p[1][1] for p in parts])
        parts.sort(key=lambda p: (round(((p[1][1] + p[1][3]) / 2) / max(1, hs * 0.75)), p[1][0]))
    return parts[:max_parts]


def split_grid(img: Image.Image, cols: int, rows: int) -> list[Image.Image]:
    fw, fh = img.width // cols, img.height // rows
    return [img.crop((c * fw, r * fh, (c + 1) * fw, (r + 1) * fh)) for r in range(rows) for c in range(cols)]
