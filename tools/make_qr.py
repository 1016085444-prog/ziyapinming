"""生成子牙品命的推广二维码海报。

一条贯穿全篇的取舍：**能扫上永远优先于好看**。
所以码区一律是浅底深模块——反色码（深底浅模块）在新手机上多半能扫，
但老设备和部分小程序扫码器会失败，而这个码是要发给陌生人的，
扫不出等于白做。高级感放在码区之外的版面里，不去动码本身的对比度。

用法：
    .venv/bin/python tools/make_qr.py
产物落在 qr/ 目录。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import segno
from PIL import Image, ImageDraw, ImageFont

# 站点地址取自 config.SITE_URL，不在这里再写一份——地址写两处，
# 迟早漏改一处，而漏改的那处恰好是已经印出去发给陌生人的那张码。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config                                                  # noqa: E402

URL = config.SITE_URL

OUT_DIR = Path(__file__).resolve().parent.parent / "qr"

SONGTI = "/System/Library/Fonts/Supplemental/Songti.ttc"
HEITI = "/System/Library/Fonts/STHeiti Medium.ttc"

# 站点同款配色
INK = (11, 13, 20)
INK_2 = (18, 21, 29)
GOLD = (205, 163, 73)
GOLD_LIT = (232, 206, 138)
GOLD_DIM = (138, 114, 56)
CREAM = (245, 239, 226)      # 码区底色：暖白而非纯白，比纯黑白耐看且不损识别
MODULE = (16, 19, 27)        # 码区模块：近墨而非纯黑
TEXT = (231, 227, 217)
MUTED = (139, 135, 120)


def font(path, size, index=0):
    return ImageFont.truetype(path, size, index=index)


def radial_glow(size, center, radius, color, max_alpha):
    """一团径向光晕。Pillow 没有渐变原语，按行画同心圆最省事也够用。"""
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    steps = 60
    for i in range(steps, 0, -1):
        r = radius * i / steps
        a = int(max_alpha * (1 - i / steps) ** 2)
        d.ellipse(
            [center[0] - r, center[1] - r, center[0] + r, center[1] + r],
            fill=color + (a,),
        )
    return layer


def rounded_module(d, x, y, s, color, radius_ratio=0.28):
    """圆角模块。圆角别超过 30%，再大就会啃掉模块边缘影响识别。"""
    r = max(1, int(s * radius_ratio))
    d.rounded_rectangle([x, y, x + s - 1, y + s - 1], radius=r, fill=color)


def draw_qr(canvas, matrix, ox, oy, scale, quiet):
    """手绘码区：定位角画成圆角回字，数据模块画成圆角方块。"""
    d = ImageDraw.Draw(canvas)
    n = len(matrix)

    def in_finder(r, c):
        return (
            (r < 7 and c < 7)
            or (r < 7 and c >= n - 7)
            or (r >= n - 7 and c < 7)
        )

    # 数据模块
    for r in range(n):
        for c in range(n):
            if not matrix[r][c] or in_finder(r, c):
                continue
            rounded_module(
                d, ox + (c + quiet) * scale, oy + (r + quiet) * scale, scale, MODULE
            )

    # 三个定位角必须是标准直角方块——解码器靠它定位和判方向，
    # 削圆角会把角上的模块吃掉，整个码直接失效（实测过：圆角 2.1 个模块时
    # 三个定位角共 12 个模块翻转，任何解码器都读不出来）。
    # 想要的「高级感」交给数据模块的圆角，那部分是安全的。
    for (fr, fc) in [(0, 0), (0, n - 7), (n - 7, 0)]:
        x0 = ox + (fc + quiet) * scale
        y0 = oy + (fr + quiet) * scale
        s7 = scale * 7
        d.rectangle([x0, y0, x0 + s7 - 1, y0 + s7 - 1], fill=MODULE)
        d.rectangle(
            [x0 + scale, y0 + scale, x0 + s7 - scale - 1, y0 + s7 - scale - 1],
            fill=CREAM,
        )
        d.rectangle(
            [x0 + scale * 2, y0 + scale * 2,
             x0 + scale * 5 - 1, y0 + scale * 5 - 1],
            fill=MODULE,
        )


def center_badge(canvas, cx, cy, r):
    """中心徽标。纠错等级 H 可恢复约 30%，这里只遮约 4% 面积，余量充足。"""
    d = ImageDraw.Draw(canvas)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=CREAM)
    d.ellipse([cx - r + 3, cy - r + 3, cx + r - 3, cy + r - 3],
              outline=GOLD, width=max(2, r // 14))
    f = font(SONGTI, int(r * 1.15), index=1)
    box = d.textbbox((0, 0), "子", font=f)
    d.text((cx - (box[2] - box[0]) / 2 - box[0],
            cy - (box[3] - box[1]) / 2 - box[1]),
           "子", font=f, fill=(24, 20, 12))


def build_poster(path, w=1080, h=1500):
    canvas = Image.new("RGB", (w, h), INK)

    # 背景：上方暖金、下方冷蓝，与站点同一套冷暖对撞
    canvas = Image.alpha_composite(
        canvas.convert("RGBA"),
        radial_glow((w, h), (w * 0.5, h * 0.06), w * 0.95, GOLD, 46),
    )
    canvas = Image.alpha_composite(
        canvas,
        radial_glow((w, h), (w * 0.5, h * 1.02), w * 0.9, (95, 151, 196), 34),
    ).convert("RGB")

    d = ImageDraw.Draw(canvas)

    # ── 页眉 ──
    f_brand = font(SONGTI, 82, index=1)
    box = d.textbbox((0, 0), "子牙品命", font=f_brand)
    d.text(((w - (box[2] - box[0])) / 2 - box[0], 96), "子牙品命",
           font=f_brand, fill=GOLD_LIT)

    f_sub = font(HEITI, 27)
    sub = "子 平 八 字   ·   排 盘 问 命"
    box = d.textbbox((0, 0), sub, font=f_sub)
    d.text(((w - (box[2] - box[0])) / 2 - box[0], 206), sub,
           font=f_sub, fill=MUTED)

    # 金线 + 菱形，站点里反复出现的分隔母题
    def rule(y, half=210):
        cx = w // 2
        for i in range(half):
            a = int(150 * (1 - abs(i - half / 2) / (half / 2)))
            d.line([cx - half + i * 2, y, cx - half + i * 2 + 1, y],
                   fill=(GOLD_DIM[0], GOLD_DIM[1], GOLD_DIM[2]) if a > 40 else INK_2)
        d.regular_polygon((cx, y, 7), 4, rotation=0, fill=GOLD)

    rule(268)

    # ── 主标题 ──
    f_t1 = font(SONGTI, 76, index=1)
    box = d.textbbox((0, 0), "品命，茗有余香", font=f_t1)
    d.text(((w - (box[2] - box[0])) / 2 - box[0], 312), "品命，茗有余香",
           font=f_t1, fill=TEXT)

    # ── 码区面板 ──
    panel_w = 760
    panel_x = (w - panel_w) // 2
    panel_y = 452
    d.rounded_rectangle(
        [panel_x - 5, panel_y - 5, panel_x + panel_w + 5, panel_y + panel_w + 5],
        radius=48, outline=GOLD_DIM, width=3,
    )
    d.rounded_rectangle(
        [panel_x, panel_y, panel_x + panel_w, panel_y + panel_w],
        radius=44, fill=CREAM,
    )

    # 纠错 H：中心放徽标后仍有充足余量
    qr = segno.make(URL, error="h")
    matrix = [[bool(v) for v in row] for row in qr.matrix]
    n = len(matrix)
    quiet = 4                                    # 静区必须留，少于 4 模块识别率骤降
    scale = (panel_w - 56) // (n + quiet * 2)
    span = (n + quiet * 2) * scale
    ox = panel_x + (panel_w - span) // 2
    oy = panel_y + (panel_w - span) // 2

    draw_qr(canvas, matrix, ox, oy, scale, quiet)
    center_badge(canvas, ox + span // 2, oy + span // 2, int(span * 0.105))

    # ── 行动号召 ──
    y = panel_y + panel_w + 62
    f_cta = font(SONGTI, 54, index=1)
    box = d.textbbox((0, 0), "扫码免费排盘", font=f_cta)
    d.text(((w - (box[2] - box[0])) / 2 - box[0], y), "扫码免费排盘",
           font=f_cta, fill=GOLD_LIT)

    f_note = font(HEITI, 29)
    for i, line in enumerate([
        "节气按太阳视黄经实时推算，时柱经真太阳时校正",
        "不限次数 · 不留存生日 · 约 10 秒出盘",
    ]):
        box = d.textbbox((0, 0), line, font=f_note)
        d.text(((w - (box[2] - box[0])) / 2 - box[0], y + 88 + i * 46), line,
               font=f_note, fill=MUTED)

    canvas.save(path, "PNG", optimize=True)
    return path, n, scale


def build_plain(path, box_px=1000):
    """无版面的纯码，留给需要自己排版的场合（海报、名片、朋友圈九宫格）。"""
    qr = segno.make(URL, error="h")
    matrix = [[bool(v) for v in row] for row in qr.matrix]
    n = len(matrix)
    quiet = 4
    scale = box_px // (n + quiet * 2)
    span = (n + quiet * 2) * scale

    img = Image.new("RGB", (span, span), CREAM)
    draw_qr(img, matrix, 0, 0, scale, quiet)
    center_badge(img, span // 2, span // 2, int(span * 0.105))
    img.save(path, "PNG", optimize=True)
    return path


if __name__ == "__main__":
    OUT_DIR.mkdir(exist_ok=True)
    poster, n, scale = build_poster(OUT_DIR / "海报.png")
    plain = build_plain(OUT_DIR / "纯二维码.png")
    print("矩阵 {0}×{0}，模块 {1}px，纠错等级 H".format(n, scale))
    for p in (poster, plain):
        print("{}  {:.0f} KB".format(p.name, p.stat().st_size / 1024))
