"""
ย้ายข้อมูลจาก SQLite (data/ledger.db) ขึ้น Postgres บน Supabase

วิธีใช้
    PYTHONIOENCODING=utf-8 python tools/migrate_to_supabase.py            # ตรวจก่อน ไม่เขียนอะไร
    PYTHONIOENCODING=utf-8 python tools/migrate_to_supabase.py --run      # ย้ายจริง
    PYTHONIOENCODING=utf-8 python tools/migrate_to_supabase.py --run --replace
                                                    # ล้างของเดิมบน Supabase ก่อนย้าย

หลักคิดของไฟล์นี้
-----------------
ข้อมูล 15 วันนี้มีก้อนเดียวในโลก จดมาทีละวันด้วยมือ หายแล้วหายเลย
สคริปต์นี้จึงออกแบบให้ "พังแล้วไม่เสียหาย" คือ

  1) ค่าเริ่มต้นคือแค่ตรวจ ไม่เขียน  ต้องพิมพ์ --run เองถึงจะเขียน
  2) ตรวจวันที่และเวลาทุกแถวให้ผ่านก่อน แล้วจึงเริ่มเขียน
     ถ้ามีแถวไหนวันที่เพี้ยน จะหยุดทั้งหมดตั้งแต่ยังไม่แตะ Postgres
     (SQLite ยอมให้ '2026-13-45' ผ่าน แต่ Postgres ไม่ยอม
      ถ้าไม่ตรวจก่อน จะไปพังกลางทางตอนย้ายไปแล้วครึ่งนึง)
  3) เขียนทั้งหมดใน transaction เดียว พังตรงไหนก็ย้อนกลับหมด
     ไม่มีสภาพ "ย้ายไปได้ครึ่งเดียว" ซึ่งเป็นสภาพที่แก้ยากที่สุด
  4) ย้ายเสร็จแล้วเทียบตัวเลขสองฝั่งให้ดู ทั้งจำนวนแถวและยอดเงินรวม
     การย้ายที่ไม่ได้ตรวจยอด เท่ากับยังไม่ได้ย้าย
  5) ไม่ลบไฟล์ SQLite ทิ้ง เก็บไว้เป็นของสำรองเสมอ
"""

import os
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import store  # noqa: E402

SQLITE_PATH = ROOT / "data" / "ledger.db"

# ⚠️ เพิ่มตารางใหม่ใน schema.sql แล้วต้องมาเพิ่มที่นี่ด้วยทุกครั้ง
# ไม่งั้นข้อมูลตารางนั้นจะไม่ถูกย้ายไปด้วย และจะรู้ตัวตอนที่สายไปแล้ว
# (28 ก.ย. 2026 เกือบพลาด — ตาราง transfer/balance_snapshot/pending_order/expense
#  สร้างทีหลังแล้วลืมมาเพิ่ม เจอตอนรันตรวจก่อนย้ายพอดี)
# มีเทสต์เทียบรายชื่อนี้กับ schema.sql อยู่ใน tests/smoke.py แล้ว
TABLES = ["sale", "day_log", "purchase", "token_move", "spend",
          "transfer", "balance_snapshot", "pending_order", "expense",
          "app_state", "job_log"]

# คอลัมน์ที่เป็นวันที่ (ต้องเป็น YYYY-MM-DD) และที่เป็นเวลา (ต้องเป็น ISO)
DATE_COLUMNS = {"sale": ["sold_on"], "day_log": ["log_date"],
                "purchase": ["bought_on"], "token_move": ["happened_on"],
                "spend": ["spent_on"], "transfer": ["moved_on"],
                "balance_snapshot": ["taken_on"],
                "pending_order": ["received_on"], "expense": ["spent_on"]}
STAMP_COLUMNS = {"sale": ["logged_at"], "purchase": ["logged_at"],
                 "token_move": ["logged_at"], "spend": ["logged_at"],
                 "transfer": ["logged_at"], "balance_snapshot": ["logged_at"],
                 "pending_order": ["logged_at"], "expense": ["logged_at"],
                 "app_state": ["updated_at"], "job_log": ["ran_at"]}

