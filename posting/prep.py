#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prep.py — เตรียมรอบโพสต์บอลในคำสั่งเดียว (แพทเทิร์นเดียวกับ ขายอสังหา/landsale)

ทำอะไร
  1. สุ่มรูปโพสต์ละไม่เกิน 10 รูปจาก Desktop\\Bladeball\\<โฟลเดอร์> (ไม่แตะต้นฉบับ)
     ยกเว้นโพสต์ 7 รวมทุกอย่าง: สุ่มจากหลายโฟลเดอร์ ~32 รูป แบ่งอัปหลายชุด
  2. ย่อเป็น JPG กว้างไม่เกิน 1600px ลบ EXIF ให้รวมกันไม่เกิน 9.5MB ต่อโพสต์
  3. บันทึกไว้ใน posting/ready/<n>_<ชื่อ>/  ซึ่งอยู่ในโฟลเดอร์โปรเจกต์
     (Claude in Chrome อัปโหลดได้เฉพาะไฟล์ในโฟลเดอร์ของแชท → ห้ามอัปจาก Desktop\\Bladeball ตรงๆ)
  4. เขียน posting/ready/today.json = ข้อความ (สลับบรรทัดเปิดทุกกลุ่ม) + path รูปของแต่ละโพสต์

ใช้งาน:  python posting/prep.py            (สุ่มใหม่ทุกครั้ง)
         python posting/prep.py --seed 5   (อยากได้ชุดเดิมซ้ำ)
