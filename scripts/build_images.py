"""プロフィールの画像を作る。

動く画像（ヘッダー、数字の帯、OSS のカード、ほぼらじおの画面、最新のワールド、区切り、フッター）は SVG、
角を丸めたサムネイルは WebP で書き出す。色は NiAka堂のパステル版ロゴ（2026-09 承認）から取った。

SVG は README から <img> で読まれるので、スクリプトも外部のファイルも使えない。そのため、
- 文字は、見る人の環境に字体がなくても同じ形で出るよう、字の輪郭を図形にして埋め込む
- 画像は data URI で埋め込む
- 動きは CSS の keyframes だけで作り、OS の「動きを減らす」設定では止める
- 動きが働かない環境でも絵が成り立つよう、動かす前の位置を、そのまま止め絵として見られる形にしておく

使い方: python scripts/build_images.py
字体は scripts/fonts/ に置く（git には入れない）。
- Zen Maru Gothic の Medium・Bold・Black（OFL。https://github.com/google/fonts/tree/main/ofl/zenmarugothic ）
- こもれびのカードだけ Noto Serif CJK JP を使う（--serif-dir、既定は C:/Windows/Fonts）
- コマンドの文字は Cascadia Mono（OFL。--mono-font、既定は Windows に入っているもの）
fontTools と Pillow が要る。
"""

from __future__ import annotations

import argparse
import base64
import io
import math
import random
import re
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SRC = ROOT / "scripts" / "src"
FONTS = ROOT / "scripts" / "fonts"

# NiAka堂のロゴの色
PINK, BROWN, SAGE, MOON, CREAM, LINE = "#dfa2a4", "#987e7a", "#a2af99", "#f1d0aa", "#fdfcf9", "#e9d9d3"
DEEP = "#795d57"  # ロゴの輪郭の濃い茶

# ライトは昼の空、ダークは夜の空。sky は上の色、sky_low は下の色。
# 文字は空の上にだけ置く。ink と sub は、空のどちらの色の上でも 4.5 以上のコントラストを保つ（下で確かめる）
THEMES = {
    "light": dict(sky="#fcf6ef", sky_low="#f9e9e3", ink="#3f2e2a", sub="#795d57", ring="#cfb3aa",
                  cloud="#f6e2de", floor_back="#f4d9d6", floor_front="#fffaf4", glow="#fffdf8", glow_op=0.9,
                  line="#e6d3cb", night=False),
    "dark": dict(sky="#211922", sky_low="#33242f", ink="#fbf3ea", sub="#d9c2b8", ring="#7a5f67",
                 cloud="#2c212b", floor_back="#3b2a35", floor_front="#48343f", glow="#f1d0aa", glow_op=0.16,
                 line="#57434a", night=True),
}

# easeInOutSine。行って戻る動きにこの緩急を付けると、円運動を横から見た動き（sin）になる
SINE = "cubic-bezier(.37,0,.63,1)"
REDUCED = "@media (prefers-reduced-motion:reduce){*{animation-play-state:paused!important}}"
TWINKLE = "@keyframes tw{50%{opacity:.25;transform:scale(.55)}}.tw{animation:tw 4s ease-in-out infinite}"
BOB = "@keyframes bob{50%{transform:translateY(-9px)}}.bob{animation:bob 7s ease-in-out infinite}"
SWAY = "@keyframes sway{50%{transform:rotate(9deg) translateY(-5px)}}.sway{animation:sway 8s ease-in-out infinite}"


