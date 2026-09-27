"""Per-platform thumbnail export: one finished design -> YouTube + Bilibili files.

Specs (checked 2026-09; see .claude/skills/publish-video-chat/SKILL.md for sources):

* YouTube custom thumbnail — 16:9, JPG/PNG, min width 640. Size cap is 2 MB when
  set from the mobile app (desktop Studio / Data API allow 50 MB). We keep
  1280x720 JPEG <= ~1.9 MB so the same file is valid on every upload path.
* Bilibili cover (封面) — JPG/PNG, <= 5 MB, recommended >= 1146x717, min 960x600,
  i.e. **16:10**, not 16:9. Some feeds (mobile home / recommendation cards) also
  show a **4:3 centre crop**, and every card overlays the duration badge
  (bottom-right) plus play/danmaku counts (bottom-left).

Because the aspect differs (16:9 vs 16:10), a separate Bilibili file is written.
It is made by *padding* the 16:9 design top/bottom with a blurred, darkened
extension of its own edges (default) — nothing is squashed and no text is
cropped. ``bilibili_mode="crop"`` instead centre-crops the sides (16:9 -> 16:10
loses ~5% per side), which is fine when the design keeps text inside the
central 4:3 zone anyway.

Pure Pillow, no new deps.
"""
import io
import os

from PIL import Image, ImageEnhance, ImageFilter

YOUTUBE_SIZE = (1280, 720)          # 16:9
YOUTUBE_MAX_BYTES = int(1.9 * 1024 * 1024)   # under the 2 MB mobile cap
BILIBILI_SIZE = (1280, 800)         # 16:10, >= recommended 1146x717
BILIBILI_MAX_BYTES = int(4.8 * 1024 * 1024)  # under the 5 MB cap


def _cover(img, size):
    """Scale to fill ``size`` then centre-crop (no distortion)."""
    tw, th = size
    scale = max(tw / img.width, th / img.height)
    nw, nh = max(tw, round(img.width * scale)), max(th, round(img.height * scale))
    img = img.resize((nw, nh), Image.LANCZOS)
    l, t = (nw - tw) // 2, (nh - th) // 2
    return img.crop((l, t, l + tw, t + th))


def _pad_blur(img, size):
    """Fit ``img`` inside ``size`` (full width) and fill the rest with a blurred,
    slightly darkened stretch of the image itself — reads as intentional, not
    as letterbox bars."""
    tw, th = size
    scale = min(tw / img.width, th / img.height)
    fw, fh = round(img.width * scale), round(img.height * scale)
    fg = img.resize((fw, fh), Image.LANCZOS)
    bg = _cover(img, size).filter(ImageFilter.GaussianBlur(radius=max(tw, th) // 40))
    bg = ImageEnhance.Brightness(bg).enhance(0.6)
    bg.paste(fg, ((tw - fw) // 2, (th - fh) // 2))
    return bg


def _save_capped(img, path, max_bytes, quality=95, min_quality=60):
    """Save JPEG, stepping quality down until the file fits ``max_bytes``."""
    img = img.convert("RGB")
    q = quality
    while True:
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=q, optimize=True, progressive=True)
        if buf.tell() <= max_bytes or q <= min_quality:
            break
        q -= 5
    if buf.tell() > max_bytes:
        raise ValueError(f"{path}: {buf.tell()} bytes > cap {max_bytes} even at q={q}")
    with open(path, "wb") as f:
        f.write(buf.getvalue())
    return q


def export_for_platforms(src_image, out_dir, base_name="thumbnail", bilibili_mode="pad"):
    """Write ``<base>_youtube.jpg`` and ``<base>_bilibili.jpg`` into ``out_dir``.

    ``src_image`` is a path or PIL Image of the finished (text-on-image) design,
    normally 1280x720. ``bilibili_mode`` is ``"pad"`` (blurred extend, keeps all
    content) or ``"crop"`` (centre crop). Returns ``{"youtube": path,
    "bilibili": path}``.
    """
    img = src_image if isinstance(src_image, Image.Image) else Image.open(src_image)
    img = img.convert("RGB")
    os.makedirs(out_dir, exist_ok=True)

    yt = _cover(img, YOUTUBE_SIZE)
    yt_path = os.path.join(out_dir, f"{base_name}_youtube.jpg")
    _save_capped(yt, yt_path, YOUTUBE_MAX_BYTES)

    if bilibili_mode == "crop":
        bl = _cover(img, BILIBILI_SIZE)
    elif bilibili_mode == "pad":
        bl = _pad_blur(yt, BILIBILI_SIZE)
    else:
        raise ValueError(f"bilibili_mode must be 'pad' or 'crop', got {bilibili_mode!r}")
    bl_path = os.path.join(out_dir, f"{base_name}_bilibili.jpg")
    _save_capped(bl, bl_path, BILIBILI_MAX_BYTES)

    return {"youtube": yt_path, "bilibili": bl_path}


if __name__ == "__main__":
    # Self-test: export a repo sample (or a generated noisy gradient) and check specs.
    import tempfile

    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    sample = os.path.join(repo, "docs", "images", "thumb-after.jpg")
    if os.path.exists(sample):
        src = Image.open(sample)
    else:  # worst-case for JPEG size: a gradient with noise, 4K
        w, h = 3840, 2160
        grad = Image.linear_gradient("L").resize((w, h))
        src = Image.merge("RGB", (grad, grad.rotate(90).resize((w, h)),
                                  Image.effect_noise((w, h), 80)))
        sample = "<generated 3840x2160 noisy gradient>"
    out = tempfile.mkdtemp(prefix="thumb_export_")
    for mode in ("pad", "crop"):
        paths = export_for_platforms(src, out, f"selftest_{mode}", bilibili_mode=mode)
        for plat, p in paths.items():
            im, size = Image.open(p), os.path.getsize(p)
            want, cap = ((YOUTUBE_SIZE, YOUTUBE_MAX_BYTES) if plat == "youtube"
                         else (BILIBILI_SIZE, BILIBILI_MAX_BYTES))
            assert im.size == want, (p, im.size)
            assert im.format == "JPEG" and size <= cap, (p, im.format, size)
            if plat == "bilibili":
                assert im.width >= 1146 and im.height >= 717
            print(f"OK {mode:4s} {plat:8s} {im.size[0]}x{im.size[1]} {size/1024:.0f} KB  {p}")
    print(f"source: {sample}\nall checks passed -> {out}")
