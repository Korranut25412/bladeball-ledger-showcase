#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clip.py — ใส่ข้อความโพสต์ลงคลิปบอร์ดแบบเป๊ะตามไฟล์ แล้วบอกแฮชไว้เช็กในเบราว์เซอร์

ทำไมต้องมี (บั๊ก 17 พ.ย. 2569)
  - พิมพ์ข้อความไทยเองในคำสั่ง JS → คำเพี้ยน (โพสต์ระเบิดกลุ่มใบมีดบอลมี "เรา" งอกมา)
  - คลิปบอร์ด Windows โดนของอื่นทับระหว่างทาง (ได้ลิงก์ Instagram reel แทนข้อความ)
    น่าจะมาจากคลิปบอร์ดซิงก์มือถือ/การก๊อปของผู้ใช้ → แก้ที่ต้นเหตุไม่ได้
  → ใช้ไฟล์เป็นต้นฉบับเสมอ ใส่คลิปบอร์ดตอนจะวางเท่านั้น แล้วให้ fb_check.js
    เทียบแฮชในช่องโพสต์ก่อนกดโพสต์ทุกครั้ง ไม่ตรง = ห้ามโพสต์

ใช้งาน:  python posting/clip.py <เลข versions> <เลขโพสต์ 1-7>
  เช่น   python posting/clip.py 10 2   → ข้อความโพสต์ 2 (ระเบิด) ของ versions[10]
พิมพ์ออกมา: แฮช 8 ตัว (เอาไปใส่ใน fb_check.js) + บรรทัดแรกของข้อความ
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent


def put(g, p):
    """ใส่ข้อความโพสต์ p ของ versions[g] ลงคลิปบอร์ด คืน (key, hash, ok, บรรทัดแรก)
    แยกเป็นฟังก์ชันเพื่อให้ autopost.py เรียกใช้ได้ ไม่ต้องก๊อปโค้ดซ้ำ"""
    d = json.loads((ROOT / "ready" / "today.json").read_text(encoding="utf-8"))
    post = d["posts"][p - 1]
    text, h = post["versions"][g], post["hashes"][g]
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as f:
        f.write(text)
        tmp = f.name
    ps = (f"Set-Clipboard -Value (Get-Content -Raw -Encoding UTF8 '{tmp}'); "
          "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw")
    back = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                          capture_output=True, encoding="utf-8").stdout
    Path(tmp).unlink(missing_ok=True)
    return post["key"], h, back.strip() == text.strip(), text.splitlines()[0]


def main():
    if len(sys.argv) != 3:
        sys.exit("ใช้: python posting/clip.py <versions> <โพสต์ 1-7>")
    g, p = int(sys.argv[1]), int(sys.argv[2])
    d = json.loads((ROOT / "ready" / "today.json").read_text(encoding="utf-8"))
    post = d["posts"][p - 1]
    text, h = post["versions"][g], post["hashes"][g]

    # ส่งผ่านไฟล์ UTF-8 ไม่ส่งผ่าน argument/pipe เพราะคอนโซล Windows เป็น cp1252 ภาษาไทยจะกลายเป็น ????
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as f:
        f.write(text)
        tmp = f.name
    ps = (f"Set-Clipboard -Value (Get-Content -Raw -Encoding UTF8 '{tmp}'); "
          "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw")
    back = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                          capture_output=True, encoding="utf-8").stdout
    Path(tmp).unlink(missing_ok=True)

    # อ่านคลิปบอร์ดกลับมาเทียบทันที — ถ้าโดนทับตั้งแต่ตรงนี้ให้รู้เลย
    ok = back.strip() == text.strip()
    print(f"{post['key']} versions[{g}] hash={h} clipboard={'OK' if ok else 'ไม่ตรง!'}")
    print(text.splitlines()[0])
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
