"""
ชุดทดสอบแบบ "พยายามทำให้พัง" — รันด้วย  python tests/adversarial.py

ต่างจาก smoke.py ยังไง
----------------------
smoke.py ตรวจว่าของที่ควรทำงาน ยังทำงานอยู่ (เทสต์การถดถอย)
ไฟล์นี้ตรวจว่าของที่ *ไม่ควรเกิด* มันเกิดได้มั้ย — ป้อนค่าประหลาด
ค่าติดลบ ค่าศูนย์ ค่ามหาศาล ตัวอักษรปนตัวเลข วันที่ไม่มีอยู่จริง
สั่งซ้ำ สั่งย้อนลำดับ ฯลฯ

ทุกเคสห่อด้วย try/except เพราะ "พังแล้วโปรแกรมตาย" เป็นผลลัพธ์ที่ต้องรายงาน
ไม่ใช่เหตุให้หยุดเทสต์

ผลลัพธ์แบ่ง 3 แบบ
  ok    = ทำงานถูกต้อง
  พัง   = ผิดจากที่ควรเป็น ต้องแก้
  ข้อสังเกต = ไม่ถึงกับผิด แต่ควรรู้ไว้
"""
import io
import os
import sys
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "test-token")

# ⚠️ ห้ามลบ — บังคับใช้ SQLite เสมอ แม้ตั้ง DATABASE_URL ไว้
# ไฟล์นี้สุ่มยิงคำสั่ง 300 ครั้งและล้างตารางซ้ำๆ
# ถ้าวิ่งไปโดน Supabase ข้อมูลจริงหายทั้งหมด
os.environ["LEDGER_FORCE_SQLITE"] = "1"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import db                                                    # noqa: E402
db.DB_PATH = ROOT / "data" / "adversarial.db"
if db.DB_PATH.exists():
    db.DB_PATH.unlink()

import store                                                 # noqa: E402
import bot                                                   # noqa: E402
from parser import parse_line, ParseError                    # noqa: E402

out = []
bot.api = lambda method, **p: (out.append(p.get("text", "")), {"ok": True})[1]
conn = db.connect()

passed = []
failed = []
notes = []
n = 0

TABLES = ("sale", "day_log", "purchase", "app_state", "job_log",
          "spend", "token_move", "transfer", "balance_snapshot",
          "pending_order", "expense")


def reset():
    for t in TABLES:
        conn.execute(f"DELETE FROM {t}")
    conn.commit()


def say(text):
    out.clear()
    try:
        bot.handle_text(conn, "x", text)
    except Exception as e:
        return f"__ระเบิด__ {type(e).__name__}: {e}"
    return "\n".join(out)


def check(label, cond, extra=""):
    global n
    n += 1
    if cond:
        passed.append(label)
        print(f"  ok   {n:>3}. {label}")
    else:
        failed.append(label)
        print(f"  พัง  {n:>3}. {label}  · {extra}")


def note(text):
    notes.append(text)
    print(f"  หมายเหตุ  {text}")


def section(title):
    print(f"\n{'─' * 62}\n{title}\n{'─' * 62}")


# ==============================================================
section("1. ข้อความเข้าที่ผิดรูป")
# ==============================================================
reset()
for label, text in [
    ("ข้อความว่าง", ""),
    ("เว้นวรรคล้วน", "     "),
    ("ขึ้นบรรทัดล้วน", "\n\n\n"),
    ("แท็บล้วน", "\t\t"),
    ("อิโมจิล้วน", "🔥🔥🔥"),
    ("ตัวอักษรล้วน", "สวัสดีครับ"),
    ("เลขตัวเดียว", "500"),
    ("ขีดกลางล้วน", "---"),
    ("สแลชเปล่า", "/"),
    ("คำสั่งไม่มีอยู่", "/ไม่มีคำสั่งนี้"),
]:
    r = say(text)
    check(f"{label} ไม่ทำบอทตาย", "__ระเบิด__" not in r, r[:80])

check("ข้อความว่างต้องตอบอะไรสักอย่าง", len(say("")) > 0)
check("ไม่มีแถวขยะถูกบันทึก",
      conn.execute("SELECT COUNT(*) FROM sale").fetchone()[0] == 0)


# ==============================================================
section("2. ตัวเลขนอกขอบเขต")
# ==============================================================
reset()
say("/ซื้อ 700 63")

for label, text, should_save in [
    ("ราคาติดลบ", "-100 200", False),
    ("ราคาศูนย์", "0 200", False),
    ("Token ติดลบ", "100 -200", False),
    ("Token ศูนย์", "100 0", False),
    ("ทั้งคู่ติดลบ", "-100 -200", False),
    ("ราคาทศนิยม", "99.5 200", True),
    ("Token ทศนิยม", "100 200.7", True),
    # เดิมรับหมด แล้ว Postgres ล้มที่เลขเกิน 2,147,483,647 (SQLite เงียบ) — 30 ก.ย. 2026
    ("ราคามหาศาล", "999999999 200", False),
    ("Token มหาศาล", "100 999999999", False),
    ("ราคาเกินเพดานนิดเดียว", "50001 200", False),
    ("ราคาเท่าเพดานพอดี", "50000 200", True),
    ("ลูกน้ำแทนเว้นวรรค 100,200 500", "100,200 500", False),
    ("ลูกน้ำหลักพันถูกต้อง", "1,200 13,200", True),
]:
    before = conn.execute("SELECT COUNT(*) FROM sale").fetchone()[0]
    r = say(text)
    after = conn.execute("SELECT COUNT(*) FROM sale").fetchone()[0]
    saved = after > before
    check(f"{label} → {'บันทึก' if should_save else 'ปฏิเสธ'}",
          saved == should_save and "__ระเบิด__" not in r, f"saved={saved} {r[:60]}")

reset()
say("/ซื้อ 700 63")
r = say("100 4000000")
check("Token มหาศาลแล้วกำไรติดลบมหาศาล ไม่ทำรายงานพัง",
      "__ระเบิด__" not in say("/today"))
# ทุนสูงกว่าราคาขาย 3 เท่าแทบเป็นไปไม่ได้ในงานจริง ส่วนใหญ่คือพิมพ์ Token เกินหลัก
check("ทุนสูงกว่าราคาขายมากผิดปกติ ต้องเตือน", "ผิดปกติ" in r, r[:100])

