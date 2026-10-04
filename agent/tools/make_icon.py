"""Generate the app icon set (ico/icns/png) from one source drawing.

Run: uv run python agent/tools/make_icon.py
Outputs into agent/assets/ — the generated files are committed so the
PyInstaller specs can reference them directly on any OS.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def make_source(size: int = 1024) -> Image.Image:
    """Simple booth-deck mark: dark rounded square, green EQ bars."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = size // 16
    d.rounded_rectangle(
        (pad, pad, size - pad, size - pad),
        radius=size // 5,
        fill="#0f172a",
    )
    bars = [0.35, 0.65, 0.9, 0.55, 0.75, 0.45, 0.6]
    bw = size // 14
    gap = size // 22
    total = len(bars) * bw + (len(bars) - 1) * gap
    x = (size - total) // 2
    base_y = int(size * 0.78)
    top_y = int(size * 0.28)
    for h in bars:
        bh = int((base_y - top_y) * h)
        d.rounded_rectangle(
            (x, base_y - bh, x + bw, base_y),
            radius=bw // 3,
            fill="#22c55e",
        )
        x += bw + gap
    return img


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    src = make_source()
    src.save(ASSETS / "icon.png")
    src.save(ASSETS / "icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
    src.save(ASSETS / "icon.icns", sizes=[(s, s) for s in (16, 32, 64, 128, 256, 512, 1024)])
    print(f"wrote {ASSETS}")


if __name__ == "__main__":
    main()