def num(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def contrast(a: str, b: str) -> float:
    def lum(c: str) -> float:
        ch = [int(c[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        r, g, bl = (v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in ch)
        return 0.2126 * r + 0.7152 * g + 0.0722 * bl
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


for _name, _t in THEMES.items():
    for _key in ("ink", "sub"):
        for _bg in ("sky", "sky_low"):
            assert contrast(_t[_key], _t[_bg]) >= 4.5, (_name, _key, _bg, contrast(_t[_key], _t[_bg]))


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


def data_uri(img: Image.Image, quality: int = 78) -> str:
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=quality, method=6)
    return f"data:image/webp;base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"


def rounded(img: Image.Image, radius: float, border: bool = False, top: bool = True) -> Image.Image:
    """角を丸めて、外側を透明にする。top=False なら下の2つの角だけ丸める。

    border=True なら、内側に細い線を引く（白い画像が白いページに溶けないように）。
    縁がぎざぎざにならないよう、4倍の大きさで描いて縮める。
    """
    img = img.convert("RGBA")
    k = 4
    box = (0, 0, img.width * k - 1, img.height * k - 1)
    if border:
        line = Image.new("RGBA", (img.width * k, img.height * k), (0, 0, 0, 0))
        ImageDraw.Draw(line).rounded_rectangle(box, radius * k, outline=(152, 126, 122, 110), width=round(1.5 * k))
        img = Image.alpha_composite(img, line.resize(img.size, Image.LANCZOS))
    mask = Image.new("L", (img.width * k, img.height * k), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle(box, radius * k, fill=255)
    if not top:
        d.rectangle((0, 0, box[2], box[3] // 2), fill=255)
    img.putalpha(mask.resize(img.size, Image.LANCZOS))
    return img


def fit(path: Path, w: int, h: int) -> Image.Image:
    """中央で切り抜いて w×h にする"""
    im = Image.open(path).convert("RGB")
    s = max(w / im.width, h / im.height)
    im = im.resize((max(w, round(im.width * s)), max(h, round(im.height * s))), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def logo_inner(name: str) -> str:
    """ロゴの SVG の中身（形と色はそのまま使う。変形・色替えをしない）"""
    s = (SRC / name).read_text(encoding="utf-8")
    s = s[s.index(">", s.index("<svg")) + 1:s.rindex("</svg>")]
    s = re.sub(r"<title>.*?</title>|<desc>.*?</desc>", "", s, flags=re.S)
    s = re.sub(r'\s(?:inkscape:[\w-]+|id)="[^"]*"', "", s)  # id は埋め込み先とぶつかるので外す
    return re.sub(r">\s+<", "><", s).strip()


def motif(logo: str, element_id: str) -> tuple[str, float]:
    """NiAka堂ロゴの飾り（クローバー・月・きらめき）の形を、中心を原点にして取り出す。返すのは path の d と幅"""
    d = re.search(rf'id="{element_id}"[^>]*? d="([^"]+)"', logo).group(1)
    assert set(re.findall(r"[A-Za-z]", d)) <= set("MCLZ"), "座標が x,y の組で並ぶ絶対指定の命令だけを扱う"
    number = r"-?\d+\.?\d*"
    vals = [float(v) for v in re.findall(number, d)]
    xs, ys = vals[0::2], vals[1::2]
    center = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    index = iter(range(len(vals)))
    moved = re.sub(number, lambda mt: num(float(mt.group()) - center[next(index) % 2]), d)
    return moved, max(xs) - min(xs)


class Motifs:
    def __init__(self) -> None:
        logo = (SRC / "niakado-logo.svg").read_text(encoding="utf-8")
        self.shapes = {key: motif(logo, element_id) for key, element_id in (
            ("clover", "Clover_Fill_0"), ("moon", "Moon_Fill_0"), ("sparkle", "Star_Pink_Fill_0"), ("sparkle2", "Star_Gold_Fill_0"))}

    def put(self, key: str, x: float, y: float, size: float, fill: str, cls: str = "",
            delay: float = 0, opacity: float = 1) -> str:
        """飾りを (x, y) に幅 size で置く。動きは中心を軸にするので、位置・動き・大きさを別の要素に分ける"""
        d, w = self.shapes[key]
        anim = f' class="{cls}" style="animation-delay:{num(delay)}s"' if cls else ""
        op = "" if opacity >= 1 else f' fill-opacity="{opacity}"'
        return (f'<g transform="translate({num(x)} {num(y)})"><g{anim}>'
                f'<path transform="scale({size / w:.4f})" d="{d}" fill="{fill}"{op}/></g></g>')


def cloud(x: float, y: float, w: float, fill: str, opacity: float = 1) -> str:
    """ロゴの台紙と同じ、もこもこした雲"""
    r = w / 5
    bumps = [(0.18, 0.62, 0.9), (0.38, 0.38, 1.25), (0.62, 0.48, 1.05), (0.82, 0.66, 0.85)]
    parts = "".join(f'<circle cx="{num(x + w * bx)}" cy="{num(y + r * 2 * by)}" r="{num(r * br)}"/>' for bx, by, br in bumps)
    base = f'<rect x="{num(x + w * 0.1)}" y="{num(y + r * 1.25)}" width="{num(w * 0.8)}" height="{num(r * 0.95)}" rx="{num(r * 0.47)}"/>'
    op = "" if opacity >= 1 else f' fill-opacity="{opacity}"'
    return f'<g fill="{fill}"{op}>{parts}{base}</g>'


def cloud_floor(w: int, top: float, bottom: float, fill: str, seed: int, big: float = 1) -> str:
    """下の縁に沿って並ぶ雲。丸を重ねて、上の縁をもこもこにする"""
    rnd = random.Random(seed)
    x, parts = 0.0, []
    while x < w:
        r = rnd.uniform(30, 56) * big
        parts.append(f'<circle cx="{num(x)}" cy="{num(top + r + rnd.uniform(0, 16))}" r="{num(r)}"/>')
        x += r * rnd.uniform(1.0, 1.35)
    return f'<g fill="{fill}">{"".join(parts)}<rect y="{num(top + 44 * big)}" width="{w}" height="{num(bottom - top)}"/></g>'


def drifting(content: str, width: int, name: str) -> str:
    """層を、継ぎ目なく横へ流す（同じ層を右にもう1枚置いて、1枚ぶん動いたら頭に戻る）"""
    return (f'<g class="{name}"><g id="{name}">{content}</g>'
            f'<use href="#{name}" transform="translate({width} 0)"/></g>')


def drift_css(width: int, layers: dict[str, int]) -> str:
    return (f"@keyframes drift{{to{{transform:translateX({-width}px)}}}}"
            + "".join(f".{name}{{animation:drift {sec}s linear infinite}}" for name, sec in layers.items()))


def sky(t: dict, w: int, h: int) -> str:
    return (f'<linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{t["sky"]}"/>'
            f'<stop offset="1" stop-color="{t["sky_low"]}"/></linearGradient>', f'<rect width="{w}" height="{h}" fill="url(#sky)"/>')


def stars(t: dict, w: int, top: float, bottom: float, count: int, seed: int, left: float = 20) -> str:
    """夜の星。文字の後ろに入ると汚れに見えるので、文字のない範囲（left から右、top から bottom）にだけ置く"""
    if not t["night"]:
        return ""
    rnd = random.Random(seed)
    return "".join(
        f'<g transform="translate({num(rnd.uniform(left, w - 20))} {num(rnd.uniform(top, bottom))})">'
        f'<circle class="tw" r="{rnd.choice((1.1, 1.4, 1.8, 2.3))}" fill="{MOON}" '
        f'style="animation-delay:{num(-rnd.uniform(0, 5))}s;animation-duration:{num(rnd.uniform(3, 6))}s"/></g>'
        for _ in range(count))


def svg_open(w: int, h: int, title: str, desc: str = "") -> str:
    d = f'\n  <desc id="desc">{desc}</desc>' if desc else ""
    labelled = "title desc" if desc else "title"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'role="img" aria-labelledby="{labelled}">\n  <title id="title">{title}</title>{d}')


# ヘッダー ------------------------------------------------------------------------------------

# ロゴのまわりを回る窓（作ったワールド・配布物・Web）。高さをそろえ、幅は元の縦横比のまま。
# 数を増やすと、輪の左右の端で窓どうしが重なる
ORBIT = [
    ("latest/manuka-pumpkin-field.webp", 16 / 9),
    ("products/sugar-reactor.webp", 1),
    ("worlds/amayadokari.webp", 4 / 3),
    ("latest/hoboradio-site.webp", 16 / 9),
    ("worlds/cyanaria.webp", 4 / 3),
    ("products/ezraffle.webp", 1),
    ("worlds/sugaria.webp", 4 / 3),
]
ORBIT_H = 110       # 手前に来たときの窓の高さ
ORBIT_SECONDS = 70  # 1周にかける時間
SATELLITE_SECONDS = 26


def orbit_defs() -> str:
    cards = []
    for i, (rel, ratio) in enumerate(ORBIT):
        w = round(ORBIT_H * ratio)
        img = rounded(fit(ASSETS / rel, w * 2, ORBIT_H * 2), 24)
        x, y = -w / 2, -ORBIT_H / 2
        cards.append(
            f'<g id="c{i}">'
            f'<rect x="{x - 5}" y="{y + 3}" width="{w + 10}" height="{ORBIT_H + 10}" rx="18" fill="#3f2e2a" fill-opacity=".13"/>'
            f'<rect x="{x - 5}" y="{y - 5}" width="{w + 10}" height="{ORBIT_H + 10}" rx="17" fill="{CREAM}" stroke="{LINE}" stroke-width="1.5"/>'
            f'<image href="{data_uri(img)}" x="{x}" y="{y}" width="{w}" height="{ORBIT_H}"/>'
            "</g>"
        )
    return "".join(cards)


def orbit(cx: float, cy: float, rx: float, ry: float, front: bool) -> str:
    """輪の上を回る窓。奥の半周と手前の半周を別々に描き、ロゴをそのあいだに挟んで前後を付ける。

    1つの窓に g を3つ重ねる。外から、見えるか（奥か手前か）、横の位置、縦の位置と大きさ。
    横と縦は同じ往復を4分の1周期ずらして重ねるので、楕円の上を回って見える。
    動きが働かないときは、transform と opacity の属性で、同じ並びの止め絵になる。
    """
    t = ORBIT_SECONDS
    out = []
    for i in range(len(ORBIT)):
        phi = (i + 0.5) / len(ORBIT)              # 0〜1。0 は奥のまんなか
        z = -math.cos(2 * math.pi * phi)          # -1 が奥、1 が手前
        x = rx * math.sin(2 * math.pi * phi)
        shown = (z > 0) == front
        vis = "vf" if front else "vb"
        out.append(
            f'<g class="{vis}" opacity="{1 if shown else 0}" style="animation-delay:{num(-phi * t)}s">'
            f'<g class="ox" transform="translate({num(x)} 0)" style="animation-delay:{num(-(phi + 0.25) * t)}s">'
            f'<g class="oz" transform="translate(0 {num(ry * z)}) scale({0.76 + 0.24 * z:.3f})" opacity="{0.725 + 0.275 * z:.2f}" '
            f'style="animation-delay:{num(-phi * t)}s"><use href="#c{i}"/></g></g></g>'
        )
    return f'<g transform="translate({cx} {cy})">{"".join(out)}</g>'


def orbit_css(rx: float, ry: float) -> str:
    t = ORBIT_SECONDS
    return (
        f"@keyframes ox{{from{{transform:translateX({-rx}px)}}to{{transform:translateX({rx}px)}}}}"
        f"@keyframes oz{{from{{transform:translateY({-ry}px) scale(.52);opacity:.45}}to{{transform:translateY({ry}px) scale(1);opacity:1}}}}"
        "@keyframes vf{0%{opacity:0}25%{opacity:1}75%{opacity:0}}"
        "@keyframes vb{0%{opacity:1}25%{opacity:0}75%{opacity:1}}"
        f".ox{{animation:ox {t / 2}s {SINE} infinite alternate}}"
        f".oz{{animation:oz {t / 2}s {SINE} infinite alternate}}"
        f".vf{{animation:vf {t}s step-end infinite}}.vb{{animation:vb {t}s step-end infinite}}"
        f"@keyframes sz{{from{{transform:translateY({-ry}px) scale(.5)}}to{{transform:translateY({ry}px) scale(1)}}}}"
        f".sx{{animation:ox {SATELLITE_SECONDS / 2}s {SINE} infinite alternate}}"
        f".sz{{animation:sz {SATELLITE_SECONDS / 2}s {SINE} infinite alternate}}"
    )


def satellites(m: Motifs, cx: float, cy: float, rx: float, ry: float) -> str:
    """輪の上を、窓より速く回る小さなきらめき。輪が通り道だと分かるように置く"""
    out = []
    for phi, key, color, size in ((0.08, "sparkle2", MOON, 15), (0.58, "sparkle", PINK, 13)):
        z = -math.cos(2 * math.pi * phi)
        d, w = m.shapes[key]
        out.append(
            f'<g class="sx" transform="translate({num(rx * math.sin(2 * math.pi * phi))} 0)" style="animation-delay:{num(-(phi + 0.25) * SATELLITE_SECONDS)}s">'
            f'<g class="sz" transform="translate(0 {num(ry * z)}) scale({0.75 + 0.25 * z:.3f})" style="animation-delay:{num(-phi * SATELLITE_SECONDS)}s">'
            f'<path transform="scale({size / w:.4f})" d="{d}" fill="{color}"/></g></g>'
        )
    return f'<g transform="translate({cx} {cy})">{"".join(out)}</g>'


def hero(theme: str, f: dict[str, Font], m: Motifs, defs: str) -> str:
    t = THEMES[theme]
    w, h = 960, 612
    cx, cy, rx, ry = 480, 250, 368, 126     # 輪の中心と半径
    lw = 372                                 # ロゴの幅
    ls = lw / 1672
    lcy = 176
    lx, ly = cx - lw / 2, lcy - 941 * ls / 2
    sky_def, sky_rect = sky(t, w, h)

    top = "".join(cloud(x, y, cw, t["cloud"]) for x, y, cw in ((30, 30, 190), (372, 4, 130), (690, 44, 220)))
    layers = (drifting(top, w, "far")
              + stars(t, w, 16, 440, 30, 7))

    decor = []
    if t["night"]:
        decor.append(f'<circle cx="852" cy="92" r="78" fill="{MOON}" fill-opacity=".06"/>'
                     f'<circle cx="852" cy="92" r="52" fill="{MOON}" fill-opacity=".08"/>')
        decor.append(m.put("moon", 852, 92, 62, MOON, "bob"))
        decor.append(m.put("sparkle", 770, 152, 22, PINK, "tw", -1.3))
        decor.append(m.put("sparkle2", 112, 86, 28, MOON, "tw", -2.1))
        decor.append(m.put("sparkle", 190, 150, 15, PINK, "tw", -0.4))
        # 流れ星。ふだんは見えず、11秒に1回だけ流れる
        decor.append('<g transform="translate(250 34) rotate(24)"><g class="shoot" opacity="0">'
                     f'<rect width="120" height="2.4" rx="1.2" fill="url(#streak)"/></g></g>')
    else:
        decor.append(m.put("clover", 112, 92, 60, SAGE, "sway"))
        decor.append(m.put("sparkle", 190, 150, 20, PINK, "tw", -0.4))
        decor.append(m.put("moon", 852, 92, 52, MOON, "bob"))
        decor.append(m.put("sparkle2", 776, 150, 22, MOON, "tw", -1.3))
        decor.append(m.put("sparkle", 908, 176, 14, PINK, "tw", -2.4))

    floor = (drifting(cloud_floor(w, 548, h, t["floor_back"], 3, 1.1), w, "fb")
             + drifting(cloud_floor(w, 570, h, t["floor_front"], 5), w, "ff"))

    ring = (f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="none" stroke="{t["ring"]}" stroke-width="1.2" stroke-opacity=".8"/>'
            # 短い線を間をあけて並べ、輪に歯を付ける
            f'<ellipse cx="{cx}" cy="{cy}" rx="{rx + 7}" ry="{ry + 5}" fill="none" stroke="{t["ring"]}" stroke-width="6" '
            'stroke-dasharray="1.6 13.4" stroke-opacity=".7"/>')

    title = "Web開発と、VRChatのワールドづくり"
    caps = "FULL-STACK WEB ENGINEER  /  VRCHAT WORLD CREATOR  /  OSS MAINTAINER"
    assert f["bold"].width(title, 40, 1) < w - 120 and f["bold"].width(caps, 14, 2.6) < w - 120
    text = (f["bold"].path(title, cx, 502, 40, t["ink"], tracking=1, anchor="middle")
            + f["bold"].path(caps, cx, 536, 14, t["sub"], tracking=2.6, anchor="middle"))

    css = (
        orbit_css(rx, ry) + TWINKLE + BOB + SWAY
        + drift_css(w, {"far": 200, "fb": 150, "ff": 95})
        + "@keyframes shoot{0%{transform:translateX(0);opacity:0}1.5%{opacity:1}7%{transform:translateX(330px);opacity:0}100%{transform:translateX(330px);opacity:0}}"
        ".shoot{animation:shoot 11s ease-out infinite 3s}"
        + REDUCED
    )
    return f"""{svg_open(w, h, "NiAka — Web開発と、VRChatのワールドづくり", "NiAkaのロゴのまわりを、作ったVRChatワールド、配布しているギミック、制作したWebサイトの画像がゆっくり回っている")}
  <style>{css}</style>
  <defs>
    <clipPath id="frame"><rect width="{w}" height="{h}" rx="36"/></clipPath>
    {sky_def}
    <radialGradient id="glow"><stop offset="0" stop-color="{t["glow"]}" stop-opacity="{t["glow_op"]}"/><stop offset="1" stop-color="{t["glow"]}" stop-opacity="0"/></radialGradient>
    <linearGradient id="streak"><stop offset="0" stop-color="{MOON}" stop-opacity="0"/><stop offset="1" stop-color="#fff6e6"/></linearGradient>
    {defs}
  </defs>
  <g clip-path="url(#frame)">
  {sky_rect}
  {layers}
  <ellipse cx="{cx}" cy="{lcy + 14}" rx="330" ry="210" fill="url(#glow)"/>
  {"".join(decor)}
  {ring}
  {satellites(m, cx, cy, rx, ry)}
  {orbit(cx, cy, rx, ry, front=False)}
  <g transform="translate({num(lx)} {num(ly)}) scale({ls:.5f})">{logo_inner("niaka-logo.svg")}</g>
  {orbit(cx, cy, rx, ry, front=True)}
  {floor}
  {text}
  </g>
</svg>
"""


# 数字の帯 ------------------------------------------------------------------------------------

STATS = [("300+", "OSS GitHub Stars", PINK), ("6+ years", "Web Development", SAGE), ("20K visits", "in 2 days / あまやどかり", MOON)]


def stats(theme: str, f: dict[str, Font], m: Motifs) -> str:
    t = THEMES[theme]
    w, h, gap = 960, 132, 12
    pw = (w - gap * 2) / 3
    out = []
    for i, (value, label, color) in enumerate(STATS):
        x = i * (pw + gap)
        assert f["bold"].width(label, 25) < pw - 28, label
        out.append(
            f'<rect x="{num(x + 1)}" y="1" width="{num(pw - 2)}" height="{h - 2}" rx="30" fill="{t["sky"]}" stroke="{t["line"]}" stroke-width="1.5"/>'
            f'<rect x="{num(x + pw / 2 - 26)}" y="{h - 9}" width="52" height="5" rx="2.5" fill="{color}"/>'
            + f["black"].path(value, x + pw / 2, 66, 50, t["ink"], anchor="middle")
            + f["bold"].path(label, x + pw / 2, 104, 25, t["sub"], anchor="middle")
            + m.put("sparkle" if i % 2 == 0 else "sparkle2", x + pw - 34, 30, 17, color, "tw", -i * 1.4)
        )
    alt = " / ".join(f"{v} {lb}" for v, lb, _ in STATS)
    return f"""{svg_open(w, h, alt)}
  <style>{TWINKLE}{REDUCED}</style>
  {"".join(out)}
</svg>
"""


# Open Source のカード ------------------------------------------------------------------------

COMMAND = "npx skills add niaka3dayo/agent-skills-vrc-udon"


def oss(theme: str, f: dict[str, Font], m: Motifs) -> str:
    """agent-skills-vrc-udon のカード。導入のコマンドが、1文字ずつ打ち込まれる"""
    t = THEMES[theme]
    w, h = 960, 304
    sky_def, sky_rect = sky(t, w, h)
    tx, ty, tw, th = 48, 170, 864, 98                 # ターミナルの枠
    term = "#3f2e2a" if not t["night"] else "#17111a"
    size = 27
    mono = f["mono"]
    adv = mono.width("n", size)                        # 等幅なので、1文字ぶんの幅
    cmd_x = tx + 34 + adv * 2
    cmd_w = adv * len(COMMAND)
    assert cmd_x + cmd_w + adv < tx + tw - 20, "コマンドがターミナルの枠に収まらない"
    base = ty + 62
    # 文字の上に枠と同じ色の板を置き、1文字ぶんずつ右へずらして見せていく。
    # 動きが働かないときは、板が右へずれきった位置（全部見えている状態）になる
    cover = (f'<rect class="type" transform="translate({num(cmd_w)} 0)" x="{num(cmd_x)}" y="{ty + 26}" '
             f'width="{num(cmd_w + adv)}" height="52" fill="{term}"/>')
    cursor = (f'<g class="type" transform="translate({num(cmd_w)} 0)"><rect class="blink" x="{num(cmd_x + 3)}" y="{base - 26}" '
              f'width="{num(adv * 0.82)}" height="32" rx="3" fill="{MOON}"/></g>')
    dots = "".join(f'<circle cx="{tx + 24 + i * 18}" cy="{ty + 20}" r="5" fill="{c}"/>' for i, c in enumerate((PINK, MOON, SAGE)))
    name = "agent-skills-vrc-udon"
    css = (
        f"@keyframes type{{0%{{transform:translateX(0);animation-timing-function:steps({len(COMMAND)})}}"
        f"36%,100%{{transform:translateX({num(cmd_w)}px)}}}}"
        "@keyframes blink{50%{opacity:0}}"
        ".type{animation:type 11s infinite}.blink{animation:blink 1.1s step-end infinite}"
        + TWINKLE + SWAY + REDUCED
    )
    return f"""{svg_open(w, h, "agent-skills-vrc-udon — AIが書くUdonSharpを、もう少しまともにする。", "導入のコマンド npx skills add niaka3dayo/agent-skills-vrc-udon が、ターミナルに打ち込まれていく")}
  <style>{css}</style>
  <defs><clipPath id="frame"><rect width="{w}" height="{h}" rx="36"/></clipPath>
  <clipPath id="term"><rect x="{tx}" y="{ty}" width="{tw}" height="{th}" rx="22"/></clipPath>{sky_def}</defs>
  <g clip-path="url(#frame)">
  {sky_rect}
  {stars(t, w, 14, 150, 9, 51, left=640)}
  {cloud(690, 10, 230, t["cloud"])}
  {m.put("clover", 846, 78, 54, SAGE, "sway")}{m.put("sparkle", 778, 118, 18, PINK, "tw", -1)}{m.put("sparkle2", 902, 132, 14, MOON, "tw", -2.4)}
  {f["medium"].path("OPEN SOURCE", 50, 54, 15, t["sub"], tracking=4.5)}
  {f["bold"].path(name, 48, 102, 42, t["ink"], tracking=0.5)}
  {f["bold"].path("AIが書くUdonSharpを、もう少しまともにする。", 50, 142, 23, t["sub"])}
  <rect x="{tx}" y="{ty}" width="{tw}" height="{th}" rx="22" fill="{term}" stroke="{t["line"]}" stroke-width="{1.5 if t["night"] else 0}"/>
  {dots}
  {mono.path("$", tx + 34, base, size, PINK)}
  {mono.path(COMMAND, cmd_x, base, size, CREAM)}
  <g clip-path="url(#term)">{cover}{cursor}</g>
  </g>
</svg>
"""


# ほぼらじお公式サイトの画面 --------------------------------------------------------------------

def showcase(theme: str, f: dict[str, Font], m: Motifs) -> str:
    t = THEMES[theme]
    w, h = 960, 520
    desk = Image.open(SRC / "hoboradio-desktop.webp")
    phone = Image.open(SRC / "hoboradio-mobile.webp")
    bw = 640
    bh = round(bw * desk.height / desk.width)
    pw = 172
    ph = round(pw * phone.height / phone.width)
    bx, by = 48, 108
    px, py = 742, 84
    bar = 34
    sky_def, sky_rect = sky(t, w, h)
    dots = "".join(f'<circle cx="{20 + i * 18}" cy="{bar / 2}" r="5" fill="{c}"/>' for i, c in enumerate((PINK, MOON, SAGE)))
    url = f["medium"].path("site.shijukairadio.com", bw / 2, bar / 2 + 5, 14, DEEP, anchor="middle")
    browser = (
        f'<g transform="translate({bx} {by})"><g class="fa">'
        f'<rect x="-1" y="9" width="{bw + 2}" height="{bar + bh + 2}" rx="16" fill="#3f2e2a" fill-opacity=".12"/>'
        f'<rect x="-1" y="-1" width="{bw + 2}" height="{bar + bh + 2}" rx="15" fill="#fffdfa" stroke="#e3cfc8" stroke-width="2"/>'
        f'{dots}<rect x="{bw / 2 - 130}" y="7" width="260" height="20" rx="10" fill="#f3e9e1"/>{url}'
        f'<image href="{data_uri(rounded(desk, 26, top=False), 80)}" x="0" y="{bar}" width="{bw}" height="{bh}"/>'
        "</g></g>"
    )
    device = (
        f'<g transform="translate({px} {py})"><g class="fb">'
        f'<rect x="-9" y="1" width="{pw + 18}" height="{ph + 18}" rx="31" fill="#3f2e2a" fill-opacity=".14"/>'
        f'<rect x="-9" y="-9" width="{pw + 18}" height="{ph + 18}" rx="30" fill="#3f2e2a"/>'
        f'<rect x="-1" y="-1" width="{pw + 2}" height="{ph + 2}" rx="22" fill="#ffffff"/>'
        f'<image href="{data_uri(rounded(phone, 46), 80)}" x="0" y="0" width="{pw}" height="{ph}"/>'
        "</g></g>"
    )
    name = "ほぼらじお 公式サイト"
    text = (f["bold"].path(name, 48, 66, 36, t["ink"], tracking=1)
            + f["bold"].path("デザインと開発", 48 + f["bold"].width(name, 36, 1) + 26, 66, 23, t["sub"]))
    floor = (drifting(cloud_floor(w, 440, h, t["floor_back"], 9, 1.1), w, "fb2")
             + drifting(cloud_floor(w, 468, h, t["floor_front"], 12), w, "ff2"))
    css = (
        "@keyframes fa{50%{transform:translateY(-7px)}}@keyframes fb{50%{transform:translateY(9px)}}"
        ".fa{animation:fa 9s ease-in-out infinite}.fb{animation:fb 7s ease-in-out infinite}"
        + TWINKLE + drift_css(w, {"fb2": 150, "ff2": 95}) + REDUCED
    )
    return f"""{svg_open(w, h, "ほぼらじお 公式サイト（デザインと開発 NiAka）", "公式サイトのトップページを、パソコンとスマートフォンの画面で並べている")}
  <style>{css}</style>
  <defs><clipPath id="frame"><rect width="{w}" height="{h}" rx="36"/></clipPath>{sky_def}</defs>
  <g clip-path="url(#frame)">
  {sky_rect}
  {stars(t, w, 90, 420, 14, 21)}
  {floor}
  {m.put("sparkle", 712, 58, 20, PINK, "tw", -0.6)}{m.put("sparkle2", 690, 88, 12, MOON, "tw", -2)}
  {text}
  {browser}
  {device}
  </g>
</svg>
"""


# 最新のワールド（ゆっくり寄る） ---------------------------------------------------------------

def feature(rel: str, title: str) -> str:
    w, h = 960, 540
    img = fit(ASSETS / rel, w, h)
    css = ("@keyframes kb{from{transform:scale(1)}to{transform:scale(1.07) translate(-14px,-8px)}}"
           ".kb{animation:kb 22s ease-in-out infinite alternate}" + REDUCED)
    return f"""{svg_open(w, h, title)}
  <style>{css}</style>
  <defs><clipPath id="frame"><rect width="{w}" height="{h}" rx="36"/></clipPath></defs>
  <g clip-path="url(#frame)"><g transform="translate({w / 2} {h / 2})"><g class="kb">
  <image href="{data_uri(img, 82)}" x="{-w / 2}" y="{-h / 2}" width="{w}" height="{h}"/>
  </g></g></g>
</svg>
"""


# 区切りとフッター ------------------------------------------------------------------------------

def divider(m: Motifs, key: str) -> str:
    """見出しの前に置く区切り。ライトでもダークでも見える色だけで描く"""
    w, h = 960, 44
    color = {"clover": SAGE, "moon": MOON, "sparkle": PINK}[key]
    line = (f'<path d="M150 22H432M528 22H810" fill="none" stroke="{BROWN}" stroke-opacity=".55" '
            'stroke-width="2" stroke-dasharray="1 10" stroke-linecap="round"/>')
    css = ("@keyframes sway{50%{transform:rotate(10deg)}}.sway{animation:sway 7s ease-in-out infinite}" + TWINKLE + REDUCED)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" aria-hidden="true">
  <style>{css}</style>
  {line}
  {m.put("sparkle", 452, 24, 13, PINK if key != "sparkle" else MOON, "tw", -1)}
  {m.put(key, 480, 22, 30 if key != "sparkle" else 26, color, "sway")}
  {m.put("sparkle2", 508, 20, 13, MOON if key != "moon" else PINK, "tw", -2.6)}
</svg>
"""


def footer(theme: str, f: dict[str, Font], m: Motifs) -> str:
    t = THEMES[theme]
    w, h = 960, 280
    lw = 290
    ls = lw / 1672
    sky_def, sky_rect = sky(t, w, h)
    top = "".join(cloud(x, y, cw, t["cloud"]) for x, y, cw in ((70, 30, 180), (660, 44, 210)))
    floor = (drifting(cloud_floor(w, 226, h, t["floor_back"], 31, 1.1), w, "fb")
             + drifting(cloud_floor(w, 246, h, t["floor_front"], 33), w, "ff"))
    tagline = "あとひとつ、未来にプラスを。"
    css = TWINKLE + BOB + drift_css(w, {"far": 200, "fb": 150, "ff": 95}) + REDUCED
    return f"""{svg_open(w, h, "NiAka堂 — あとひとつ、未来にプラスを。")}
  <style>{css}</style>
  <defs><clipPath id="frame"><rect width="{w}" height="{h}" rx="36"/></clipPath>{sky_def}
  <radialGradient id="glow"><stop offset="0" stop-color="{t["glow"]}" stop-opacity="{t["glow_op"]}"/><stop offset="1" stop-color="{t["glow"]}" stop-opacity="0"/></radialGradient></defs>
  <g clip-path="url(#frame)">
  {sky_rect}
  {drifting(top, w, "far")}{stars(t, w, 14, 172, 18, 11)}
  <ellipse cx="{w / 2}" cy="100" rx="270" ry="130" fill="url(#glow)"/>
  {m.put("clover", 236, 92, 40, SAGE, "bob")}{m.put("moon", 728, 86, 40, MOON, "bob", -3)}
  {m.put("sparkle", 186, 140, 16, PINK, "tw", -1)}{m.put("sparkle2", 782, 142, 16, MOON, "tw", -2.2)}
  <g transform="translate({num(w / 2 - lw / 2)} 12) scale({ls:.5f})">{logo_inner("niakado-logo.svg")}</g>
  {f["bold"].path(tagline, w / 2, 208, 24, t["sub"], tracking=2, anchor="middle")}
  {floor}
  </g>
</svg>
"""


def vpm_banner(f: dict[str, Font], m: Motifs) -> str:
    """NiAkaDev VPM Repository への帯。ライトでもダークでも同じ絵を使う"""
    w, h = 960, 150
    return f"""{svg_open(w, h, "NiAkaDev VPM Repository（VCC / ALCOM から導入できる配布先）")}
  <defs><clipPath id="frame"><rect width="{w}" height="{h}" rx="36"/></clipPath></defs>
  <g clip-path="url(#frame)">
  <rect width="{w}" height="{h}" fill="{DEEP}"/>
  {cloud_floor(w, 104, h, "#866a63", 41, 1.2)}
  {m.put("clover", 868, 52, 42, SAGE)}{m.put("sparkle2", 808, 84, 18, MOON)}{m.put("sparkle", 770, 44, 12, PINK)}
  {f["medium"].path("NIAKADEV", 52, 48, 16, MOON, tracking=5)}
  {f["black"].path("VPM Repository", 50, 96, 44, CREAM)}
  {f["bold"].path("VCC / ALCOM から導入  ·  vpm.2aka.io", 52, 128, 20, "#f6e7dc")}
  </g>
</svg>
"""


# こもれびのカード ------------------------------------------------------------------------------

def komorebi_card(fonts: dict[str, Font], pad: tuple[float, float, float]) -> str:
    """こもれびのプロモーション動画のカード。ワールドの画像やロゴは使わず、文字と光の丸だけで作る"""
    w, h = 960, 540
    left, right, bottom = pad
    paper, gold = "#F7F6F6", "#D0A85C"
    serif_b, serif_sb, serif_m = fonts["serif_bold"], fonts["serif_semibold"], fonts["serif_medium"]
    # 葉のあいだから差す光を、ぼかした丸で置く（右上ほど明るい）
    lights = [(760, 90, 150, gold, .30), (900, 210, 110, "#B8D8CC", .22), (640, 40, 90, "#F7E7B8", .25),
              (860, 430, 130, gold, .14), (560, 470, 80, "#B8D8CC", .12), (980, 40, 120, "#F7E7B8", .20)]
    circles = "".join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{c}" fill-opacity="{o}" filter="url(#soft)"/>'
                      for x, y, r, c, o in lights)
    parts = "\n  ".join([
        serif_m.path("PROMOTION VIDEO", 64, 96, 20, "#B8D8CC", tracking=5),
        serif_sb.path("初心者案内ワールド", 64, 200, 30, paper, opacity=.86),
        serif_b.path("こもれび", 58, 318, 112, paper),
        serif_m.path("With Rinasciita", 66, 378, 36, paper, tracking=2, opacity=.92),
        serif_m.path("構成・撮影・編集　NiAka", 64, 476, 24, "#DCE5E0"),
        serif_m.path("2026.11", 896, 476, 24, "#B8D8CC", tracking=2, anchor="end"),
        f'<circle cx="790" cy="280" r="62" fill="{paper}" fill-opacity=".94"/>',
        '<path d="M772 248 L820 280 L772 312 Z" fill="#354D3D"/>',
    ])
    tw, th = w + left + right, h + bottom
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{num(tw)}" height="{num(th)}" viewBox="{num(-left)} 0 {num(tw)} {num(th)}" role="img" aria-labelledby="title">
  <title id="title">初心者案内ワールド こもれび With Rinasciita のプロモーション動画（構成・撮影・編集 NiAka、2026年11月）</title>
  <defs>
    <linearGradient id="bg" x1="0" y1="1" x2="1" y2="0">
      <stop offset="0" stop-color="#1E3328"/>
      <stop offset="1" stop-color="#3E5A47"/>
    </linearGradient>
    <filter id="soft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="28"/></filter>
    <clipPath id="frame"><rect width="{w}" height="{h}" rx="36"/></clipPath>
  </defs>
  <g clip-path="url(#frame)">
  <rect width="{w}" height="{h}" fill="url(#bg)"/>
  {circles}
  <rect x="64" y="122" width="56" height="4" rx="2" fill="{gold}"/>
  {parts}
  </g>
</svg>
"""


# 角を丸めたサムネイル --------------------------------------------------------------------------

# 角の丸みは、ページの上でどの行も同じ大きさになるよう、列の数に比例させる。
# README の行と同じ並び。行の画像は空白を挟まずに並べ、合わせて幅 100% にする。
# 画像どうしのすきまは、画像の内側の辺と下に付けた透明の余白で作る（行の幅の GUTTER %）。
# こうすると、行の左右の端が、幅いっぱいの画像の端とそろう
GUTTER = 1.2
KOMOREBI = "komorebi"
ROWS = [
    [("latest/ezraffle.webp", "ezraffle-latest"), KOMOREBI],
    [("worlds/sugaria.webp", "sugaria"), ("worlds/amayadokari.webp", "amayadokari")],
    [("worlds/cyanaria.webp", "cyanaria"), ("worlds/manulabo.webp", "manulabo")],
    [("products/sugar-reactor.webp", "sugar-reactor"), ("products/eztalkdeck.webp", "eztalkdeck"), ("products/ezraffle.webp", "ezraffle")],
    [("products/ezmirror.webp", "ezmirror"), ("products/oborozuki.webp", "oborozuki"), ("products/font-tool.webp", "font-tool")],
    [("projects/hoboradio.webp", "hoboradio"), ("projects/aquelia.webp", "aquelia")],
    [("projects/mokaboard.webp", "mokaboard"), ("projects/metacopi.webp", "metacopi")],
]


def gutters(cols: int, index: int, content_w: float) -> tuple[float, float, float]:
    """行の中の index 番目の画像に付ける、左・右・下の余白（画像の中身の幅が content_w のとき）"""
    content = (100 - GUTTER * (cols - 1)) / cols      # 中身の幅（行の幅に対する %）
    unit = content_w / content                         # 1% あたりの長さ
    half = GUTTER / 2 * unit
    return (0 if index == 0 else half, 0 if index == cols - 1 else half, GUTTER / 2 * unit)


def slot_width(cols: int, index: int) -> float:
    """README の width に書く %（中身の幅に、内側の余白を足したもの）"""
    content = (100 - GUTTER * (cols - 1)) / cols
    inner = (index != 0) + (index != cols - 1)
    return content + GUTTER / 2 * inner


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    print(f"{path.relative_to(ROOT).as_posix()}: {path.stat().st_size // 1024} KB")


def tiles(f: dict[str, Font]) -> None:
    for row in ROWS:
        ratio = None
        for index, item in enumerate(row):
            if item == KOMOREBI:
                write(ASSETS / "latest" / "komorebi-promo.svg", komorebi_card(f, gutters(len(row), index, 960)))
                ratio = ratio or 960 / 540
                continue
            rel, name = item
            im = Image.open(ASSETS / rel)
            ratio = ratio or im.width / im.height     # 行の高さがそろうよう、1枚目の縦横比に合わせて切る
            im = fit(ASSETS / rel, im.width, round(im.width / ratio))
            left, right, bottom = (round(v) for v in gutters(len(row), index, im.width))
            canvas = Image.new("RGBA", (im.width + left + right, im.height + bottom), (0, 0, 0, 0))
            canvas.paste(rounded(im, im.width * 0.028 * len(row), border=True), (left, 0))
            out = ASSETS / "tiles" / f"{name}.webp"
            out.parent.mkdir(exist_ok=True)
            canvas.save(out, "WEBP", quality=86, method=6)
            print(f"{out.relative_to(ROOT).as_posix()}: {out.stat().st_size // 1024} KB  width={slot_width(len(row), index):.2f}%")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--serif-dir", type=Path, default=Path("C:/Windows/Fonts"))
    parser.add_argument("--mono-font", type=Path, default=Path("C:/Windows/Fonts/CascadiaMono.ttf"))
    args = parser.parse_args()
    f = {key: Font(FONTS / f"ZenMaruGothic-{name}.ttf") for key, name in (("medium", "Medium"), ("bold", "Bold"), ("black", "Black"))}
    f.update({f"serif_{key}": Font(args.serif_dir / f"NotoSerifCJKjp-{name}.otf")
              for key, name in (("bold", "Bold"), ("semibold", "SemiBold"), ("medium", "Medium"))})
    f["mono"] = Font(args.mono_font)
    m = Motifs()
    defs = orbit_defs()
    for theme in THEMES:
        write(ASSETS / f"hero-{theme}.svg", hero(theme, f, m, defs))
        write(ASSETS / f"stats-{theme}.svg", stats(theme, f, m))
        write(ASSETS / f"oss-{theme}.svg", oss(theme, f, m))
        write(ASSETS / f"hoboradio-{theme}.svg", showcase(theme, f, m))
        write(ASSETS / f"footer-{theme}.svg", footer(theme, f, m))
    for key in ("sparkle", "clover", "moon"):
        write(ASSETS / f"divider-{key}.svg", divider(m, key))
    write(ASSETS / "worlds" / "manuka-pumpkin-field.svg", feature("latest/manuka-pumpkin-field.webp", "マヌカボチャ畑 / Manuka Pumpkin Field"))
    write(ASSETS / "products" / "vpm.svg", vpm_banner(f, m))
    tiles(f)


if __name__ == "__main__":
    main()