reset()
say("/ซื้อ 1100 100")        # เรท 11 พอดี ทำให้คำนวณในหัวตามง่าย
#
# วัดขอบเขตของคำเตือน: เตือนเมื่อทุนเกินราคาขาย 3 เท่า
# ขาย 200฿ ทุนต้องเกิน 600฿ ถึงจะเตือน = Token เกิน 6,600
for label, line, should_warn in [
    ("ขายปกติ กำไร 2 เท่า (200฿ / 1,100 Token)", "200 1100", False),
    ("ขายเท่าทุน (200฿ / 2,200 Token)", "200 2200", False),
    ("ขาดทุนนิดหน่อย (200฿ / 3,000 Token)", "200 3000", False),
    ("ขาดทุนหนัก 2 เท่า (200฿ / 4,400 Token)", "200 4400", False),
    ("ทุนเกิน 3 เท่า (200฿ / 7,000 Token)", "200 7000", True),
    ("พิมพ์เกินหลัก 10 เท่า (200฿ / 11,000 Token)", "200 11000", True),
]:
    r = say(line)
    check(f"{label} → {'เตือน' if should_warn else 'ไม่เตือน'}",
          ("ผิดปกติ" in r) == should_warn, r[:90])

note("คำเตือนจับได้เฉพาะตอนทุนเกินราคาขาย 3 เท่า "
     "ถ้าพิมพ์ Token เกินหลักแต่ยังมีกำไรอยู่ (เช่น 199฿ / 1,990 Token ที่เรท 11 "
     "= ทุน 179฿) จะจับไม่ได้ เพราะแยกไม่ออกจากรายการจริง")


# ==============================================================
section("3. เรท Token")
# ==============================================================
reset()
for label, text, ok_expected in [
    ("/ซื้อ เรท 0", "/ซื้อ 0 100", False),
    ("/ซื้อ จ่าย 0", "/ซื้อ 1000 0", False),
    ("/ซื้อ ติดลบ", "/ซื้อ -1000 100", False),
    ("/ซื้อ เรทต่ำเกิน (4)", "/ซื้อ 400 100", False),
    ("/ซื้อ เรทสูงเกิน (100)", "/ซื้อ 10000 100", False),
    ("/ซื้อ เรทปกติ 11", "/ซื้อ 1100 100", True),
    ("/ซื้อ เรทขอบล่าง 5", "/ซื้อ 500 100", True),
    ("/ซื้อ เรทขอบบน 80", "/ซื้อ 8000 100", True),
]:
    before = conn.execute("SELECT COUNT(*) FROM purchase").fetchone()[0]
    r = say(text)
    after = conn.execute("SELECT COUNT(*) FROM purchase").fetchone()[0]
    check(f"{label}", (after > before) == ok_expected, f"{r[:70]}")

reset()
say("/ซื้อ 1100 100")
rate_ok = db.current_rate(conn, 11.0)
say("/เหมา 2800 100")
check("ล็อตเหมาต้องไม่ไปเปลี่ยนเรทที่ใช้ขาย",
      abs(db.current_rate(conn, 11.0) - rate_ok) < 0.001,
      f"{rate_ok} -> {db.current_rate(conn, 11.0)}")

# 29 ก.ย. 2026 — ของเหมาเรท ~100 เกิดจริง แต่บอทเดิมไม่ยอมให้จด
for label, text, ok_expected in [
    ("/เหมา เรท ~100 เกิดจริง ต้องจดได้", "/เหมา 6048 60", True),
    ("/เหมา เลขศูนย์เกิน (เรท ~1,000) ต้องตีกลับ", "/เหมา 60480 60", False),
    ("/เหมา สลับเลข ต้องตีกลับ", "/เหมา 60 6048", False),
    ("/ซื้อ ยังคงเพดาน 80 (พ่อค้าไม่ให้เรท 100)", "/ซื้อ 6000 60", False),
]:
    before = conn.execute("SELECT COUNT(*) FROM purchase").fetchone()[0]
    r = say(text)
    after = conn.execute("SELECT COUNT(*) FROM purchase").fetchone()[0]
    check(label, (after > before) == ok_expected, r[:70])
check("/เหมา เรทเกิน 80 ต้องเตือนเรื่อง RAP ปั่น", "ปั่น" in say("/เหมา 6048 60"))
check("/เหมา เรทปกติ ไม่ต้องเตือนเรื่องปั่น", "ปั่น" not in say("/เหมา 2800 100"))

# ลูกน้ำคั่นหลักพัน — 29 ก.ย. 2026 "/ซื้อ 8,340 758" ถูกตีกลับ
reset()
say("/ซื้อ 8,340 758")
row = conn.execute("SELECT tokens, baht FROM purchase ORDER BY id DESC LIMIT 1").fetchone()
check("/ซื้อ 8,340 758 อ่านเป็น 8340 Token",
      row is not None and row["tokens"] == 8340 and abs(row["baht"] - 758) < 0.01,
      str(dict(row)) if row else "ไม่บันทึก")
say("1,200 13,200")
row = conn.execute("SELECT price_baht, tokens_spent FROM sale ORDER BY id DESC LIMIT 1").fetchone()
check("บรรทัดขาย 1,200 13,200 อ่านถูก",
      row is not None and row["price_baht"] == 1200 and row["tokens_spent"] == 13200,
      str(dict(row)) if row else "ไม่บันทึก")
# /แก้ ต้องไม่เปลี่ยนเรท / หมายเหตุ / วันที่ ของออเดอร์เก่าเงียบๆ
reset()
say("/ซื้อ 1100 100")                       # เรท 11
say("มว 750 6497 #ของน้อง NX")
old = conn.execute("SELECT id, sold_on FROM sale ORDER BY id DESC LIMIT 1").fetchone()
say("/ซื้อ 1000 100")                       # เรทเปลี่ยนเป็น 10 ก่อนมาแก้
say(f"/แก้ {old['id']} 750 12801")
row = conn.execute("SELECT * FROM sale WHERE id = ?", (old["id"],)).fetchone()
# กติกา LIFO (16 พ.ย. 2026): ใช้ชุดที่มีตอนขายก่อน (1,100 @11)
# ที่ขาดเอาจากชุดถัดไป (1,000 @10) ที่เหลือคิดที่เรทซื้อล่าสุด (10)
_lifo = 12801 / (1100 / 11 + 1000 / 10 + 10701 / 10)
check("/แก้ คิดต้นทุนใหม่ตามชุด Token (LIFO)",
      abs(row["token_rate"] - _lifo) < 0.001, f"{row['token_rate']} ควรเป็น {_lifo:.3f}")
