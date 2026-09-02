"""Image fingerprints: dHash + coarse color histogram. No extra packages beyond Pillow."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

DHASH_SIZE = 16  # 16x16 bits = 256


def _open_rgb(path: Path) -> Image.Image:
    im = Image.open(path)
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1] if im.mode == "RGBA" else None)
        return bg
    return im.convert("RGB")


def dhash_int(im: Image.Image, size: int = DHASH_SIZE) -> int:
    g = im.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    pixels = list(g.getdata())
    bits = 0
    bit = 0
    for row in range(size):
        row_off = row * (size + 1)
        for col in range(size):
            if pixels[row_off + col] > pixels[row_off + col + 1]:
                bits |= 1 << bit
            bit += 1
    return bits


def hist64(im: Image.Image) -> list[float]:
    small = im.resize((64, 64), Image.Resampling.BOX)
    hist = small.histogram()
    # 256*3 → 4x4x4 by binning each channel into 4
    # cheaper: 8 bins per channel on already-quantized histogram
    r = hist[0:256]
    g = hist[256:512]
    b = hist[512:768]

    def bins8(channel: list[int]) -> list[int]:
        out = [0] * 8
        for i, v in enumerate(channel):
            out[i >> 5] += v
        return out

    vec = bins8(r) + bins8(g) + bins8(b)
    s = float(sum(vec)) or 1.0
    return [v / s for v in vec]


def fingerprint_image(path: Path) -> dict:
    im = _open_rgb(path)
    # crop a slight center to ignore shop watermarks on borders a bit
    w, h = im.size
    if w > 20 and h > 20:
        m = int(min(w, h) * 0.04)
        im = im.crop((m, m, w - m, h - m))
    return {
        "dhash": dhash_int(im),
        "hist": hist64(im),
    }


def fingerprint_bytes(data: bytes) -> dict:
    from io import BytesIO

    im = Image.open(BytesIO(data))
    im = ImageOps.exif_transpose(im).convert("RGB")
    w, h = im.size
    if w > 20 and h > 20:
        m = int(min(w, h) * 0.04)
        im = im.crop((m, m, w - m, h - m))
    return {"dhash": dhash_int(im), "hist": hist64(im)}


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def hist_cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (na * nb)))


def visual_score(fp_a: dict, fp_b: dict) -> float:
    """0..1, higher is more similar. dHash dominates; histogram breaks color collisions."""
    dist = hamming(int(fp_a["dhash"]), int(fp_b["dhash"]))
    # 256-bit hash
    hash_sim = 1.0 - (dist / 256.0)
    color_sim = hist_cosine(fp_a["hist"], fp_b["hist"])
    # Near-duplicate manufacturer photos: hash_sim very high.
    # Different photos of same product: hash drops, color may still help a little.
    score = 0.82 * hash_sim + 0.18 * color_sim
    return max(0.0, min(1.0, score))
