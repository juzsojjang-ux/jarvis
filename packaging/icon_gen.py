"""JARVIS 앱 아이콘 생성 — macOS 스타일 라운드 사각 + 글로우 아크리액터 HUD.

산출물(packaging/ 에):
  - jarvis_icon_1024.png  (마스터)
  - jarvis.icns           (macOS .app 아이콘)
  - jarvis.ico            (Windows .exe 아이콘)
재현용:  python packaging/icon_gen.py
"""
from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
SS = 2048  # 슈퍼샘플
CY = (96, 224, 255)
MD = (79, 180, 221)
GD = (240, 190, 84)
DP = (40, 96, 128)


def _rounded_mask(size: int, radius_frac: float = 0.225) -> Image.Image:
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    r = int(size * radius_frac)
    pad = int(size * 0.06)
    d.rounded_rectangle((pad, pad, size - pad, size - pad), radius=r, fill=255)
    return m


def _bg(size: int) -> Image.Image:
    """딥 네이비→블랙 방사형 + 상단 살짝 밝은 림."""
    bg = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = bg.load()
    cx = cy = size / 2
    maxd = size * 0.72
    for y in range(size):
        for x in range(0, size, 1):
            dx, dy = (x - cx), (y - cy * 0.92)
            dist = math.hypot(dx, dy) / maxd
            t = max(0.0, min(1.0, dist))
            r = int(18 * (1 - t) + 4 * t)
            g = int(34 * (1 - t) + 8 * t)
            b = int(54 * (1 - t) + 14 * t)
            px[x, y] = (r, g, b, 255)
    return bg


def _orb(size: int) -> Image.Image:
    """아크리액터/HUD 링 — 시안 밴드 + 골드 아크 + 코어. 글로우 포함."""
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    g = ImageDraw.Draw(glow)
    cx = cy = size / 2

    def ring(draw, rad, w, col, a=255):
        draw.ellipse((cx - rad, cy - rad, cx + rad, cy + rad), outline=col + (a,), width=w)

    def arc(draw, rad, w, a0, a1, col, a=255):
        draw.arc((cx - rad, cy - rad, cx + rad, cy + rad), a0, a1, fill=col + (a,), width=w)

    R = size * 0.30
    # 글로우 레이어(블러용) — 두꺼운 시안/골드
    arc(g, R, int(size * 0.03), -70, 80, CY, 255)
    arc(g, R, int(size * 0.035), 150, 215, GD, 255)
    g.ellipse((cx - size*0.06, cy - size*0.06, cx + size*0.06, cy + size*0.06), fill=GD + (255,))
    glow = glow.filter(ImageFilter.GaussianBlur(size * 0.018))
    layer = Image.alpha_composite(layer, glow)
    d = ImageDraw.Draw(layer)

    # 외곽 눈금 + 가는 가이드
    ring(d, R * 1.32, max(2, int(size*0.004)), DP, 170)
    for k in range(72):
        ang = k / 72 * 2 * math.pi
        r0, r1 = R * 1.28, R * 1.34
        d.line((cx + math.cos(ang) * r0, cy + math.sin(ang) * r0,
                cx + math.cos(ang) * r1, cy + math.sin(ang) * r1), fill=MD + (140,),
               width=max(1, int(size * 0.0018)))
    # 메인 시안 밴드(상/우) + 골드 아크(좌)
    arc(d, R, int(size * 0.022), -70, 80, CY, 240)
    arc(d, R, int(size * 0.028), 150, 215, GD, 250)
    ring(d, R * 0.98, max(2, int(size*0.003)), CY, 200)
    ring(d, R * 0.70, max(2, int(size*0.003)), DP, 200)
    # 내부 음성파형 점선
    for k in range(64):
        ang = k / 64 * 2 * math.pi
        rr = R * 0.52 + (size * 0.010 if k % 2 else 0)
        pr = max(2, int(size * 0.004))
        d.ellipse((cx + math.cos(ang) * rr - pr, cy + math.sin(ang) * rr - pr,
                   cx + math.cos(ang) * rr + pr, cy + math.sin(ang) * rr + pr), fill=CY + (150,))
    # 중앙 코어
    cr = size * 0.052
    d.ellipse((cx - cr, cy - cr, cx + cr, cy + cr), fill=GD + (255,))
    d.ellipse((cx - size*0.024, cy - size*0.024, cx + size*0.024, cy + size*0.024),
              fill=(255, 244, 210, 255))
    return layer


def build() -> Path:
    bg = _bg(SS)
    orb = _orb(SS)
    art = Image.alpha_composite(bg, orb)
    # 라운드 사각 마스크 적용 + 미세 외곽선
    mask = _rounded_mask(SS)
    out = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    out.paste(art, (0, 0), mask)
    master = out.resize((1024, 1024), Image.LANCZOS)
    png = HERE / "jarvis_icon_1024.png"
    master.save(png)

    # iconset → icns (macOS)
    iconset = HERE / "JARVIS.iconset"
    iconset.mkdir(exist_ok=True)
    for sz, name in [(16, "16x16"), (32, "16x16@2x"), (32, "32x32"), (64, "32x32@2x"),
                     (128, "128x128"), (256, "128x128@2x"), (256, "256x256"),
                     (512, "256x256@2x"), (512, "512x512"), (1024, "512x512@2x")]:
        master.resize((sz, sz), Image.LANCZOS).save(iconset / f"icon_{name}.png")
    if sys.platform == "darwin":
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(HERE / "jarvis.icns")],
                       check=True)

    # .ico (Windows)
    master.save(HERE / "jarvis.ico",
                sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("아이콘 생성:", png, "/ jarvis.icns / jarvis.ico")
    return png


if __name__ == "__main__":
    build()
