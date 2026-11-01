"""プロフィールのヘッダー画像（ライト・ダーク）と、こもれびのプロモーション動画・VPMのカードを作る。

文字は、見る人の環境に字体がなくても同じ形で出るよう、字の輪郭を図形にして埋め込む。
ヘッダーの右に並べるサムネイルは assets/ の画像から作るので、ワールドや配布物を
差し替えたら TILES を直してから実行し直す。

使い方: python scripts/build_images.py [--font-dir C:/Windows/Fonts]
（Noto Serif CJK JP の Bold・SemiBold・Medium と、fontTools・Pillow が要る）
"""

from __future__ import annotations

import argparse
import base64
import io
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
CLOVER = ROOT / "scripts" / "hero" / "clover.png"

# NiAka堂ブランドの色
PAPER, INK = "#F7F6F6", "#1F2A40"
TEAL, PURPLE, GOLD = "#4FB3AA", "#7B6AE6", "#D0A85C"

THEMES = {
    "light": dict(bg=PAPER, title=INK, text="#354D3D", sub="#556B5E", stroke="#FFFFFF", shadow=0.16),
    "dark": dict(bg=INK, title=PAPER, text="#DCE5E0", sub="#B8C8C0", stroke="#3A4A5E", shadow=0.45),
}

# ヘッダーの右に、少し傾けて並べるサムネイル（3行 × 3列）。左の列は文字の側へ溶かすので、
# 目立つのは真ん中と右の列
TILES = [
    ["worlds/cyanaria.webp", "products/oborozuki.webp", "products/ezmirror.webp"],
    ["worlds/amayadokari.webp", "worlds/manuka-pumpkin-field.webp", "worlds/sugaria.webp"],
    ["products/eztalkdeck.webp", "products/sugar-reactor.webp", "worlds/manulabo.webp"],
]
TILE_W, TILE_H, TILE_GAP, TILE_R = 236, 177, 18, 14