check("/แก้ ไม่ใส่ # ต้องเก็บหมายเหตุเดิมไว้", row["note"] == "ของน้อง NX", str(row["note"]))
check("/แก้ ไม่ย้ายวันที่ของออเดอร์เก่า", row["sold_on"] == old["sold_on"], str(row["sold_on"]))
check("/แก้ ตัวเลขใหม่ถูกบันทึก", row["tokens_spent"] == 12801, str(row["tokens_spent"]))
say(f"/แก้ {old['id']} 750 12801 12.5 #หมายเหตุใหม่")
row = conn.execute("SELECT * FROM sale WHERE id = ?", (old["id"],)).fetchone()
check("/แก้ ใส่เรทมาเอง ไม่ถูกใช้ คิดตามชุด Token เหมือนเดิม", abs(row["token_rate"] - _lifo) < 0.001,
      str(row["token_rate"]))
check("/แก้ ใส่ # มา ต้องใช้หมายเหตุใหม่", row["note"] == "หมายเหตุใหม่", str(row["note"]))

# /นับ = /เช็ค + /บูธ ในคำสั่งเดียว (30 ก.ย. 2026)
reset()
say("/ซื้อ 1100 100")
r = say("/นับ 3780 1660 639 620")
check("/นับ ปรับยอด Token ในไอดี", db.token_balance(conn)["expected"] == 3780,
      str(db.token_balance(conn)["expected"]))
check("/นับ จดบูธเป็นผลรวมราคา", int(db.get_state(conn, "booth_tokens")) == 2919,
      str(db.get_state(conn, "booth_tokens")))
check("/นับ แล้วไม่เตือนว่าเลขบูธค้าง (นับพร้อมกันแล้ว)", "เลขบูธ" not in r, r[-200:])
check("/นับ แล้ว /ทุน ไม่เตือนบูธค้าง", "เลขบูธ" not in say("/ทุน"))
say("/นับ 5000 0")
check("/นับ บูธว่าง = บูธเป็น 0", int(db.get_state(conn, "booth_tokens")) == 0)
before = db.token_balance(conn)["expected"]
r = say("/นับ 9999")
check("/นับ เลขเดียว ไม่บันทึกอะไร (ไม่รู้ว่าบูธว่างหรือลืมใส่)",
      db.token_balance(conn)["expected"] == before and "บูธ" in r, r[:80])
before = (db.token_balance(conn)["expected"], db.get_state(conn, "booth_tokens"))
r = say("/นับ 5000 300 5OO")
check("/นับ มีคำแปล (5OO) ต้องไม่บันทึกอะไรเลย",
      (db.token_balance(conn)["expected"], db.get_state(conn, "booth_tokens")) == before
      and "ยังไม่ได้บันทึก" in r, r[:80])
r = say("/นับ 5OO 300 200")
check("/นับ ตัวแรกพิมพ์ผิด ต้องไม่เลื่อน 300 ไปเป็นยอดไอดี",
      db.token_balance(conn)["expected"] == before[0], str(db.token_balance(conn)["expected"]))
check("/เช็ค กับ /บูธ แบบเดิมยังใช้ได้",
      "ตรวจยอด Token" in say("/เช็ค 5000") and "บันทึกของในบูธ" in say("/บูธ 100 200"))
check("/help บอกวิธีใช้ /นับ", "/นับ" in say("/help"))

# ข้อความปิดเดือน — 1 ต.ค. 2026 เกือบบอกว่ากรุงไทยควรมี ~16,500 ทั้งที่จริง ~9,000
# เพราะไม่หักเงินที่ /โอน ออกไประหว่างเดือน
reset()
say("/ซื้อ 1100 100")
say("500 2200")
say("/โอน 300 dime")
from datetime import timedelta                                    # noqa: E402
_real_now = db.now_th
_next = (_real_now().replace(day=1) + timedelta(days=32)).replace(day=1, hour=9)
db.now_th = lambda: _next
try:
    mc = bot.text_month_close(conn)
finally:
    db.now_th = _real_now
check("ปิดเดือนไม่ทายยอดกรุงไทยเอง (ไม่รู้ยอดต้นเดือนจริง)", "ควรอยู่ราว" not in mc, mc[:120])
check("ปิดเดือนต้องบอกเงินที่ย้ายออกไประหว่างเดือน", "ย้ายออกไปแล้ว 300" in mc, mc[:200])
check("ปิดเดือนให้สูตรแบ่งจากยอดจริง", "ยอดจริง −" in mc)

from parser import strip_thousands
for raw, want in [("8,340", "8340"), ("1,234,567", "1234567"), ("8,340.5", "8340.5"),
                  ("1,5", "1,5"), ("12,34", "12,34"), ("1234,567", "1234,567"),
                  ("2,297/130", "2297/130"), ("55 192", "55 192")]:
    check(f"strip_thousands({raw!r}) = {want!r}", strip_thousands(raw) == want,
          strip_thousands(raw))


# ==============================================================
section("4. วันที่")
# ==============================================================
reset()
say("/ซื้อ 700 63")
for label, text, should_save in [
    ("d0", "d0 100 200", False),
    ("d32", "d32 100 200", False),
    ("d99", "d99 100 200", False),
    ("d1 ปกติ", "d1 100 200", True),
    ("เมื่อวาน", "มว 100 200", True),
]:
    before = conn.execute("SELECT COUNT(*) FROM sale").fetchone()[0]
    r = say(text)
    after = conn.execute("SELECT COUNT(*) FROM sale").fetchone()[0]
    check(f"วันที่ {label}", (after > before) == should_save, r[:70])

