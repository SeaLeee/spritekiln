"""Background removal: chroma/flood-fill (exact, CPU) and BiRefNet (neural, local GPU/CPU)."""
from __future__ import annotations

import threading

import numpy as np
from PIL import Image
from scipy import ndimage

from .pixelate import has_alpha


def border_stats(img: Image.Image, width: int = 3) -> tuple[tuple[int, int, int], float]:
    rgb = np.asarray(img.convert("RGB")).astype(np.float32)
    border = np.concatenate([rgb[:width].reshape(-1, 3), rgb[-width:].reshape(-1, 3),
                             rgb[:, :width].reshape(-1, 3), rgb[:, -width:].reshape(-1, 3)])
    med = np.median(border, axis=0)
    spread = float(np.median(np.abs(border - med).sum(axis=1)))
    return (int(med[0]), int(med[1]), int(med[2])), spread


def parse_color(value: str | tuple | None) -> tuple[int, int, int] | None:
    if value is None or value == "" or value == "auto":
        return None
    if isinstance(value, (tuple, list)):
        return tuple(int(v) for v in value[:3])  # type: ignore[return-value]
    v = value.lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def chroma_remove(img: Image.Image, color: tuple[int, int, int] | None = None, tolerance: float = 42.0,
                  flood: bool = True, soft: bool = True) -> Image.Image:
    """Remove a (near-)uniform background. Flood-fill from the border keeps same-coloured interior details."""
    rgba = img.convert("RGBA")
    arr = np.asarray(rgba).astype(np.float32)
    if color is None:
        color, _ = border_stats(rgba)
    dist = np.sqrt(((arr[..., :3] - np.array(color, dtype=np.float32)) ** 2).sum(axis=2))
    bg = dist < tolerance
    if flood:
        labels, _ = ndimage.label(bg)
        edge_labels = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
        edge_labels = edge_labels[edge_labels > 0]
        bg = np.isin(labels, edge_labels)
    alpha = np.where(bg, 0.0, arr[..., 3])
    if soft:
        # anti-aliased fringe: pixels touching the background get partial alpha + colour despill
        ring = ndimage.binary_dilation(bg, iterations=1) & ~bg
        t = np.clip((dist - tolerance * 0.5) / (tolerance * 1.5), 0, 1)
        alpha = np.where(ring, np.minimum(alpha, t * 255), alpha)
        c = np.array(color, dtype=np.float32)
        a = np.clip(alpha / 255.0, 1e-3, 1)[..., None]
        unmixed = (arr[..., :3] - c * (1 - a)) / a
        arr[..., :3] = np.where(ring[..., None], np.clip(unmixed, 0, 255), arr[..., :3])
    arr[..., 3] = alpha
    out = arr.astype(np.uint8)
    out[out[..., 3] == 0] = 0
    return Image.fromarray(out, "RGBA")


class _BiRefNet:
    def __init__(self) -> None:
        self.model = None
        self.device = "cpu"
        self.lock = threading.Lock()
        self.error: str | None = None

    def available(self) -> bool:
        if self.model is not None:
            return True
        if self.error:
            return False
        try:
            from huggingface_hub import snapshot_download
            snapshot_download("ZhengPeng7/BiRefNet", local_files_only=True)
            return True
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
            return False

    def load(self, model_name: str = "ZhengPeng7/BiRefNet", device: str = "auto") -> None:
        if self.model is not None:
            return
        import torch
        from huggingface_hub import snapshot_download
        from transformers import AutoModelForImageSegmentation

        path = snapshot_download(model_name, local_files_only=True)
        model = AutoModelForImageSegmentation.from_pretrained(path, trust_remote_code=True).float().eval()
        self.device = ("cuda" if torch.cuda.is_available() else "cpu") if device == "auto" else device
        self.model = model.to(self.device)

    def __call__(self, img: Image.Image) -> Image.Image:
        import torch
        from torchvision import transforms

        with self.lock:
            self.load()
            rgb = img.convert("RGB")
            tf = transforms.Compose([
                transforms.Resize((1024, 1024)), transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            ])
            x = tf(rgb).unsqueeze(0).to(self.device)
            with torch.inference_mode():
                pred = self.model(x)[-1].sigmoid().cpu()[0].squeeze()  # type: ignore[misc]
            mask = transforms.ToPILImage()(pred).resize(rgb.size, Image.Resampling.BILINEAR)
            out = rgb.convert("RGBA")
            out.putalpha(mask)
            return out

    def unload(self) -> None:
        with self.lock:
            if self.model is not None:
                self.model = None
                try:
                    import torch
                    torch.cuda.empty_cache()
                except Exception:  # noqa: BLE001
                    pass


birefnet = _BiRefNet()


def remove_background(img: Image.Image, method: str = "auto", mode: str = "hd", color: str | None = None,
                      tolerance: float = 42.0, preserve_translucency: bool = False) -> tuple[Image.Image, str]:
    """Returns (rgba, method_used). method: auto | chroma | birefnet | none."""
    img = img.convert("RGBA")
    if method == "none":
        return img, "none"
    if has_alpha(img) and method == "auto":
        return img, "existing-alpha"
    used = method
    key = parse_color(color)
    if method == "auto":
        _, spread = border_stats(img)
        if key is not None or spread < 18:
            used = "chroma"
        elif birefnet.available():
            used = "birefnet"
        else:
            used = "chroma"
    if used == "birefnet":
        try:
            out = birefnet(img)
        except Exception as exc:  # noqa: BLE001
            birefnet.error = str(exc)
            out = chroma_remove(img, key, tolerance, soft=mode != "pixel")
            used = "chroma"
    else:
        out = chroma_remove(img, key, tolerance, soft=mode != "pixel")
    if mode == "pixel" and not preserve_translucency:
        arr = np.asarray(out).copy()
        arr[..., 3] = np.where(arr[..., 3] >= 128, 255, 0)
        arr[arr[..., 3] == 0] = 0
        out = Image.fromarray(arr, "RGBA")
    return out, used