# ตารางที่มีคอลัมน์ id วิ่งเอง — ย้ายเสร็จต้องบอก Postgres ว่าให้นับต่อจากเลขไหน
# ถ้าลืมขั้นนี้ ออเดอร์แรกที่จดหลังย้ายจะชน id เดิมแล้วฟ้อง duplicate key
IDENTITY_TABLES = ["sale", "purchase", "token_move", "spend", "transfer",
                   "balance_snapshot", "pending_order", "expense"]


def read_sqlite():
    """อ่านทุกตารางออกมาเป็น (ชื่อคอลัมน์, แถวทั้งหมด)"""
    if not SQLITE_PATH.exists():
        sys.exit(f"ไม่เจอไฟล์ {SQLITE_PATH}")
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    out = {}
    for table in TABLES:
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        columns = [d[0] for d in conn.execute(
            f"SELECT * FROM {table} LIMIT 0").description]
        out[table] = (columns, [tuple(r) for r in rows])
    conn.close()
    return out


def check(data) -> list:
    """ตรวจวันที่/เวลาทุกแถวก่อนแตะ Postgres — คืนรายการปัญหาที่เจอ"""
    problems = []
    for table, (columns, rows) in data.items():
        for column in DATE_COLUMNS.get(table, []):
            i = columns.index(column)
            for row in rows:
                try:
                    date.fromisoformat(str(row[i]))
                except (ValueError, TypeError):
                    problems.append(f"{table}.{column} = {row[i]!r} ไม่ใช่วันที่")
        for column in STAMP_COLUMNS.get(table, []):
            i = columns.index(column)
            for row in rows:
                try:
                    datetime.fromisoformat(str(row[i]))
                except (ValueError, TypeError):
                    problems.append(f"{table}.{column} = {row[i]!r} ไม่ใช่เวลา")
    return problems