rows = conn.execute("SELECT sold_on FROM sale").fetchall()
check("ไม่มีวันที่ในอนาคต",
      all(r["sold_on"] <= db.today_th() for r in rows),
      str([r["sold_on"] for r in rows]))


# ==============================================================
section("5. เงินย้ายกระเป๋า /โอน")
# ==============================================================
reset()
say("/ซื้อ 700 63")
say("170 371")
base = db.cash_summary(conn, "2000-01-01", "2100-01-01")["profit_cash"]

for label, text in [
    ("โอนปกติ", "/โอน 5000 dime"),
    ("โอนติดลบ (เงินเข้า)", "/โอน -2000 เงินตัวเอง"),
    ("โอนทศนิยม", "/โอน 330.01 kbank"),
    ("โอนมหาศาล", "/โอน 99999999 dime"),
    ("โอนไม่ระบุปลายทาง", "/โอน 100"),
    ("ปลายทางมาก่อนเลข", "/โอน dime 250"),
]:
    r = say(text)
    check(f"{label} ไม่พัง", "__ระเบิด__" not in r, r[:70])

after = db.cash_summary(conn, "2000-01-01", "2100-01-01")["profit_cash"]
check("ย้ายเงินทุกแบบแล้วกำไรต้องไม่ขยับเลย",
      abs(base - after) < 0.001, f"{base} -> {after}")

r = say("/โอน 0")
check("โอน 0 บาทถูกปฏิเสธ", "0 บาท" in r or "ไม่ต้อง" in r, r[:70])
check("/โอน เปล่า แสดงวิธีใช้", "โอน" in say("/โอน"))


# ==============================================================
section("6. รายจ่ายส่วนตัว /จ่าย")
# ==============================================================
reset()
say("/ซื้อ 700 63")
say("170 371")
base = db.cash_summary(conn, "2000-01-01", "2100-01-01")["profit_cash"]
for text in ("/จ่าย 50 ข้าว", "/จ่าย 0 ฟรี", "/จ่าย -20 คืนเงิน",
             "/จ่าย 99999 ของแพง", "/จ่าย ข้าว"):
    check(f"{text} ไม่พัง", "__ระเบิด__" not in say(text))
after = db.cash_summary(conn, "2000-01-01", "2100-01-01")["profit_cash"]
check("รายจ่ายส่วนตัวไม่แตะกำไรธุรกิจ", abs(base - after) < 0.001)

spent = db.spend_total(conn, "2000-01-01", "2100-01-01")
if spent < 0:
    note(f"รายจ่ายส่วนตัวรวมติดลบได้ ({spent}) — /จ่าย รับค่าติดลบ")


# ==============================================================
section("7. /บูธ")
# ==============================================================
reset()
for label, text, expect in [
    ("เลขเดียว", "/บูธ 3051", 3051),
    ("หลายเลขบวกให้", "/บูธ 599 529 488", 1616),
    ("ศูนย์", "/บูธ 0", 0),
    ("มีตัวอักษรปน", "/บูธ 100 abc 200", 300),
    ("ติดลบ", "/บูธ -500", None),
]:
    r = say(text)
    got = db.get_state(conn, "booth_tokens")
    if expect is None:
        check(f"/บูธ {label}", "__ระเบิด__" not in r, r[:60])
    else:
        check(f"/บูธ {label} = {expect}", got is not None and int(got) == expect,
              f"ได้ {got}")

# พิมพ์ 5OO (โอใหญ่) แทน 500 เกิดได้จริงตอนพิมพ์เร็ว ถ้าเงียบไปของตุนจะหาย 500
r = say("/บูธ 100 5OO 200")
check("/บูธ ต้องบอกว่ามองข้ามคำไหนไป", "ข้ามคำที่ไม่ใช่ตัวเลข" in r, r[:120])
check("/บูธ ยังบวกเฉพาะตัวเลขที่อ่านออกได้ถูก",
      int(db.get_state(conn, "booth_tokens")) == 300)
r = say("/บูธ 599 529 488")
check("/บูธ ที่ถูกต้องทั้งหมด ต้องไม่ขึ้นคำเตือน",
      "ข้ามคำที่ไม่ใช่ตัวเลข" not in r, r[:80])


# ==============================================================
section("8. /ยกยอด")
# ==============================================================
reset()
for label, text, ok_expected in [
    ("หลายบัญชี", "/ยกยอด 1095 10000 3600 2656", True),
    ("บัญชีเดียว", "/ยกยอด 5000", True),
    ("ศูนย์", "/ยกยอด 0", False),
    ("ติดลบ", "/ยกยอด -100", False),
    ("ทศนิยม", "/ยกยอด 100.55", True),
    ("ติดลบรวมแล้วบวก", "/ยกยอด -100 500", True),
]:
    before = conn.execute("SELECT COUNT(*) FROM balance_snapshot").fetchone()[0]
    r = say(text)
    after = conn.execute("SELECT COUNT(*) FROM balance_snapshot").fetchone()[0]
    check(f"/ยกยอด {label}", (after > before) == ok_expected, r[:60])

check("/ยกยอด เปล่า แสดงวิธีใช้", "ยกยอด" in say("/ยกยอด"))


# ==============================================================
section("9. /เช็ค Token")
# ==============================================================
reset()
say("/ซื้อ 1100 100")
for label, text in [("ปกติ", "/เช็ค 900"), ("ศูนย์", "/เช็ค 0"),
                    ("ติดลบ", "/เช็ค -500"), ("มหาศาล", "/เช็ค 99999999"),
                    ("ไม่ใส่เลข", "/เช็ค")]:
    check(f"/เช็ค {label} ไม่พัง", "__ระเบิด__" not in say(text))

bal = db.token_balance(conn)["expected"]
if bal < 0:
    note(f"ยอด Token ติดลบได้ ({bal:,}) — ควรเตือนเพราะเป็นไปไม่ได้ในเกม")


# ==============================================================
section("10. หลายบรรทัดในข้อความเดียว")
# ==============================================================
reset()
r = say("/ซื้อ 700 63\n55 192\n60 200\n/โอน 100 dime")
check("คำสั่งปนบรรทัดขาย ทำครบทุกบรรทัด",
      conn.execute("SELECT COUNT(*) FROM sale").fetchone()[0] == 2
      and db.transfer_total(conn, "2000-01-01", "2100-01-01") == 100,
      r[:90])

