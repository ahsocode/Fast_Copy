#!/usr/bin/env python3
"""
Generate Fast_Copy app icon.
Output: assets/icon.ico (Windows) and assets/icon.icns (macOS).

Design:
  - Dark catppuccin-mocha rounded square background
  - Two file stacks (source left, destination right) in blue
  - Bold lightning bolt in gold shooting from source → destination
  - Subtle speed lines behind the bolt
"""

import os
import math
from PIL import Image, ImageDraw, ImageFilter, ImageColor

# ── Palette (catppuccin mocha) ─────────────────────────────────────────────
BG          = (30, 30, 46)          # #1e1e2e  — surface
FILE_SRC    = (69, 71, 90)          # #45475a  — slightly lighter surface
FILE_DST    = (137, 180, 250)       # #89b4fa  — blue
FILE_FOLD   = (100, 130, 200)       # darker blue for fold
BOLT_MAIN   = (249, 226, 175)       # #f9e2af  — peach/gold (lightning)
BOLT_GLOW   = (249, 226, 175, 60)   # same, transparent glow
SPEED_LINE  = (203, 166, 247, 80)   # #cba6f7  — mauve, semi-transparent
WHITE       = (255, 255, 255)

SIZE = 1024
R    = SIZE // 5          # corner radius of background square


# ── Helpers ───────────────────────────────────────────────────────────────

