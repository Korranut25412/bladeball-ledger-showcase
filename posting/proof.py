#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
proof.py — คำสั่ง "ดันโพสต์": เอารูปเทรด "Confirmed!" ไปตอบใต้คอมเมนต์ "จุดของออก" ในโพสต์หลัก (โพสต์ 7)
และเคลียร์รูปแคปอื่นที่ไม่เกี่ยวทิ้งลงถังขยะ

ทำไมทำแบบนี้
  - ผู้ใช้เทรดจากคอม แล้ว Snipping Tool เซฟรูปแคปไว้ที่ OneDrive\\Pictures\\Screenshots เองอัตโนมัติ
    → ไม่ต้องส่งรูปในแชท ดึงจากโฟลเดอร์นี้ได้เลย
  - สคริปต์แยกเองไม่ได้ว่ารูปไหนเป็นหน้าเทรด Confirmed (ไม่มี OCR) → ทำ "ภาพรวม" (sheet.jpg)
    เป็นรูปย่อมีเลขกำกับ ให้ Claude เปิดดูทีเดียวทั้งหมด (ประหยัดกว่าเปิดทีละรูปมาก) แล้วสั่งว่าเลขไหนลง เลขไหนทิ้ง
  - รูปที่ไม่ได้ระบุเลขทั้ง --post และ --trash จะไม่ถูกแตะเลย (ไม่แน่ใจ = เก็บไว้ก่อน)
  - "ทิ้ง" = ย้ายลงถังขยะ (Recycle Bin) ไม่ใช่ลบถาวร → พลาดยังกู้คืนได้
  - Claude in Chrome อัปโหลดได้เฉพาะไฟล์ในโฟลเดอร์ของแชท → ย่อรูปที่จะลงไว้ที่ posting/proof/
  - จดชื่อไฟล์ที่ลงแล้ว/ตัดสินแล้วไว้ใน proof/used.json กันลงซ้ำ และรูป Confirmed ต้นฉบับเก็บไว้ ไม่ลบ

ใช้งาน
  python posting/proof.py scan                     → ทำ proof/sheet.jpg + proof/pending.json จากรูปที่ยังไม่เคยตัดสิน
  python posting/proof.py pick --post 1 4 --trash 2 3
                                                   → ย่อรูป 1,4 ไว้ลง · ส่ง 2,3 ลงถังขยะ · พิมพ์ลิงก์โพสต์หลัก