reset()
say("/ซื้อ 700 63")
r = say("\n".join(f"{50 + i} {100 + i}" for i in range(80)))
check("80 บรรทัดรวดเดียว บันทึกครบ",
      conn.execute("SELECT COUNT(*) FROM sale").fetchone()[0] == 80)
check("ทุกก้อนข้อความไม่เกินลิมิต Telegram",
      all(len(c) <= 4096 for c in out), f"ยาวสุด {max(len(c) for c in out)}")

reset()
say("/ซื้อ 700 63")
r = say("55 192\nบรรทัดนี้อ่านไม่ออก\n60 200")
check("บรรทัดเสียไม่ทำให้บรรทัดดีหาย",
      conn.execute("SELECT COUNT(*) FROM sale").fetchone()[0] == 2, r[:90])


# ==============================================================
section("11. จดซ้ำ")
# ==============================================================
reset()
say("/ซื้อ 700 63")
say("100 300")
r = say("100 300")
check("จดเหมือนเดิมซ้ำ ต้องเตือน", "ซ้ำ" in r or "เหมือน" in r, r[:90])
check("แต่ยังบันทึกให้ (ขายของเหมือนกัน 2 ชิ้นเกิดได้)",
      conn.execute("SELECT COUNT(*) FROM sale").fetchone()[0] == 2)


# ==============================================================
section("12. การคำนวณกำไร")
# ==============================================================
reset()
say("/ซื้อ 1100 100")          # เรท 11
say("100 1100")                # ทุน 100฿ ขาย 100฿ = กำไร 0
row = conn.execute("SELECT * FROM v_sale ORDER BY id DESC LIMIT 1").fetchone()
check("ขายเท่าทุน กำไรต้องเป็น 0", abs(row["profit_baht"]) < 0.01,
      str(row["profit_baht"]))
check("ขายเท่าทุน markup ต้องเป็น 1", abs(row["markup_x"] - 1.0) < 0.01)

say("50 1100")                 # ขาดทุน
row = conn.execute("SELECT * FROM v_sale ORDER BY id DESC LIMIT 1").fetchone()
check("ขายต่ำกว่าทุน กำไรติดลบ", row["profit_baht"] < 0, str(row["profit_baht"]))

cash = db.cash_summary(conn, "2000-01-01", "2100-01-01")
check("กำไรเงินสด = รับ - จ่าย",
      abs(cash["profit_cash"] - (cash["cash_in"] - cash["cash_out"])) < 0.01)
check("ผลต่างสองชั้น = attributed - cash",
      abs(cash["gap"] - (cash["profit_attributed"] - cash["profit_cash"])) < 0.01)


# ==============================================================
section("13. มูลค่าของตุน / หารศูนย์")
# ==============================================================
reset()
try:
    old = bot.STOCK_RATE
    bot.STOCK_RATE = 0
    r = bot.stock_value(conn)
    check("STOCK_RATE = 0 ต้องไม่ทำให้พัง", True)
    bot.STOCK_RATE = old
except ZeroDivisionError:
    bot.STOCK_RATE = old
    check("STOCK_RATE = 0 ต้องไม่ทำให้พัง", False, "ZeroDivisionError")
except Exception as e:
    bot.STOCK_RATE = old
    check("STOCK_RATE = 0 ต้องไม่ทำให้พัง", False, f"{type(e).__name__}")

try:
    old = bot.STOCK_RATE
    bot.STOCK_RATE = -5
    v = bot.stock_value(conn)["total_baht"]
    bot.STOCK_RATE = old
    if v < 0:
        note(f"STOCK_RATE ติดลบทำให้มูลค่าของตุนติดลบ ({v:,.0f}฿) โดยไม่มีอะไรเตือน")
    check("STOCK_RATE ติดลบไม่ทำให้พัง", True)
except Exception as e:
    bot.STOCK_RATE = old
    check("STOCK_RATE ติดลบไม่ทำให้พัง", False, f"{type(e).__name__}")

reset()
check("ไม่มีข้อมูลเลย /ทุน ไม่พัง", "__ระเบิด__" not in say("/ทุน"))
check("ไม่มีข้อมูลเลย /กำไรจริง ไม่พัง", "__ระเบิด__" not in say("/กำไรจริง"))
check("ไม่มีข้อมูลเลย /month ไม่พัง", "__ระเบิด__" not in say("/month"))
check("ไม่มีข้อมูลเลย /band ไม่พัง", "__ระเบิด__" not in say("/band"))
check("ไม่มีข้อมูลเลย /กรุงไทย ไม่พัง", "__ระเบิด__" not in say("/กรุงไทย 100"))
check("ไม่มีข้อมูลเลย /ส่วนตัว ไม่พัง", "__ระเบิด__" not in say("/ส่วนตัว"))
check("ไม่มีข้อมูลเลย /เหลือ ไม่พัง", "__ระเบิด__" not in say("/เหลือ 500"))


# ==============================================================
section("14. เตือนเลขบูธค้าง")
# ==============================================================
reset()
say("/ซื้อ 1100 100")
say("/บูธ 5000")
check("จดบูธใหม่ ไม่เตือน", "เลขบูธ" not in say("/ทุน"))
say("/เช็ค 400")
check("นับ Token หลังจดบูธ ต้องเตือน", "เลขบูธ" in say("/ทุน"))
say("/บูธ 0")
check("อัปเดตบูธแล้วหยุดเตือน", "เลขบูธ" not in say("/ทุน"))
say("/เช็ค 300")
check("บูธ = 0 แล้วนับใหม่ ไม่ต้องเตือน (ไม่มีอะไรให้นับซ้ำ)",
      "เลขบูธ" not in say("/ทุน"))