"""

import argparse
import io
import json
import random
import re
import shutil
import sys
from datetime import date
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from PIL import Image

ROOT = Path(__file__).resolve().parent
SRC = Path.home() / "OneDrive" / "Desktop" / "Bladeball"
OUT = ROOT / "ready"
MAX_W = 1600
MAX_PER_POST = 10
BUDGET = int(9.5 * 1024 * 1024)

POSTS = [
    ("1_รับซื้อ", "รับซื้อ",
     "รับซื้อของในเกมทุกชิ้นค้าบ ชิ้นเดียวก็รับ เลิกเล่นยกไอดีก็รับ\n"
     "ไม่รู้ว่าของตัวเองราคาเท่าไหร่ แคปมาให้ดู ตีราคาให้ฟรี ไม่ขายก็ไม่เป็นไร\n"
     "รับโทเรทเหมา · รับกดกิฟพาส · รับหาของ · รับสปินสกิล\n"
     "ทักมาได้ตลอด ตอบไวครับ"),
    ("2_ระเบิด", "Ex",
     "ระเบิดมีครบทุกลายในเกมค้าบ ส่งได้ทันทีไม่ต้องรอคิว\n"
     "ราคาเริ่ม 50 มีให้ทุกงบ\n"
     "บอกงบมาเลยครับ เดี๋ยวจัดให้ดูว่าได้ลายไหนบ้าง"),
    ("3_emote", "Emote",
     "emote ท่าเต้นมีครบทุกท่าในเกมค้าบ พร้อมส่งเลย\n"
     "เริ่มต้นท่าละ 50 ในรูปเอามาโชว์แค่บางส่วน\n"
     "อยากได้ท่าไหนทักมาถาม หรือบอกงบมาก็ได้ครับ"),
    ("4_ดาบ", "Index",
     "ดาบมีทุกเล่มในเกมค้าบ ส่งได้ทันที\n"
     "ราคาเริ่ม 50 ไม่รู้จะเลือกเล่มไหน บอกงบมา\n"
     "เดี๋ยวจัดชุดให้เลือกตามงบเลยครับ"),
    ("5_ดาบติดตูด", "รวม",
     "ดาบติดตูด ดาบแบกหลัง มีครบทุกแบบค้าบ พร้อมส่ง\n"
     "ราคาเริ่ม 50 ชอบแบบไหนทักมาได้เลย\n"
     "บอกงบมาก็ได้ครับ เลือกให้ตรงงบ"),
    ("6_เซ็ตดาบ", "เซ็ต",
     "เซ็ตดาบมีครบทุกเซ็ตค้าบ ในรูปยังไม่หมด มีอีกเยอะ พร้อมส่ง\n"
     "ชอบเซ็ตไหนทักมาถามได้เลย\n"
     "หรือบอกงบมา เดี๋ยวจัดเซ็ตที่ได้ในงบให้ดูครับ"),
    # โพสต์ 7 = โพสต์หลัก "รวมทุกอย่าง" (แบบเดียวกับที่ลงเอง 6 ต.ค. แล้วได้คนทักแชท)
    # รูปดึงจากหลายโฟลเดอร์ ไม่ใช่โฟลเดอร์เดียว → ใส่เป็นลิสต์ (โฟลเดอร์, จำนวนรูป)
    # ลำดับรูป = ลำดับที่คนเห็นในฟีด (ผู้ใช้สั่ง 16 พ.ย. 2569):
    #   รูปรับซื้อ + สปิน (โฟลเดอร์ "รับซื้อ") นำเสมอ เหมือนโพสต์เดิม 6 ต.ค.
    #   → ดาบ (โฟลเดอร์ "รวม") กับเซ็ตมากสุด เพราะขายออกบ่อยสุด → ระเบิดกับท่าไว้ท้าย · ไม่ใช้ Index
    # โทเค่นเลิกขายแล้ว (16 พ.ย. 2569) → ไม่มีบรรทัดเรทโทเค่น
    ("7_รวมทุกอย่าง",
     [("รับซื้อ", 2), ("รวม", 9), ("เซ็ต", 9), ("Ex", 4), ("Emote", 4)],
     "โพสนี้รวมทุกอย่างที่ขายนะครับ จะตั้งจุดของออกไว้ในคอมเมนต์ให้เห็นด้วย "
     "รูปอาจจะเยอะนิดนึงนะครับ สนใจชิ้นไหนทักมาสอบถามได้เลยนะค้าบ\n"
     "** สินค้าอื่นนอกเหนือจากในรูปสามารถทักถามได้ทุกชิ้นนะครับ **\n"
     "-รับของราคาร้อน\n"
     "-รับกด bp / สุ่มสปิน\n"
     "-ขายระเบิดทุกชิ้น\n"
     "-ขายดาบทุกชิ้น\n"
     "-ขายท่าทางทุกชิ้น"),
]

# โพสต์ที่ต้องคอมเมนต์ต่อทันทีหลังโพสต์ขึ้น (คอมเมนต์นี้คือที่ไว้ตอบกลับด้วยรูปเทรดทุกครั้งที่ขายได้)
COMMENT_AFTER = {"7_รวมทุกอย่าง": "จุดของออกครับ"}

# บรรทัดหัวที่สลับให้แต่ละกลุ่ม (เนื้อหาเดิมไม่เปลี่ยน แค่ไม่ให้ข้อความซ้ำเป๊ะ)
HEADERS = ["", "🔥 ", "✨ ", "📢 ", "⚔️ ", "💥 ", "🎮 ", "✅ "]
FOOTERS = ["", "\n📩 ทักแชทได้เลย", "\n💬 สนใจทักมานะครับ", "\n⚡ ตอบไว ส่งไว"]


def text_hash(s: str) -> str:
    """ลายนิ้วมือสั้นๆ ของข้อความ (FNV-1a 32 บิต) — ใช้เช็กว่าข้อความในช่องโพสต์ตรงไฟล์เป๊ะ
    ทำไม: 17 พ.ย. 2569 พิมพ์ข้อความไทยเองแล้วเพี้ยน ("เดี๋ยวเราจัด") และคลิปบอร์ดโดนลิงก์ IG ทับ
    → ก่อนกดโพสต์ให้ fb_check.js คิดแฮชแบบเดียวกันในเบราว์เซอร์ ต้องตรงกับค่านี้
    ต้องตัดช่องว่าง/ขึ้นบรรทัดให้เหมือนกันก่อน เพราะช่องเขียนของ FB แปลง \\n เป็นย่อหน้า"""
    s = re.sub(r"[​-‍﻿]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    h = 0x811C9DC5
    for ch in s:
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return f"{h:08x}"


def shrink(path: Path, quality: int) -> bytes:
    im = Image.open(path)
    im = im.convert("RGB")
    if im.width > MAX_W:
        im = im.resize((MAX_W, round(im.height * MAX_W / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True)  # ไม่ส่ง exif = ลบ EXIF
    return buf.getvalue()


def list_images(folder: str) -> list[Path]:
    return sorted(p for p in (SRC / folder).iterdir()
                  if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))


def build_post(key: str, folder, rng: random.Random) -> list[list[str]]:
    """คืนรูปเป็น "ชุดอัปโหลด" แต่ละชุดรวมไม่เกิน 9.5MB
    (file_upload รับได้ครั้งละ ~10MB → โพสต์ที่รูปเยอะต้องอัปหลายครั้งในโพสต์เดียว)"""
    dst = OUT / key
    dst.mkdir(parents=True)

    if isinstance(folder, str):
        # โพสต์ปกติ: ≤10 รูป ลดคุณภาพจนรวมกันอัปได้ครั้งเดียว (พฤติกรรมเดิม)
        files = list_images(folder)
        pick = rng.sample(files, min(MAX_PER_POST, len(files)))
        for q in (85, 75, 65, 55):
            blobs = [shrink(p, q) for p in pick]
            if sum(map(len, blobs)) <= BUDGET:
                break
        while sum(map(len, blobs)) > BUDGET and len(blobs) > 1:  # ยังเกิน → ตัดรูปออก
            blobs.pop()
    else:
        # โพสต์รวม: สุ่มจากหลายโฟลเดอร์ตามจำนวนที่กำหนด เรียงตามลำดับโฟลเดอร์
        # ไม่ต้องบีบให้รวมกัน ≤9.5MB เพราะแบ่งอัปหลายชุดได้ → ใช้คุณภาพ 80 คงที่
        q = 80
        pick = []
        for sub, n in folder:
            files = list_images(sub)
            pick += rng.sample(files, min(n, len(files)))
        blobs = [shrink(p, q) for p in pick]

    # แบ่งเป็นชุดอัปโหลด: ใส่ต่อไปเรื่อยๆ จนชุดนั้นจะเกิน 9.5MB ค่อยขึ้นชุดใหม่
    batches, cur, size = [], [], 0
    for i, b in enumerate(blobs, 1):
        f = dst / f"{i:02d}.jpg"
        f.write_bytes(b)
        if cur and size + len(b) > BUDGET:
            batches.append(cur)
            cur, size = [], 0
        cur.append(str(f))
        size += len(b)
    if cur:
        batches.append(cur)
    print(f"{key}: {len(blobs)} รูป {sum(map(len, blobs)) / 1048576:.1f}MB "
          f"(q={q}) อัป {len(batches)} ครั้ง")
    return batches


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=None)
    # 16 = กลุ่มเดิม 7 + กลุ่มใหม่ 8 (17 พ.ย. 2569) เผื่อ 1 · ลำดับกลุ่มดูหัวข้อ "เลขกลุ่ม → versions" ใน โพสต์บอล.md
    ap.add_argument("--groups", type=int, default=16, help="จำนวนกลุ่ม = จำนวนเวอร์ชันข้อความ")
    args = ap.parse_args()
    rng = random.Random(args.seed)

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()

    posts = []
    for key, folder, text in POSTS:
        batches = build_post(key, folder, rng)
        # บั๊กเดิม: สุ่มหัวใหม่ทุกกลุ่ม → สองกลุ่มได้หัว+ท้ายซ้ำกันได้ = ข้อความเหมือนเป๊ะ
        # แก้: สุ่มจุดเริ่มครั้งเดียวต่อโพสต์ แล้วเลื่อนทีละ 1 → 8 กลุ่มติดกันได้หัวไม่ซ้ำแน่นอน
        # ท้ายเลื่อนเพิ่มทุก 8 กลุ่ม (g // 8) → กลุ่ม g กับ g+8 หัวซ้ำแต่ท้ายต่าง จึงไม่ซ้ำเป๊ะ
        off = rng.randrange(len(HEADERS))
        versions = []
        for g in range(args.groups):
            h = HEADERS[(g + off) % len(HEADERS)]
            f = FOOTERS[(g + g // len(HEADERS)) % len(FOOTERS)]
            versions.append(h + text + f)
        assert len(set(versions)) == len(versions), f"{key}: มีข้อความซ้ำกันระหว่างกลุ่ม"
        post = {"key": key,
                "images": [p for b in batches for p in b],  # รูปทั้งหมด
                "batches": batches,  # อัปทีละชุด (โพสต์ปกติมีชุดเดียว)
                "versions": versions,
                "hashes": [text_hash(v) for v in versions]}  # ให้ fb_check.js เทียบ
        if key in COMMENT_AFTER:
            post["comment_after"] = COMMENT_AFTER[key]
        posts.append(post)

    (OUT / "today.json").write_text(
        json.dumps({"date": date.today().isoformat(), "posts": posts},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nเสร็จ → {OUT / 'today.json'}  (versions[i] = ข้อความของกลุ่มลำดับที่ i)")


if __name__ == "__main__":
    main()