"""

import argparse
import io
import json
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
SHOTS = Path.home() / "OneDrive" / "Pictures" / "Screenshots"
OUT = ROOT / "proof"
USED = OUT / "used.json"        # ชื่อไฟล์ที่ตัดสินแล้ว (ลงแล้ว/ทิ้งแล้ว) → scan รอบหน้าไม่หยิบซ้ำ
PENDING = OUT / "pending.json"  # เลข → ชื่อไฟล์ ของ sheet.jpg รอบล่าสุด
MAIN_POSTS = ROOT / "main_posts.json"  # ลิงก์โพสต์ 7 ของแต่ละกลุ่ม (Claude เขียนหลังโพสต์)
MAX_W = 1600
THUMB = 320   # ขนาดรูปย่อในภาพรวม ใหญ่พอให้อ่านคำว่า Confirmed! ออก
COLS = 4


def load(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def to_trash(path: Path):
    # ใช้ของ Windows เอง (ไม่ต้องลงไลบรารีเพิ่ม) ส่งลงถังขยะแทนการลบถาวร
    ps = ("Add-Type -AssemblyName Microsoft.VisualBasic; "
          "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($env:P, "
          "'OnlyErrorDialogs', 'SendToRecycleBin')")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   env={**__import__("os").environ, "P": str(path)}, check=True)


def scan():
    OUT.mkdir(exist_ok=True)
    used = set(load(USED, []))
    shots = sorted((p for p in SHOTS.iterdir()
                    if p.suffix.lower() in (".png", ".jpg", ".jpeg") and p.name not in used),
                   key=lambda p: p.stat().st_mtime)
    if not shots:
        save(PENDING, {})
        print("ไม่มีรูปแคปใหม่")
        return

    rows = (len(shots) + COLS - 1) // COLS
    sheet = Image.new("RGB", (COLS * THUMB, rows * THUMB), "white")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 36)
    except OSError:
        font = ImageFont.load_default()
    pending = {}
    for i, p in enumerate(shots, 1):
        im = Image.open(p).convert("RGB")
        im.thumbnail((THUMB - 8, THUMB - 8))
        x, y = ((i - 1) % COLS) * THUMB, ((i - 1) // COLS) * THUMB
        sheet.paste(im, (x + 4, y + 4))
        draw.rectangle([x + 4, y + 4, x + 54, y + 48], fill="red")
        draw.text((x + 10, y + 6), str(i), fill="white", font=font)
        pending[str(i)] = p.name
    sheet.save(OUT / "sheet.jpg", "JPEG", quality=80)
    save(PENDING, pending)
    print(f"{len(shots)} รูปใหม่ → {OUT / 'sheet.jpg'}")
    for k, v in pending.items():
        print(f"  {k}: {v}")


def pick(post: list[int], trash: list[int]):
    pending = load(PENDING, {})
    if set(post) & set(trash):
        sys.exit("เลขเดียวกันอยู่ทั้ง --post และ --trash")
    used = load(USED, [])
    ready = []
    for n in post:
        src = SHOTS / pending[str(n)]
        im = Image.open(src).convert("RGB")
        if im.width > MAX_W:
            im = im.resize((MAX_W, round(im.height * MAX_W / im.width)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85, optimize=True)  # ไม่ส่ง exif = ลบ EXIF
        dst = OUT / (src.stem.replace(" ", "_") + ".jpg")
        dst.write_bytes(buf.getvalue())
        used.append(src.name)
        ready.append(dst)
    for n in trash:
        src = SHOTS / pending[str(n)]
        if src.exists():
            to_trash(src)
        used.append(src.name)
        print(f"ลงถังขยะ: {src.name}")
    save(USED, used)

    print(f"\nรูปที่จะลง ({len(ready)}):")
    for d in ready:
        print(f"  {d}")
    posts = load(MAIN_POSTS, [])
    print(f"\nโพสต์หลักที่ต้องไปตอบใต้ 'จุดของออก' ({len(posts)} โพสต์):")
    for p in posts:
        print(f"  {p['group']}: {p['url']}")
    if not posts:
        print("  ยังไม่มี — ต้องโพสต์ 7 รวมทุกอย่างก่อน แล้วจดลิงก์ลง main_posts.json")


QUEUE = OUT / "queue.json"  # คิวงานตอบรูป: ทีละรูป ทีละโพสต์ ให้ทำตามลำดับ ไม่ต้องคิดเอง
AUTO_MIN = 0.12  # สัดส่วนพิกเซลสีเขียวช่อง Confirmed ขั้นต่ำของแต่ละฝั่ง (ทดสอบ 18 พ.ย.: Confirmed สองฝั่ง ≥0.17 · รูปอื่น ≈0)


def _green_frac(im, box):
    c = im.crop(box)
    px = list(c.getdata())
    n = sum(1 for r, g, b in px if r < 75 and 85 < g < 130 and 55 < b < 115 and g > r + 35)
    return n / max(1, len(px))


def is_both_confirmed(path: Path) -> bool:
    """หน้า Trade ที่ช่องซ้าย+ขวาเป็นสีเขียว Confirmed ทั้งคู่ (ฝั่งเดียว = อีกฝั่งไม่เขียว → False)"""
    im = Image.open(path).convert("RGB")
    im.thumbnail((400, 400))
    w, h = im.size
    left = _green_frac(im, (0, int(h * .25), w // 2, int(h * .9)))
    right = _green_frac(im, (w // 2, int(h * .25), w, int(h * .9)))
    return left >= AUTO_MIN and right >= AUTO_MIN


def auto():
    """scan + เลือกรูป Confirmed สองฝั่งเองด้วยโค้ด (ไม่ทิ้งรูปอื่น) + สร้างคิวตอบรูป"""
    scan()
    pending = load(PENDING, {})
    nums = [int(k) for k, v in pending.items() if is_both_confirmed(SHOTS / v)]
    print(f"\nเข้าเกณฑ์ Confirmed สองฝั่ง (ตรวจด้วยสี): {nums}")
    if not nums:
        print("ไม่มีรูปที่ลงได้ — จบ")
        return
    pick(nums, [])
    build_queue()


def build_queue():
    """แบ่งรูปในโฟลเดอร์ proof ที่ยังไม่เคยอยู่ในคิว ให้โพสต์หลักทุกโพสต์ เท่าๆ กัน (เกินเศษให้โพสต์ต้นๆ)"""
    posts = load(MAIN_POSTS, [])
    if not posts:
        sys.exit("ไม่มี main_posts.json — ต้องลงโพสต์ 7 ก่อน")
    queue = load(QUEUE, [])
    queued = {t["image"] for t in queue}
    done_imgs = set(load(OUT / "replied.json", []))
    imgs = [str(p) for p in sorted(OUT.glob("Screenshot_*.jpg"))
            if str(p) not in queued and p.name not in done_imgs]
    if not imgs:
        print("ไม่มีรูปใหม่เข้าคิว")
        return
    base, extra = divmod(len(imgs), len(posts))
    i = 0
    for k, post in enumerate(posts):
        for _ in range(base + (1 if k < extra else 0)):
            queue.append({"group": post["group"], "url": post["url"], "image": imgs[i], "done": False})
            i += 1
    save(QUEUE, queue)
    print(f"เข้าคิว {len(imgs)} รูป → {QUEUE} · ต่อไปรัน: python posting/proof.py next")


def next_task():
    queue = load(QUEUE, [])
    left = [t for t in queue if not t["done"]]
    if not left:
        print("คิวว่าง — ตอบรูปครบแล้ว (ถ้ายังไม่ได้ commit ให้ commit)")
        return
    t = left[0]
    print(f"เหลือ {len(left)} รูป · ทำรูปนี้:")
    print(f"กลุ่ม : {t['group']}")
    print(f"ลิงก์ : {t['url']}")
    print(f"รูป   : {t['image']}")
    print(f"รูป(JSON) : {json.dumps(t['image'])}")
    print("เสร็จแล้วรัน: python posting/proof.py done")


def mark_done():
    queue = load(QUEUE, [])
    for t in queue:
        if not t["done"]:
            t["done"] = True
            replied = load(OUT / "replied.json", [])
            replied.append(Path(t["image"]).name)
            save(OUT / "replied.json", replied)
            save(QUEUE, queue)
            left = sum(1 for x in queue if not x["done"])
            print(f"บันทึกแล้ว: {Path(t['image']).name} → {t['group']} · เหลือ {left} รูป")
            return
    print("ไม่มีรูปค้างในคิว")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan")
    sub.add_parser("auto")
    sub.add_parser("next")
    sub.add_parser("done")
    pk = sub.add_parser("pick")
    pk.add_argument("--post", type=int, nargs="*", default=[])
    pk.add_argument("--trash", type=int, nargs="*", default=[])
    args = ap.parse_args()
    if args.cmd == "scan":
        scan()
    elif args.cmd == "auto":
        auto()
    elif args.cmd == "next":
        next_task()
    elif args.cmd == "done":
        mark_done()
    else:
        pick(args.post, args.trash)


if __name__ == "__main__":
    main()