# ==============================================================
section("15. ความเข้ากันได้กับ Postgres")
# ==============================================================
cases = [
    ("? เดี่ยว", "SELECT * FROM sale WHERE id = ?", "SELECT * FROM sale WHERE id = %s"),
    ("? หลายตัว", "WHERE a = ? AND b = ?", "WHERE a = %s AND b = %s"),
    (":ชื่อ", "WHERE id = :id", "WHERE id = %(id)s"),
    ("ผสม", "WHERE a = ? AND b = :b", "WHERE a = %s AND b = %(b)s"),
    ("% ใน LIKE ต้องถูกหนี", "WHERE n LIKE '%x%' AND id = ?",
     "WHERE n LIKE '%%x%%' AND id = %s"),
    (":: ของ Postgres ต้องไม่โดนแปลง", "SELECT x::text WHERE id = ?",
     "SELECT x::text WHERE id = %s"),
    ("เวลา 12:30 ในข้อความต้องไม่โดนแปลง", "WHERE t > '12:30' AND id = ?",
     "WHERE t > '12:30' AND id = %s"),
]
for label, src, want in cases:
    got = store.to_postgres(src)
    check(f"แปลง SQL: {label}", got == want, f"ได้ {got!r}")

# ตรวจเฉพาะโค้ดจริง ไม่รวมคอมเมนต์
# (รอบแรกเขียนเทสต์ตรวจทั้งไฟล์ แล้วมันไปเจอคำเตือนในคอมเมนต์ที่เขียนว่า
#  "ห้ามใช้ lastrowid" เลยฟ้องว่าพังทั้งที่โค้ดถูก — เทสต์ที่ฟ้องผิดแบบนี้
#  อันตรายกว่าไม่มีเทสต์ เพราะทำให้คนเลิกเชื่อผลเทสต์)
db_code = "\n".join(
    line for line in (ROOT / "src" / "db.py").read_text(encoding="utf-8").splitlines()
    if not line.strip().startswith("#") and not line.strip().startswith("-")
)
check("ไม่เหลือ INSERT OR (เฉพาะ SQLite) ในโค้ด",
      "INSERT OR REPLACE INTO" not in db_code
      and "INSERT OR IGNORE INTO" not in db_code)
check("ไม่เหลือ cur.lastrowid ในโค้ด", "cur.lastrowid" not in db_code)
check("ไม่มี strftime/julianday ใน SQL (ของ Python ใช้ได้)",
      "julianday" not in db_code and "strftime('" not in db_code
      and 'strftime("%Y-%m", ' not in db_code)

sql_files = [(ROOT / "schema.sql").read_text(encoding="utf-8"),
             (ROOT / "schema_pg.sql").read_text(encoding="utf-8")]
check("schema_pg ไม่มี AUTOINCREMENT", "AUTOINCREMENT" not in sql_files[1])
check("schema_pg ใช้ IDENTITY", "GENERATED BY DEFAULT AS IDENTITY" in sql_files[1])

# ชนิดข้อมูลที่ตัวแปลงต้องเปลี่ยนกลับให้เหมือน SQLite
from datetime import date as _d, datetime as _dt                 # noqa: E402
from decimal import Decimal as _Dec                              # noqa: E402
check("Decimal ถูกแปลงเป็น float", store._clean(_Dec("12.34")) == 12.34)
check("date ถูกแปลงเป็นข้อความ", store._clean(_d(2026, 9, 27)) == "2026-09-27")
check("datetime ไม่ถูกตัดเหลือแค่วันที่",
      "T" in store._clean(_dt(2026, 9, 27, 13, 5, 0, tzinfo=store.TH)))
check("None ผ่านไปเฉยๆ", store._clean(None) is None)
check("int ไม่ถูกแตะ", store._clean(5) == 5)

row = store.Row(["a", "b"], [10, 20])
check("Row เรียกด้วยชื่อได้", row["a"] == 10)
check("Row เรียกด้วยเลขลำดับได้", row[0] == 10 and row[1] == 20)
check("Row แปลงเป็น dict ได้", dict(row) == {"a": 10, "b": 20})


# ==============================================================
section("16. ฟังก์ชันฐานข้อมูลทุกตัวต้องไม่พังตอนไม่มีข้อมูล")
# ==============================================================
reset()
probes = [
    ("cash_summary", lambda: db.cash_summary(conn, "2026-01-01", "2026-12-31")),
    ("range_summary", lambda: db.range_summary(conn, "2026-01-01", "2026-12-31")),
    ("day_summary", lambda: db.day_summary(conn, "2026-09-27")),
    ("token_balance", lambda: db.token_balance(conn)),
    ("blended_rate", lambda: db.blended_rate(conn, 11.0)),
    ("band_breakdown", lambda: db.band_breakdown(conn, "2026-01-01", "2026-12-31")),
    ("zero_day_breakdown", lambda: db.zero_day_breakdown(conn, "2026-01-01", "2026-12-31")),
    ("days_missing_reason", lambda: db.days_missing_reason(conn, "2026-01-01", "2026-12-31")),
    ("data_health", lambda: db.data_health(conn, "2026-01-01", "2026-12-31")),
    ("spend_total", lambda: db.spend_total(conn, "2026-01-01", "2026-12-31")),
    ("spend_by_category", lambda: db.spend_by_category(conn, "2026-01-01", "2026-12-31")),
    ("transfer_total", lambda: db.transfer_total(conn, "2026-01-01", "2026-12-31")),
    ("transfer_by_destination", lambda: db.transfer_by_destination(conn, "2026-01-01", "2026-12-31")),
    ("last_snapshot", lambda: db.last_snapshot(conn)),
    ("open_pendings", lambda: db.open_pendings(conn)),
    ("pending_total", lambda: db.pending_total(conn)),
    ("pending_by_outcome", lambda: db.pending_by_outcome(conn, "2026-01-01", "2026-12-31")),
    ("snapshot_on_or_before", lambda: db.snapshot_on_or_before(conn, "2026-09-01")),
    ("last_sale", lambda: db.last_sale(conn)),
    ("last_purchase", lambda: db.last_purchase(conn)),
    ("latest_lot", lambda: db.latest_lot(conn)),
    ("recent_sales", lambda: db.recent_sales(conn)),
    ("recent_token_moves", lambda: db.recent_token_moves(conn)),
    ("last_token_check_id", lambda: db.last_token_check_id(conn)),
    ("current_rate", lambda: db.current_rate(conn, 11.0)),
]
for label, fn in probes:
    try:
        fn()
        check(f"{label} ฐานว่าง", True)
    except Exception as e:
        check(f"{label} ฐานว่าง", False, f"{type(e).__name__}: {e}")