def rounded_rect(draw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def document(draw, x, y, w, h, body_color, fold_ratio=0.28):
    """Draw a single document/page icon at (x,y) with size w×h."""
    fold = int(w * fold_ratio)
    # Body polygon (top-right corner cut)
    pts = [
        (x,         y),
        (x + w - fold, y),
        (x + w,     y + fold),
        (x + w,     y + h),
        (x,         y + h),
    ]
    draw.polygon(pts, fill=body_color)
    # Fold triangle (darker)
    fc = tuple(max(0, int(c * 0.7)) for c in body_color[:3])
    draw.polygon([
        (x + w - fold, y),
        (x + w - fold, y + fold),
        (x + w,        y + fold),
    ], fill=fc)
    # Horizontal lines (text representation)
    line_color = tuple(min(255, int(c * 1.35)) for c in body_color[:3])
    lx0, lx1 = x + int(w * 0.18), x + w - int(w * 0.22)
    for i in range(4):
        ly = y + fold + int(h * (0.22 + i * 0.17))
        if ly < y + h - int(h * 0.12):
            draw.rectangle([lx0, ly, lx1, ly + max(2, int(h * 0.045))],
                           fill=line_color)


def lightning_bolt(draw, cx, cy, size, color):
    """Draw a vertical lightning bolt centred at (cx, cy)."""
    s = size
    # Classic ⚡ shape: wide at top, narrow at notch, spike at bottom
    pts = [
        (cx + s * 0.18,  cy - s * 0.50),   # top-right
        (cx - s * 0.05,  cy - s * 0.02),   # centre notch (right approach)
        (cx + s * 0.22,  cy - s * 0.02),   # notch jog right
        (cx - s * 0.18,  cy + s * 0.50),   # bottom tip
        (cx - s * 0.28,  cy + s * 0.05),   # centre notch (left approach)
        (cx - s * 0.08,  cy + s * 0.05),   # notch jog left
        (cx - s * 0.18,  cy - s * 0.50),   # top-left
    ]
    draw.polygon(pts, fill=color)


def glow_layer(size, cx, cy, radius, color_rgba):
    """Return a radial glow image layer."""
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for r in range(radius, 0, -max(1, radius // 20)):
        alpha = int(color_rgba[3] * (1 - r / radius) ** 2)
        c = (*color_rgba[:3], alpha)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c)
    return layer


def speed_lines(draw, cx, cy, size):
    """Draw horizontal speed streaks to the left of the bolt."""
    for i in range(5):
        offset_y = cy + int(size * (-0.30 + i * 0.15))
        length   = int(size * (0.18 + (i % 2) * 0.08))
        thick    = max(2, int(size * 0.012))
        x1 = cx - int(size * 0.44)
        x2 = x1 + length
        alpha = 90 - i * 12
        draw.rectangle([x1, offset_y, x2, offset_y + thick],
                       fill=(*SPEED_LINE[:3], alpha))


# ── Main render ───────────────────────────────────────────────────────────

def render(size: int) -> Image.Image:
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")

    s = size
    pad = int(s * 0.07)
    r_bg = int(s * 0.20)

    # ── Background rounded square ──────────────────────────────────
    rounded_rect(draw, [0, 0, s - 1, s - 1], r_bg, BG)

    # ── Source file stack (left) ───────────────────────────────────
    fw  = int(s * 0.30)   # file width
    fh  = int(s * 0.38)   # file height
    cx_src = int(s * 0.28)
    cy_mid = int(s * 0.50)

    # Shadow doc behind
    document(draw,
             cx_src - fw // 2 + int(s * 0.04),
             cy_mid - fh // 2 - int(s * 0.04),
             fw, fh,
             (55, 57, 75))
    # Front doc
    document(draw,
             cx_src - fw // 2,
             cy_mid - fh // 2,
             fw, fh,
             FILE_SRC)

    # ── Destination file (right) ───────────────────────────────────
    cx_dst = int(s * 0.73)
    document(draw,
             cx_dst - fw // 2,
             cy_mid - fh // 2,
             fw, fh,
             FILE_DST)

    # ── Speed lines ───────────────────────────────────────────────
    speed_lines(draw, s // 2, cy_mid, s)

    # ── Glow behind bolt ──────────────────────────────────────────
    glow = glow_layer(s, s // 2, cy_mid,
                      int(s * 0.30), (249, 226, 175, 55))
    img  = Image.alpha_composite(img, glow)
    draw = ImageDraw.Draw(img, "RGBA")

    # ── Lightning bolt ────────────────────────────────────────────
    bolt_size = int(s * 0.38)
    lightning_bolt(draw, s // 2, cy_mid, bolt_size, BOLT_MAIN)

    # Inner highlight (lighter centre of bolt)
    lightning_bolt(draw, s // 2 - int(s * 0.015),
                   cy_mid - int(s * 0.01),
                   int(bolt_size * 0.45),
                   (255, 245, 220, 180))

    return img


def make_sizes(base: Image.Image, sizes):
    return [base.resize((s, s), Image.LANCZOS) for s in sizes]


def save_ico(images, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Convert to RGBA first, then save as ICO
    ico_images = [img.convert("RGBA") for img in images]
    ico_images[0].save(
        path,
        format="ICO",
        sizes=[(img.width, img.height) for img in ico_images],
        append_images=ico_images[1:],
    )
    print(f"  ✓ {path}  ({len(images)} sizes)")


def save_icns(images, path):
    """Save as icns via png intermediates + iconutil (macOS only)."""
    import platform, subprocess, tempfile, shutil
    if platform.system() != "Darwin":
        print("  ⚠ icns skipped (macOS only)")
        return

    os.makedirs(os.path.dirname(path), exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        iconset = os.path.join(tmp, "icon.iconset")
        os.makedirs(iconset)
        mapping = {
            16:   "icon_16x16",
            32:   "icon_16x16@2x",
            32:   "icon_32x32",
            64:   "icon_32x32@2x",
            128:  "icon_128x128",
            256:  "icon_128x128@2x",
            256:  "icon_256x256",
            512:  "icon_256x256@2x",
            512:  "icon_512x512",
            1024: "icon_512x512@2x",
        }
        done = set()
        for sz, name in mapping.items():
            if name in done:
                continue
            done.add(name)
            img = base.resize((sz, sz), Image.LANCZOS)
            img.save(os.path.join(iconset, f"{name}.png"))

        subprocess.run(
            ["iconutil", "-c", "icns", iconset, "-o", path],
            check=True, capture_output=True,
        )
    print(f"  ✓ {path}")


# ── Entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Rendering base icon at 1024×1024 …")
    base = render(1024)

    ico_sizes  = [16, 32, 48, 64, 128, 256]
    ico_images = make_sizes(base, ico_sizes)

    print("Saving …")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assets = os.path.join(root, "assets")

    save_ico(ico_images, os.path.join(assets, "icon.ico"))
    save_icns(base, os.path.join(assets, "icon.icns"))

    # Also save a preview PNG
    preview = base.resize((512, 512), Image.LANCZOS)
    preview.save(os.path.join(assets, "icon_preview.png"))
    print(f"  ✓ {os.path.join(assets, 'icon_preview.png')}  (preview)")
    print("Done.")
