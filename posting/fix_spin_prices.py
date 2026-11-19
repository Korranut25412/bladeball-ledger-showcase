#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_spin_prices.py — แก้เลขราคา (ตัวขาวขอบดำ) ในรูปสปิน Desktop\\Bladeball\\รับซื้อ\\36.png
ไม่แตะต้นฉบับ: เขียนผลไปที่ไฟล์ปลายทางที่สั่ง

เรท (ผู้ใช้กำหนด 16 พ.ย. 2569): 10 สปิน = 480 โทเค่น = 80 บาท (÷6) · Battlepass = 90 บาท
  ร้านล่าง (Gamepass/Coins) = โทเค่น ÷ 3 ให้กำไรเท่ามัธยฐานทั้งร้าน · ราคาโทเค่นจริงแคปจากร้านในเกม 16 พ.ย. 2569

วิธีลบเลขเก่า (ไม่มี OpenCV ในเครื่อง):
  หาพิกเซลขาวของตัวเลขในกรอบ → ขยายออกเท่าความหนาขอบดำ = บริเวณที่ต้องลบ
  → เติมสีจากขอบเข้าไปทีละชั้น (onion-peel) ให้กลืนกับพื้นหลัง แล้ววาดเลขใหม่ฟอนต์ Arial Bold ขาวขอบดำ
"""

import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

SRC = Path.home() / "OneDrive" / "Desktop" / "Bladeball" / "รับซื้อ" / "36.png"
FONT = r"C:\Windows\Fonts\arialbd.ttf"


def baht(token: int) -> int:
    return math.ceil(token / 6)


def shop(token: int) -> int:
    """ของในร้านล่าง (Gamepass/Coins) คิด 1 บาท ต่อ 3 โทเค่น
    ทุนโทเค่นเรทกลาง 11.1 โท/บาท (0.09฿/โท) → มาร์จิ้น ~73%
    = มัธยฐานมาร์จิ้นทั้งร้าน (73.0%, v_sale 16 พ.ย. 2569) ตามที่ผู้ใช้เลือก
    ÷6 เดิมได้แค่ ~46% ผู้ใช้ว่ากำไรน้อยไม่คุ้มกด · ÷4 (~64%) ผู้ใช้ให้ขึ้นอีก"""
    return math.ceil(token / 3)


# (กรอบค้นหา x0,y0,x1,y1, ราคาใหม่)  กรอบต้องครอบเลขเก่าทั้งตัวแต่ไม่ครอบตัวหนังสือขาวอื่น
EDITS = [
    ((185, 365, 345, 478), 90),               # Battlepass (ยกเว้น ตั้ง 90)
    ((1140, 1295, 1345, 1410), baht(480)),    # 10 สปิน 480 โทเค่น
    # แถวบน: Trading Sign · Double Coins · Instant Spin · VIP · 1,000 · 3,750 Coins
    ((0, 1690, 110, 1775), shop(112)),
    ((215, 1690, 325, 1775), shop(240)),
    ((462, 1690, 575, 1775), shop(120)),
    ((672, 1690, 790, 1775), shop(240)),
    ((925, 1690, 1005, 1775), shop(60)),
    ((1178, 1690, 1295, 1775), shop(180)),
    # แถวล่าง: VIP · 1,000 · 3,750 · 8,000 · 14,500 · 24,000 Coins
    ((0, 1938, 100, 2000), shop(240)),
    ((228, 1938, 305, 2000), shop(60)),
    ((468, 1938, 585, 2000), shop(180)),
    ((672, 1938, 790, 2000), shop(360)),
    ((922, 1938, 1040, 2000), shop(600)),
    ((1165, 1938, 1315, 2000), shop(900)),
]


def dilate(m: np.ndarray, r: int) -> np.ndarray:
    out = m.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx * dx + dy * dy <= r * r:
                out |= np.roll(np.roll(m, dy, 0), dx, 1)
    return out


def fill(img: np.ndarray, mask: np.ndarray) -> None:
    """เติมพิกเซลใน mask จากเพื่อนบ้านที่รู้ค่าแล้ว ทีละชั้นจากขอบเข้าใน"""
    known = ~mask
    while (~known).any():
        acc = np.zeros_like(img)
        cnt = np.zeros(known.shape)
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)):
            k = np.roll(np.roll(known, dy, 0), dx, 1)
            acc += np.roll(np.roll(img, dy, 0), dx, 1) * k[..., None]
            cnt += k
        new = (~known) & (cnt > 0)
        if not new.any():
            break
        img[new] = acc[new] / cnt[new][:, None]
        known |= new


def main(dst: Path):
    im = Image.open(SRC).convert("RGB")
    arr = np.asarray(im).astype(float)
    jobs = []
    for (x0, y0, x1, y1), price in EDITS:
        sub = arr[y0:y1, x0:x1]
        white = (sub > 205).all(axis=2)
        # เอาเฉพาะแถบแนวนอนที่ยาวที่สุดที่มีขาวหนาแน่น = ตัวเลข
        # (กันเม็ดขาวกระจัดกระจาย/ตัวหนังสือเกมที่ติดกรอบ ทำให้วัดความสูงเพี้ยน)
        dense = white.sum(axis=1) > 3
        best, run, start = (0, 0), 0, 0
        for i, on in enumerate(list(dense) + [False]):
            if on:
                if run == 0:
                    start = i
                run += 1
            else:
                if run > best[1] - best[0]:
                    best = (start, start + run)
                run = 0
        keep = np.zeros_like(white)
        keep[best[0]:best[1]] = white[best[0]:best[1]]
        white = keep
        ys, xs = np.nonzero(white)
        h = ys.max() - ys.min() + 1
        stroke = max(4, round(h * 0.13))
        pad = stroke + 3
        # ทำงานบนกรอบที่ขยายแล้ว เพื่อให้มีพื้นหลังรอบๆ ไว้เติมสี
        X0, Y0 = max(0, x0 - pad), max(0, y0 - pad)
        X1, Y1 = min(arr.shape[1], x1 + pad), min(arr.shape[0], y1 + pad)
        big = np.zeros((Y1 - Y0, X1 - X0), bool)
        big[y0 - Y0:y1 - Y0, x0 - X0:x1 - X0] = white
        mask = dilate(big, stroke + 2)
        patch = arr[Y0:Y1, X0:X1].copy()
        fill(patch, mask)
        arr[Y0:Y1, X0:X1] = patch
        jobs.append((x0 + xs.min(), y0 + ys.min(), h, stroke, price))

    out = Image.fromarray(arr.clip(0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(out)
    for left, top, h, stroke, price in jobs:
        size = round(h / 0.716)  # ความสูงตัวเลข Arial ≈ 0.716 ของขนาดฟอนต์
        font = ImageFont.truetype(FONT, size)
        bx0, by0, _, _ = draw.textbbox((0, 0), str(price), font=font)
        draw.text((left - bx0, top - by0), str(price), font=font, fill="white",
                  stroke_width=stroke, stroke_fill="black")
        print(f"วาง {price} ที่ ({left},{top}) สูง {h}px")
    out.save(dst)
    print(f"เสร็จ → {dst}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main(Path(sys.argv[1]))