# ==============================================================
section("17. ข้อความยาวและอักขระพิเศษ")
# ==============================================================
reset()
say("/ซื้อ 700 63")
for label, text in [
    ("โน้ตยาว 3000 ตัว", "100 200 " + "ก" * 3000),
    ("อักขระ HTML", "100 200 <b>ตัวหนา</b> & <script>"),
    ("อัญประกาศเดี่ยว", "100 200 it's a 'test'"),
    ("SQL injection", "100 200 '; DROP TABLE sale; --"),
    ("อิโมจิในโน้ต", "100 200 ดาบ🔥⚔️"),
    ("ขึ้นบรรทัดในโน้ต", "100 200 ดาบ"),
]:
    r = say(text)
    check(f"{label} ไม่พัง", "__ระเบิด__" not in r, r[:60])

check("ตาราง sale ยังอยู่หลัง SQL injection",
      conn.execute("SELECT COUNT(*) FROM sale").fetchone()[0] > 0)
check("ข้อความตอบกลับไม่เกิน 4096 ทุกก้อน",
      all(len(c) <= 4096 for c in out))

r = say("/รายการ")
check("/รายการ กับโน้ตที่มี HTML ไม่ทำให้ Telegram ตีกลับ",
      "__ระเบิด__" not in r and "<script>" not in r.replace("&lt;", "<"),
      r[:80])


# ==============================================================
section("18. ลำดับการทำงานที่ผิดธรรมชาติ")
# ==============================================================
reset()
check("ขายก่อนซื้อ Token (ไม่มีเรท) ยังบันทึกได้",
      "__ระเบิด__" not in say("100 200"))
check("/ย่อย ทั้งที่ไม่มีล็อต ไม่พัง", "__ระเบิด__" not in say("/ย่อย 500"))
check("/ยกเลิก ทั้งที่ไม่มีอะไรให้ยกเลิก ไม่พัง",
      "__ระเบิด__" not in say("/ยกเลิก"))
check("/แก้ รายการที่ไม่มีอยู่ ไม่พัง", "__ระเบิด__" not in say("/แก้ 99999 100 200"))
check("/close ซ้ำหลายรอบ ไม่พัง",
      all("__ระเบิด__" not in say("/close วันนี้") for _ in range(3)))
check("/ทัก ค่าติดลบ ไม่พัง", "__ระเบิด__" not in say("/ทัก -5"))

reset()
say("/ซื้อ 700 63")
say("100 200")
n_before = conn.execute("SELECT COUNT(*) FROM sale").fetchone()[0]
say("/ยกเลิก")
n_after = conn.execute("SELECT COUNT(*) FROM sale").fetchone()[0]
check("/ยกเลิก ลบรายการล่าสุดจริง", n_after == n_before - 1, f"{n_before}->{n_after}")
say("/ยกเลิก")
say("/ยกเลิก")
check("/ยกเลิก เกินจำนวนที่มี ไม่ทำให้ติดลบ",
      conn.execute("SELECT COUNT(*) FROM sale").fetchone()[0] >= 0)


# ==============================================================
section("19. งานตามเวลา")
# ==============================================================
reset()
say("/ซื้อ 700 63")
say("100 200")
try:
    bot.run_scheduled_jobs(conn)
    c1 = len(out)
    bot.run_scheduled_jobs(conn)
    bot.run_scheduled_jobs(conn)
    check("งานตามเวลารันซ้ำไม่ยิงข้อความซ้ำ", len(out) == c1, f"{c1} -> {len(out)}")
except Exception as e:
    check("งานตามเวลาไม่พัง", False, f"{type(e).__name__}: {e}")


# ==============================================================
section("20. ตัวแยกข้อความระดับล่าง")
# ==============================================================
from datetime import date as D                                  # noqa: E402
today = D(2026, 9, 27)
# เลขไทย ๑๐๐ ใช้ได้จริง เพราะ int() ของ Python อ่านเลขยูนิโค้ดออก
# รอบแรกผมเขียนเทสต์ว่าต้องปฏิเสธ ซึ่งคิดผิด — มันแปลงถูกต้องอยู่แล้ว
th = parse_line("๑๐๐ ๒๐๐", today, 11.0)
check("เลขไทย ๑๐๐ ๒๐๐ แปลงเป็น 100 / 200 ได้ถูกต้อง",
      th["price_baht"] == 100.0 and th["tokens_spent"] == 200,
      f"{th['price_baht']} {th['tokens_spent']}")

bad = ["", "   ", "abc", "100", "- -"]
for text in bad:
    try:
        parse_line(text, today, 11.0)
        check(f"parse_line({text!r}) ควรปฏิเสธ", False, "ไม่ปฏิเสธ")
    except ParseError:
        check(f"parse_line({text!r}) ปฏิเสธถูกต้อง", True)
    except Exception as e:
        check(f"parse_line({text!r})", False, f"{type(e).__name__}: {e}")

good = ["100 200", "100 200 ดาบ", "มว 100 200", "100 200 1100/100"]
for text in good:
    try:
        parse_line(text, today, 11.0)
        check(f"parse_line({text!r}) ผ่าน", True)
    except Exception as e:
        check(f"parse_line({text!r}) ควรผ่าน", False, f"{type(e).__name__}: {e}")


# ==============================================================
section("21. สุ่มยิงคำสั่ง 300 ครั้ง แล้วตรวจกฎที่ห้ามผิด")
# ==============================================================
#
# เทสต์ข้างบนเป็นเคสที่ "คิดออก" ส่วนนี้ยิงมั่วเพื่อหาเคสที่คิดไม่ถึง
# ใช้ seed คงที่ เวลาเจอปัญหาจะรันซ้ำให้เหมือนเดิมได้
import random                                                   # noqa: E402
random.seed(20260927)