def num(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


class Font:
    """字体ファイルから、文字列の輪郭を SVG の path にする"""

    def __init__(self, path: Path):
        self.font = TTFont(path, lazy=True)
        self.glyphs = self.font.getGlyphSet()
        self.cmap = self.font.getBestCmap()
        self.upem = self.font["head"].unitsPerEm

    def width(self, text: str, size: float, tracking: float = 0) -> float:
        adv = sum(self.glyphs[self.cmap[ord(c)]].width for c in text) * size / self.upem
        return adv + tracking * (len(text) - 1)

    def path(self, text: str, x: float, y: float, size: float, fill: str,
             tracking: float = 0, anchor: str = "start", opacity: float = 1.0) -> str:
        if anchor == "middle":
            x -= self.width(text, size, tracking) / 2
        elif anchor == "end":
            x -= self.width(text, size, tracking)
        pen = SVGPathPen(self.glyphs, ntos=num)
        s = size / self.upem
        for c in text:
            name = self.cmap[ord(c)]
            self.glyphs[name].draw(TransformPen(pen, (s, 0, 0, -s, x, y)))
            x += self.glyphs[name].width * s + tracking
        op = "" if opacity >= 1 else f' fill-opacity="{opacity}"'
        return f'<path d="{pen.getCommands()}" fill="{fill}"{op}/>'


def data_uri(img: Image.Image, quality: int = 72) -> str:
    buf = io.BytesIO()
    if img.mode == "RGBA":
        img.save(buf, "PNG", optimize=True)
        mime = "image/png"
    else:
        img.save(buf, "WEBP", quality=quality, method=6)
        mime = "image/webp"
    return f"data:{mime};base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"


def tile_image(relative: str) -> str:
    """サムネイルを 4:3 の中央で切り抜き、表示の2倍の大きさで埋め込む"""
    im = Image.open(ASSETS / relative).convert("RGB")
    tw, th = TILE_W * 2, TILE_H * 2
    s = max(tw / im.width, th / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    x, y = (im.width - tw) // 2, (im.height - th) // 2
    return data_uri(im.crop((x, y, x + tw, y + th)))


def hero(theme: str, fonts: dict[str, Font], tiles: list[list[str]], clover: str) -> str:
    t = THEMES[theme]
    w, h = 1200, 400
    grid_w = 3 * TILE_W + 2 * TILE_GAP
    grid_h = 3 * TILE_H + 2 * TILE_GAP
    cells = []
    for r, row in enumerate(tiles):
        for c, uri in enumerate(row):
            x, y = c * (TILE_W + TILE_GAP), r * (TILE_H + TILE_GAP)
            cells.append(
                f'<g transform="translate({x} {y})" filter="url(#shadow)">'
                f'<image href="{uri}" width="{TILE_W}" height="{TILE_H}" clip-path="url(#tile)" preserveAspectRatio="xMidYMid slice"/>'
                f'<rect width="{TILE_W}" height="{TILE_H}" rx="{TILE_R}" fill="none" stroke="{t["stroke"]}" stroke-opacity=".7" stroke-width="2"/>'
                "</g>"
            )
    serif_b, serif_sb, serif_m = fonts["bold"], fonts["semibold"], fonts["medium"]
    text = "\n  ".join([
        f'<image href="{clover}" x="72" y="82" width="96" height="96"/>',
        serif_b.path("NiAka", 186, 160, 88, t["title"], tracking=1),
        serif_sb.path("Web開発と、VRChatのワールドづくり", 76, 246, 28, t["text"]),
        serif_m.path("WEB ENGINEER / VRCHAT CREATOR / OSS MAINTAINER", 78, 290, 14, t["sub"], tracking=2.2),
        f'<rect x="78" y="318" width="74" height="6" rx="3" fill="{TEAL}"/>',
        f'<rect x="160" y="318" width="48" height="6" rx="3" fill="{PURPLE}"/>',
        f'<rect x="216" y="318" width="28" height="6" rx="3" fill="{GOLD}"/>',
    ])
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-labelledby="title desc">
  <title id="title">NiAka — Web開発と、VRChatのワールドづくり</title>
  <desc id="desc">NiAkaのGitHubプロフィールのヘッダー。右に、作ったVRChatワールドと配布しているツールのサムネイルを並べている</desc>
  <defs>
    <clipPath id="frame"><rect width="{w}" height="{h}" rx="28"/></clipPath>
    <clipPath id="tile"><rect width="{TILE_W}" height="{TILE_H}" rx="{TILE_R}"/></clipPath>
    <linearGradient id="fade" x1="0" x2="1" y1="0" y2="0">
      <stop offset="0" stop-color="{t["bg"]}" stop-opacity="1"/>
      <stop offset=".55" stop-color="{t["bg"]}" stop-opacity=".55"/>
      <stop offset="1" stop-color="{t["bg"]}" stop-opacity="0"/>
    </linearGradient>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="150%">
      <feDropShadow dx="0" dy="6" stdDeviation="8" flood-color="#0B1220" flood-opacity="{t["shadow"]}"/>
    </filter>
  </defs>
  <g clip-path="url(#frame)">
  <rect width="{w}" height="{h}" fill="{t["bg"]}"/>
  <g transform="translate(905 200) rotate(-10) translate({-grid_w / 2} {-grid_h / 2})">
  {"".join(cells)}
  </g>
  <rect width="610" height="{h}" fill="{t["bg"]}"/>
  <rect x="609" width="250" height="{h}" fill="url(#fade)"/>
  {text}
  </g>
</svg>
"""


def komorebi_card(fonts: dict[str, Font]) -> str:
    """こもれびのプロモーション動画のカード。ワールドの画像やロゴは使わず、文字と光の丸だけで作る"""
    w, h = 960, 540
    serif_b, serif_sb, serif_m = fonts["bold"], fonts["semibold"], fonts["medium"]
    # 葉のあいだから差す光を、ぼかした丸で置く（右上ほど明るい）
    lights = [(760, 90, 150, GOLD, .30), (900, 210, 110, "#B8D8CC", .22), (640, 40, 90, "#F7E7B8", .25),
              (860, 430, 130, GOLD, .14), (560, 470, 80, "#B8D8CC", .12), (980, 40, 120, "#F7E7B8", .20)]
    circles = "".join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{c}" fill-opacity="{o}" filter="url(#soft)"/>'
                      for x, y, r, c, o in lights)
    parts = "\n  ".join([
        serif_m.path("PROMOTION VIDEO", 64, 96, 20, "#B8D8CC", tracking=5),
        serif_sb.path("初心者案内ワールド", 64, 200, 30, PAPER, opacity=.86),
        serif_b.path("こもれび", 58, 318, 112, PAPER),
        serif_m.path("With Rinasciita", 66, 378, 36, PAPER, tracking=2, opacity=.92),
        serif_m.path("構成・撮影・編集　NiAka", 64, 476, 24, "#DCE5E0"),
        serif_m.path("2026.11", 896, 476, 24, "#B8D8CC", tracking=2, anchor="end"),
        f'<circle cx="790" cy="280" r="62" fill="{PAPER}" fill-opacity=".94"/>',
        '<path d="M772 248 L820 280 L772 312 Z" fill="#354D3D"/>',
    ])
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-labelledby="title">
  <title id="title">初心者案内ワールド こもれび With Rinasciita のプロモーション動画（構成・撮影・編集 NiAka、2026年11月）</title>
  <defs>
    <linearGradient id="bg" x1="0" y1="1" x2="1" y2="0">
      <stop offset="0" stop-color="#1E3328"/>
      <stop offset="1" stop-color="#3E5A47"/>
    </linearGradient>
    <filter id="soft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="28"/></filter>
    <clipPath id="frame"><rect width="{w}" height="{h}" rx="24"/></clipPath>
  </defs>
  <g clip-path="url(#frame)">
  <rect width="{w}" height="{h}" fill="url(#bg)"/>
  {circles}
  <rect x="64" y="122" width="56" height="4" rx="2" fill="{GOLD}"/>
  {parts}
  </g>
</svg>
"""


def vpm_card(fonts: dict[str, Font]) -> str:
    """NiAkaDev VPM Repository へのカード。配布物の画像と同じ正方形にする"""
    w = h = 620
    serif_b, serif_m = fonts["bold"], fonts["medium"]
    parts = "\n  ".join([
        serif_m.path("NIAKADEV", 60, 108, 22, "#B8D8CC", tracking=6),
        serif_b.path("VPM", 54, 300, 168, PAPER, tracking=4),
        serif_m.path("Repository", 60, 372, 46, PAPER, opacity=.92),
        f'<rect x="60" y="414" width="64" height="5" rx="2.5" fill="{GOLD}"/>',
        serif_m.path("VCC / ALCOM", 60, 494, 28, "#DCE5E0", tracking=1),
        serif_m.path("vpm.2aka.io", 60, 548, 28, "#B8D8CC", tracking=1),
    ])
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-labelledby="title">
  <title id="title">NiAkaDev VPM Repository（VCC / ALCOM から導入できる配布先）</title>
  <defs>
    <linearGradient id="bg" x1="0" y1="1" x2="1" y2="0">
      <stop offset="0" stop-color="#26392E"/>
      <stop offset="1" stop-color="#3E5A47"/>
    </linearGradient>
  </defs>
  <rect width="{w}" height="{h}" fill="url(#bg)"/>
  {parts}
</svg>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--font-dir", type=Path, default=Path("C:/Windows/Fonts"))
    args = parser.parse_args()
    fonts = {key: Font(args.font_dir / f"NotoSerifCJKjp-{name}.otf")
             for key, name in (("bold", "Bold"), ("semibold", "SemiBold"), ("medium", "Medium"))}
    tiles = [[tile_image(p) for p in row] for row in TILES]
    clover = data_uri(Image.open(CLOVER).convert("RGBA").resize((192, 192), Image.LANCZOS))
    for theme in THEMES:
        out = ASSETS / f"hero-{theme}.svg"
        out.write_text(hero(theme, fonts, tiles, clover), encoding="utf-8")
        print(f"{out.relative_to(ROOT)}: {out.stat().st_size // 1024} KB")
    for out, svg in ((ASSETS / "latest" / "komorebi-promo.svg", komorebi_card(fonts)),
                     (ASSETS / "products" / "vpm.svg", vpm_card(fonts))):
        out.write_text(svg, encoding="utf-8")
        print(f"{out.relative_to(ROOT)}: {out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