def totals_sqlite():
    """ยอดรวมฝั่ง SQLite — ใช้เทียบหลังย้าย"""
    conn = sqlite3.connect(SQLITE_PATH)
    t = {}
    for table in TABLES:
        t[f"{table} แถว"] = conn.execute(
            f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    t["รายรับรวม (บาท)"] = round(conn.execute(
        "SELECT COALESCE(SUM(price_baht),0) FROM sale").fetchone()[0], 2)
    t["จ่ายซื้อของรวม (บาท)"] = round(conn.execute(
        "SELECT COALESCE(SUM(baht),0) FROM purchase").fetchone()[0], 2)
    t["Token ที่ส่งให้ลูกค้า"] = conn.execute(
        "SELECT COALESCE(SUM(tokens_spent),0) FROM sale").fetchone()[0]
    t["token_move สุทธิ"] = conn.execute(
        "SELECT COALESCE(SUM(tokens),0) FROM token_move").fetchone()[0]
    conn.close()
    return t


def totals_postgres(conn):
    """ยอดรวมฝั่ง Postgres — ต้องเท่ากับฝั่ง SQLite ทุกบรรทัด"""
    t = {}
    for table in TABLES:
        t[f"{table} แถว"] = conn.execute(
            f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    t["รายรับรวม (บาท)"] = round(conn.execute(
        "SELECT COALESCE(SUM(price_baht),0) FROM sale").fetchone()[0], 2)
    t["จ่ายซื้อของรวม (บาท)"] = round(conn.execute(
        "SELECT COALESCE(SUM(baht),0) FROM purchase").fetchone()[0], 2)
    t["Token ที่ส่งให้ลูกค้า"] = conn.execute(
        "SELECT COALESCE(SUM(tokens_spent),0) FROM sale").fetchone()[0]
    t["token_move สุทธิ"] = conn.execute(
        "SELECT COALESCE(SUM(tokens),0) FROM token_move").fetchone()[0]
    return t


def main():
    run = "--run" in sys.argv
    replace = "--replace" in sys.argv

    if store.backend() != "postgres":
        sys.exit("ยังไม่ได้ตั้ง DATABASE_URL ใน .env — อ่านวิธีในไฟล์ SUPABASE.md")

    print(f"ต้นทาง : SQLite {SQLITE_PATH}")
    print("ปลายทาง: Postgres (Supabase)\n")

    data = read_sqlite()
    for table, (_, rows) in data.items():
        print(f"  {table:12} {len(rows):5} แถว")

    problems = check(data)
    if problems:
        print(f"\nเจอปัญหา {len(problems)} จุด ยังไม่ได้แตะ Supabase เลย:")
        for p in problems[:20]:
            print("  x", p)
        sys.exit(1)
    print("\nตรวจวันที่และเวลาทุกแถว: ผ่าน")

    before = totals_sqlite()

    print("\nต่อ Supabase และสร้างตาราง...")
    conn = store.connect()          # สร้างตารางจาก schema_pg.sql ให้เองตอนต่อ
    print("  สร้างตารางแล้ว")

    existing = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in TABLES}
    filled = {t: n for t, n in existing.items() if n}
    if filled and not replace:
        print("\nบน Supabase มีข้อมูลอยู่แล้ว:", filled)
        sys.exit("หยุดไว้ก่อน กันเขียนทับของที่มีอยู่ "
                 "ถ้าต้องการล้างแล้วย้ายใหม่ ใส่ --replace")

    if not run:
        print("\n--- นี่คือการตรวจเท่านั้น ยังไม่ได้เขียนอะไรลง Supabase ---")
        print("พร้อมแล้วสั่ง: python tools/migrate_to_supabase.py --run")
        return

    print("\nเริ่มย้ายข้อมูล (transaction เดียว พังแล้วย้อนกลับหมด)...")
    # ⚠️ ต้องใช้ conn.transaction() เท่านั้น ห้ามกลับไปใช้ commit()/rollback() เฉยๆ
    #
    # 28 ก.ย. 2026 เปลี่ยนการต่อ Postgres เป็น autocommit (แก้บั๊กบอทตาย)
    # ทำให้ rollback() กลายเป็นคำสั่งที่ไม่ทำอะไรเลย
    # ถ้าไฟล์นี้ยังใช้ rollback() แบบเดิม สัญญาว่า "พังแล้วย้อนกลับหมด"
    # จะหายไปเงียบๆ — ย้ายไปครึ่งเดียวแล้วค้าง ซึ่งเป็นสภาพที่แก้ยากที่สุด
    try:
        with conn.transaction():
            if replace:
                for table in reversed(TABLES):
                    conn.execute(f"DELETE FROM {table}")
                print("  ล้างข้อมูลเดิมแล้ว")

            for table in TABLES:
                columns, rows = data[table]
                if not rows:
                    print(f"  {table:12} ว่าง ข้าม")
                    continue
                names = ", ".join(columns)
                marks = ", ".join(["?"] * len(columns))
                sql = f"INSERT INTO {table} ({names}) VALUES ({marks})"
                for row in rows:
                    conn.execute(sql, row)
                print(f"  {table:12} {len(rows):5} แถว")

            # บอก Postgres ว่าเลข id ต่อไปต้องเริ่มนับจากไหน
            for table in IDENTITY_TABLES:
                conn.execute(
                    f"SELECT setval(pg_get_serial_sequence('{table}', 'id'),"
                    f" (SELECT COALESCE(MAX(id), 1) FROM {table}))")
            print("  ตั้งเลข id ตัวถัดไปแล้ว")
    except Exception as e:
        print(f"\nล้มเหลว ย้อนกลับหมดแล้ว ไม่มีอะไรค้างบน Supabase\n  {e}")
        raise

    print("\n--- เทียบยอดสองฝั่ง ---")
    after = totals_postgres(conn)
    ok = True
    for key, value in before.items():
        got = after.get(key)
        same = abs(float(value) - float(got)) < 0.01
        ok = ok and same
        print(f"  {'ตรง ' if same else 'ไม่ตรง'} {key:24} "
              f"SQLite {value:>12}  Supabase {got:>12}")

    if not ok:
        sys.exit("\nยอดไม่ตรง อย่าเพิ่งใช้ Supabase เป็นตัวจริง "
                 "ไฟล์ SQLite เดิมยังอยู่ครบ")

    print("\nยอดตรงกันทุกบรรทัด ย้ายสำเร็จ")
    print(f"ไฟล์เดิมยังอยู่ที่ {SQLITE_PATH} และในโฟลเดอร์ backup/ — ไม่ได้ลบ")


if __name__ == "__main__":
    main()
