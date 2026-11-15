"""
ตรวจสุขภาพระบบที่รันอยู่จริง — ไม่เขียน ไม่ลบ ไม่แก้อะไรเลย

วิธีใช้
    PYTHONIOENCODING=utf-8 python tools/check_live.py

ทำไมต้องมีแยกจาก tests/
------------------------
เทสต์ใน tests/ รันบน SQLite เสมอ (บังคับไว้ด้วย LEDGER_FORCE_SQLITE)
เพราะเทสต์ล้างตารางทิ้งซ้ำๆ ถ้าหลุดไปรันบนของจริงข้อมูลหายหมด

แต่ Postgres มีพฤติกรรมบางอย่างที่ SQLite ไม่มี และทำให้บอทตายได้
เช่น 28 ก.ย. 2026 — คำสั่ง error ครั้งเดียว ทุกคำสั่งหลังจากนั้นพังหมด
เทสต์บน SQLite จับไม่ได้เลย ต้องไปลองบนของจริง

ไฟล์นี้จึงลองบนของจริง แต่ใช้เฉพาะคำสั่งที่อ่านอย่างเดียว
ไม่รันสคีมา (ไม่แตะ VIEW) ไม่ INSERT/UPDATE/DELETE ตารางไหนเลย
"""

import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import store  # noqa: E402

RENDER_URL = "https://bladeball-ledger.onrender.com/"
problems = []


def ok(msg):
    print(f"  ✓ {msg}")


def bad(msg):
    print(f"  ✗ {msg}")
    problems.append(msg)


print("=== 1. บอทบน Render ===")
try:
    t = time.time()
    with urllib.request.urlopen(RENDER_URL, timeout=60) as r:
        body = r.read().decode("utf-8", "replace").strip()
    secs = time.time() - t
    if body == "ok":
        ok(f"ตอบ ok ใน {secs:.1f} วินาที")
        if secs > 20:
            bad("ตอบช้าเกิน 20 วินาที = เครื่องเพิ่งตื่นจากหลับ ตัวปิงอาจไม่ทำงาน")
    else:
        bad(f"ตอบกลับมาแปลกๆ: {body[:60]!r}")
except Exception as e:
    bad(f"ต่อไม่ได้ ({type(e).__name__}) — บอทดับหรือเครื่องหลับ")

print("\n=== 2. การเชื่อมต่อฐานข้อมูล ===")
if store.backend() != "postgres":
    bad("ไม่ได้ตั้ง DATABASE_URL — ตรวจของจริงไม่ได้")
    sys.exit(1)

# ใช้คลาสเดียวกับที่บอทใช้ แต่ไม่ผ่าน store.connect() ซึ่งจะรันสคีมา
c = store.PgConnection(store.database_url())

try:
    c.execute("SELECT 1/0")
except Exception:
    pass
try:
    c.execute("SELECT 1").fetchone()
    ok("คำสั่ง error ครั้งเดียวไม่ลามไปคำสั่งอื่น (autocommit ทำงาน)")
except Exception as e:
    bad(f"คำสั่ง error แล้วคำสั่งต่อไปพังตาม ({type(e).__name__}) "
        f"— บอทจะตายทุกครั้งที่มี error")

rows = c.execute(
    "SELECT state, now() - state_change AS dur, LEFT(query, 60) AS q"
    " FROM pg_stat_activity"
    " WHERE datname = current_database() AND pid <> pg_backend_pid()"
    "   AND state = 'idle in transaction'"
).fetchall()
if rows:
    for r in rows:
        bad(f"มีการเชื่อมต่อค้าง transaction ไว้ {r['dur']} · {r['q']}")
else:
    ok("ไม่มีการเชื่อมต่อไหนค้าง transaction ไว้")

stuck = c.execute("SELECT COUNT(*) FROM pg_locks WHERE NOT granted").fetchone()[0]
if stuck:
    bad(f"มีคำสั่งรอล็อกอยู่ {stuck} ตัว")
else:
    ok("ไม่มีคำสั่งไหนติดรอล็อก")

print("\n=== 3. ข้อมูล ===")
sale = c.execute(
    "SELECT COUNT(*) n, COALESCE(SUM(price_baht),0) rev, MAX(id) last_id"
    " FROM sale").fetchone()
ok(f"{sale['n']} ออเดอร์ · รายรับรวม {sale['rev']:,.0f}฿ · เลขล่าสุด #{sale['last_id']}")

seq = c.execute(
    "SELECT last_value FROM pg_sequences"
    " WHERE schemaname='public' AND sequencename LIKE 'sale_id%'").fetchone()
if seq and seq[0] is not None and seq[0] < sale["last_id"]:
    bad(f"ตัวนับ id ({seq[0]}) ต่ำกว่าเลขที่มีอยู่ (#{sale['last_id']}) "
        f"— ออเดอร์ถัดไปจะชน id เดิม")
else:
    ok("ตัวนับ id ต่อจากเลขล่าสุดถูกต้อง")

weird = c.execute(
    "SELECT COUNT(*) FROM sale"
    " WHERE price_baht <= 0 OR tokens_spent <= 0"
    "    OR token_rate < 5 OR token_rate > 500").fetchone()[0]
if weird:
    bad(f"มีออเดอร์ตัวเลขผิดปกติ {weird} รายการ (ราคา/Token ≤ 0 หรือเรทนอกช่วง)")
else:
    ok("ไม่มีออเดอร์ตัวเลขผิดปกติ")

bal = c.execute(
    "SELECT"
    " (SELECT COALESCE(SUM(tokens),0) FROM purchase WHERE kind='token')"
    " + (SELECT COALESCE(SUM(tokens_realised),0) FROM purchase WHERE kind='lot')"
    " + (SELECT COALESCE(SUM(tokens),0) FROM token_move)"
    " - (SELECT COALESCE(SUM(tokens_spent),0) FROM sale)").fetchone()[0]
if bal < 0:
    bad(f"ยอด Token ในระบบติดลบ ({bal:,}) ซึ่งเป็นไปไม่ได้ในเกม "
        f"— มี Token เข้ามาที่ยังไม่ได้จด สั่ง /เช็ค")
else:
    ok(f"ยอด Token ในระบบ {bal:,} (ไม่ติดลบ)")

c.close()

print()
if problems:
    print(f"เจอปัญหา {len(problems)} อย่าง:")
    for p in problems:
        print(f"  - {p}")
    sys.exit(1)
print("ผ่านหมด ระบบที่รันจริงปกติดี")