reset()
say("/ซื้อ 1100 100")
crashes = []
for i in range(300):
    kind = random.choice(["sale", "buy", "lot", "transfer", "spend", "booth",
                          "check", "snapshot", "report", "junk", "split",
                          "pending", "closepend"])
    if kind == "sale":
        cmd = f"{random.randint(1, 5000)} {random.randint(1, 20000)}"
    elif kind == "buy":
        cmd = f"/ซื้อ {random.randint(1, 90000)} {random.randint(1, 9000)}"
    elif kind == "lot":
        cmd = f"/เหมา {random.randint(1, 90000)} {random.randint(1, 3000)}"
    elif kind == "transfer":
        cmd = f"/โอน {random.randint(-9000, 9000)} {random.choice(['dime', 'kbank', ''])}"
    elif kind == "spend":
        cmd = f"/จ่าย {random.randint(-500, 3000)} {random.choice(['ข้าว', 'เที่ยว', ''])}"
    elif kind == "booth":
        cmd = "/บูธ " + " ".join(str(random.randint(0, 900))
                                 for _ in range(random.randint(1, 6)))
    elif kind == "check":
        cmd = f"/เช็ค {random.randint(-500, 60000)}"
    elif kind == "snapshot":
        cmd = f"/ยกยอด {random.randint(-100, 30000)}"
    elif kind == "pending":
        cmd = f"/ค้าง {random.randint(-100, 3000)} ลูกค้า{random.randint(1, 9)}"
    elif kind == "closepend":
        cmd = (f"/{random.choice(['ส่งแล้ว', 'คืนเงิน', 'ตัดหนี้'])} "
               f"{random.randint(1, 40)}")
    elif kind == "split":
        cmd = f"/ย่อย {random.randint(-100, 9000)}"
    elif kind == "report":
        cmd = random.choice(["/today", "/week", "/month", "/band", "/ทุน",
                             "/กำไรจริง", "/ส่วนตัว", "/รายการ", "/ตรวจ",
                             "/กรุงไทย 1500", "/เหลือ 800", "/โอน", "/บูธ"])
    else:
        cmd = random.choice(["???", "/ไม่มี", "ขายดาบ", "1", "-", "  ", "//"])
    r = say(cmd)
    if "__ระเบิด__" in r:
        crashes.append((i, cmd, r[:120]))

check("สุ่ม 300 คำสั่งแล้วไม่มีคำสั่งไหนทำบอทตาย", not crashes,
      f"{len(crashes)} ครั้ง เช่น {crashes[:2]}")
for i, cmd, err in crashes[:5]:
    print(f"        ครั้งที่ {i}: {cmd}  →  {err}")

# --- กฎที่ต้องจริงเสมอ ไม่ว่าจะยิงอะไรใส่ ---
cash = db.cash_summary(conn, "2000-01-01", "2100-01-01")
sales_sum = conn.execute("SELECT COALESCE(SUM(price_baht),0) FROM sale").fetchone()[0]
buy_sum = conn.execute("SELECT COALESCE(SUM(baht),0) FROM purchase").fetchone()[0]
check("กำไรเงินสด = ยอดขายรวม - ยอดซื้อรวม เสมอ",
      abs(cash["profit_cash"] - (sales_sum - buy_sum)) < 0.01,
      f"{cash['profit_cash']} vs {sales_sum - buy_sum}")

spend_sum = db.spend_total(conn, "2000-01-01", "2100-01-01")
transfer_sum = db.transfer_total(conn, "2000-01-01", "2100-01-01")
check("รายจ่ายส่วนตัวไม่เคยเข้าไปอยู่ในกำไร",
      abs(cash["profit_cash"] - (sales_sum - buy_sum)) < 0.01 or spend_sum == 0)
check("เงินย้ายกระเป๋าไม่เคยเข้าไปอยู่ในกำไร",
      abs(cash["profit_cash"] - (sales_sum - buy_sum)) < 0.01 or transfer_sum == 0)

tb = db.token_balance(conn)
check("ยอด Token = ซื้อ + ย่อยได้ + เข้าออก - ที่ส่งลูกค้า",
      tb["expected"] == tb["bought"] + tb["realised"] + tb["moves"] - tb["used"])

bad_dates = conn.execute(
    "SELECT COUNT(*) FROM sale WHERE length(sold_on) <> 10"
    " OR sold_on NOT LIKE '____-__-__'").fetchone()[0]
check("ทุกวันที่ในตาราง sale อยู่ในรูป YYYY-MM-DD", bad_dates == 0, str(bad_dates))

nulls = conn.execute(
    "SELECT COUNT(*) FROM sale WHERE price_baht IS NULL OR tokens_spent IS NULL"
    " OR token_rate IS NULL OR sold_on IS NULL").fetchone()[0]
check("ไม่มีค่าว่างในคอลัมน์บังคับของ sale", nulls == 0, str(nulls))

bad_rate = conn.execute(
    f"SELECT COUNT(*) FROM sale WHERE token_rate <= 0"
    f" OR token_rate > 200").fetchone()[0]
check("ไม่มีเรทที่เป็นไปไม่ได้หลุดเข้าตาราง sale", bad_rate == 0, str(bad_rate))

for label, fn in probes:
    try:
        fn()
        check(f"{label} หลังสุ่มยิง", True)
    except Exception as e:
        check(f"{label} หลังสุ่มยิง", False, f"{type(e).__name__}: {e}")

for cmd in ("/today", "/week", "/month", "/band", "/ทุน", "/กำไรจริง",
            "/ตรวจ", "/ส่วนตัว", "/รายการ", "/ค้าง", "/โอน", "/ยกยอด"):
    r = say(cmd)
    check(f"{cmd} หลังสุ่มยิง ยังตอบได้", "__ระเบิด__" not in r, r[:70])
    check(f"{cmd} ทุกก้อนไม่เกิน 4096", all(len(c) <= 4096 for c in out))


# ==============================================================
print("\n" + "=" * 62)
print(f"รันไป {n} เคส · ผ่าน {len(passed)} · พัง {len(failed)}")
if failed:
    print("\nที่ต้องแก้:")
    for f in failed:
        print(f"  - {f}")
if notes:
    print("\nข้อสังเกต (ไม่ถึงกับผิด แต่ควรรู้):")
    for x in notes:
        print(f"  - {x}")
print("=" * 62)

try:
    conn.close()
    db.DB_PATH.unlink()
except Exception:
    pass

sys.exit(1 if failed else 0)
