"""
ถอดคอลัมน์ที่ไม่เคยมีใครกรอกออกจากตาราง sale

วิธีใช้
    PYTHONIOENCODING=utf-8 python tools/drop_unused_columns.py         # ตรวจอย่างเดียว
    PYTHONIOENCODING=utf-8 python tools/drop_unused_columns.py --run   # ทำจริง

คอลัมน์ที่ถอด: category · fb_group · customer_ref · list_baht
เหตุผลเต็มอยู่ในคอมเมนต์หัวตาราง sale ใน schema.sql

ทำไมต้องมีสคริปต์แยก ไม่แก้ schema.sql อย่างเดียวจบ
--------------------------------------------------
schema.sql ใช้ CREATE TABLE IF NOT EXISTS ซึ่งแปลว่า
ตารางที่มีอยู่แล้วจะไม่ถูกสร้างใหม่ตามโครงใหม่
ถ้าไม่มีสคริปต์นี้ ฐานข้อมูลจริงจะยังมีคอลัมน์เก่าค้างอยู่
แล้ว INSERT ที่ไม่ใส่คอลัมน์เหล่านั้นจะยังทำงานได้ (เพราะเป็น NULL ได้)
กลายเป็นว่าโค้ดกับฐานข้อมูลไม่ตรงกันแบบเงียบๆ จนกว่าจะเจอปัญหาทีหลัง

ความปลอดภัย
  - ค่าเริ่มต้นคือตรวจอย่างเดียว ต้องพิมพ์ --run เองถึงจะแก้
  - ตรวจก่อนว่าคอลัมน์เหล่านั้นว่างจริงทุกแถว ถ้ามีข้อมูลแม้แถวเดียวจะหยุด
  - สำรองไฟล์ให้อัตโนมัติก่อนแก้
"""

import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

DB = ROOT / "data" / "ledger.db"
DROP = ["category", "fb_group", "customer_ref", "list_baht"]


def main():
    run = "--run" in sys.argv
    if not DB.exists():
        sys.exit(f"ไม่เจอไฟล์ {DB}")

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    have = [r["name"] for r in conn.execute("PRAGMA table_info(sale)")]
    todo = [c for c in DROP if c in have]

    print(f"ฐานข้อมูล : {DB}")
    print(f"คอลัมน์ตอนนี้: {', '.join(have)}\n")

    if not todo:
        print("ถอดไปแล้วเรียบร้อย ไม่มีอะไรต้องทำ")
        return

    total = conn.execute("SELECT COUNT(*) FROM sale").fetchone()[0]
    blocked = []
    for col in todo:
        filled = conn.execute(
            f"SELECT COUNT({col}) FROM sale").fetchone()[0]
        mark = "ว่างทุกแถว" if filled == 0 else f"⚠️ มีข้อมูล {filled} แถว"
        print(f"  {col:14} {mark}")
        if filled:
            blocked.append((col, filled))

    if blocked:
        print("\nหยุดไว้ก่อน — คอลัมน์พวกนี้มีข้อมูลอยู่จริง ลบแล้วข้อมูลหายถาวร:")
        for col, cnt in blocked:
            print(f"  {col} มี {cnt} แถว")
        sys.exit(1)

    print(f"\nทั้งหมด {total} แถว · ทุกคอลัมน์ที่จะถอดว่างเปล่าหมด")

    if not run:
        print("\n--- ตรวจอย่างเดียว ยังไม่ได้แก้อะไร ---")
        print("ทำจริงสั่ง: python tools/drop_unused_columns.py --run")
        return

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = ROOT / "backup" / f"ledger-before-drop-{stamp}.db"
    backup.parent.mkdir(exist_ok=True)
    conn.close()
    shutil.copy2(DB, backup)
    print(f"\nสำรองไว้ที่ {backup.name}")

    conn = sqlite3.connect(DB)
    try:
        # ต้องทิ้ง VIEW ก่อน เพราะ v_sale อ้างถึงคอลัมน์ที่กำลังจะลบ
        # SQLite ไม่ยอมให้ลบคอลัมน์ที่มี VIEW อ้างอยู่
        # VIEW จะถูกสร้างใหม่เองตอนบอทต่อฐานข้อมูลครั้งถัดไป (จาก schema.sql)
        conn.execute("DROP VIEW IF EXISTS v_day")
        conn.execute("DROP VIEW IF EXISTS v_sale")
        for col in todo:
            conn.execute(f"ALTER TABLE sale DROP COLUMN {col}")
            print(f"  ถอด {col} แล้ว")
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        shutil.copy2(backup, DB)
        sys.exit(f"ล้มเหลว คืนไฟล์เดิมกลับมาแล้ว\n  {e}")

    after = [r[1] for r in conn.execute("PRAGMA table_info(sale)")]
    rows = conn.execute("SELECT COUNT(*) FROM sale").fetchone()[0]
    revenue = conn.execute(
        "SELECT COALESCE(SUM(price_baht),0) FROM sale").fetchone()[0]
    conn.close()

    print(f"\nคอลัมน์ที่เหลือ: {', '.join(after)}")
    print(f"จำนวนแถว {rows} (ก่อนแก้ {total})")
    print(f"ยอดขายรวม {revenue:,.2f}฿")
    if rows != total:
        sys.exit("⚠️ จำนวนแถวเปลี่ยน — ผิดปกติ เอาไฟล์สำรองคืน")
    print("\nเรียบร้อย · VIEW จะถูกสร้างใหม่ตอนบอทต่อฐานข้อมูลครั้งถัดไป")


if __name__ == "__main__":
    main()
