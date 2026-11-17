"""
เทสต์ "การป้อนข้อความจริง" — รันด้วย  python tests/realinput.py

ต่างจาก smoke.py / adversarial.py ยังไง
--------------------------------------
สองไฟล์นั้นเรียก handle_text() ตรงๆ ซึ่งข้ามชั้นที่รับข้อความจาก Telegram ไป
บั๊กร้ายที่สุดที่เจอ 30 ก.ย. 2026 อยู่ในชั้นนั้นพอดี และเทสต์เดิมมองไม่เห็นเลย
  - error ในคำสั่งไหนก็ตาม = ข้อความหายเงียบ บอทไม่ตอบอะไร
  - กดแก้ข้อความใน Telegram = บันทึกซ้ำเป็นออเดอร์ที่สอง
  - พิมพ์ราคาบูธแล้วกด Enter = บรรทัดใหม่กลายเป็นออเดอร์ปลอม

ไฟล์นี้จึงยิงผ่าน handle_update() หน้าตาเดียวกับที่ Telegram ส่งมาจริง
แล้วตรวจกับ "คำตอบที่ควรเป็น" ที่คิดแยกจากตัวบอทเอง ไม่ใช่แค่ดูว่าไม่พัง

ส่วนสุดท้ายรันบนสำเนาข้อมูลจริง (ไฟล์สำรองใน backup/) ไม่แตะของจริงบน Supabase
"""
import io
import os
import random
import shutil
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "test-token")

# ⚠️ ห้ามลบ — บังคับใช้ SQLite เสมอ แม้ตั้ง DATABASE_URL ไว้
# ไฟล์นี้ล้างตารางซ้ำๆ ถ้าวิ่งไปโดน Supabase ข้อมูลจริงหายทั้งหมด
os.environ["LEDGER_FORCE_SQLITE"] = "1"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import db                                                    # noqa: E402
db.DB_PATH = ROOT / "data" / "realinput.db"
if db.DB_PATH.exists():
    db.DB_PATH.unlink()

import store                                                 # noqa: E402
import bot                                                   # noqa: E402
from parser import (parse_line, ParseError, strip_thousands,  # noqa: E402
                    PRICE_MAX, TOKENS_MAX)

assert store.backend() == "sqlite", "เทสต์ต้องรันบน SQLite เท่านั้น"

out = []
bot.api = lambda method, **p: (out.append(p.get("text", "")), {"ok": True})[1]
bot.CHAT_ID = "777"
conn = db.connect()

TABLES = ("sale", "day_log", "purchase", "app_state", "job_log", "spend",
          "token_move", "transfer", "balance_snapshot", "pending_order", "expense")

passed, failed = [], []
n = 0
BOOM = "__ระเบิด__"


def section(title):
    print(f"\n{'─' * 62}\n{title}\n{'─' * 62}")


def check(label, cond, extra=""):
    global n
    n += 1
    if cond:
        passed.append(label)
    else:
        failed.append(f"{label} · {extra}"[:220])
        print(f"  พัง  {n:>4}. {label}  · {extra[:150]}")


def reset():
    for t in TABLES:
        conn.execute(f"DELETE FROM {t}")
    conn.commit()


def say(text):
    """เรียก handle_text ตรงๆ (เหมือนเทสต์เดิม)"""
    out.clear()
    try:
        bot.handle_text(conn, "777", text)
    except Exception as e:
        return f"{BOOM} {type(e).__name__}: {e}"
    return "\n".join(out)


def tg(text=None, edited=None, chat=777, raise_in=None):
    """ส่ง update หน้าตาเหมือนที่ Telegram ส่งมาจริง ผ่าน handle_update"""
    out.clear()
    key = "edited_message" if edited is not None else "message"
    body = {"chat": {"id": chat}}
    if (edited if edited is not None else text) is not None:
        body["text"] = edited if edited is not None else text
    real = bot.handle_text
    if raise_in:
        def boom(*a, **k):
            raise RuntimeError(raise_in)
        bot.handle_text = boom
    try:
        bot.handle_update(conn, {"update_id": 1, key: body})
    except Exception as e:
        return f"{BOOM} {type(e).__name__}: {e}"
    finally:
        bot.handle_text = real
    return "\n".join(out)


def n_sales():
    return conn.execute("SELECT COUNT(*) FROM sale").fetchone()[0]


def booth():
    v = db.get_state(conn, "booth_tokens")
    return None if v is None else int(v)


def wallet():
    return db.token_balance(conn)["expected"]


# ==============================================================
section("A. ลูกน้ำคั่นหลักพัน (strip_thousands)")
# ==============================================================
for raw, want in [
    ("8,340", "8340"), ("1,234,567", "1234567"), ("8,340.5", "8340.5"),
    ("1,000", "1000"), ("999,999", "999999"), ("12,345", "12345"),
    ("/ซื้อ 8,340 758", "/ซื้อ 8340 758"), ("1,200 13,200", "1200 13200"),
    ("2,297/130", "2297/130"), ("#note 1,000", "#note 1000"),
    ("๘,๓๔๐", "๘๓๔๐"),                     # เลขไทยคั่นหลักพันก็ตัดให้ (Python อ่านเลขไทยได้)
    ("1,5", "1,5"), ("12,34", "12,34"), ("1234,567", "1234,567"),
    ("1,2345", "1,2345"), (",123", ",123"), ("123,", "123,"),
    ("1,,000", "1,,000"), ("1,000,00", "1,000,00"), ("a1,000", "a1000"),
    ("55 192", "55 192"), ("", ""), ("   ", "   "), ("abc", "abc"),
    ("1,000\n2,000", "1000\n2000"), ("x1,000", "x1000"),
    ("1,000,000,000", "1000000000"), ("0,000", "0000"),
    ("-1,000", "-1000"), ("1.000,50", "1.000,50"),
]:
    check(f"strip_thousands({raw!r})", strip_thousands(raw) == want,
          f"ได้ {strip_thousands(raw)!r} ควรเป็น {want!r}")


# ==============================================================
section("B. แปลบรรทัดขาย (ราคา × Token × ตัวเลือก)")
# ==============================================================
TODAY = date(2026, 9, 30)
PRICES_OK = ["55", "1,200", "99.5", "50000", "๕๕", "20"]
PRICES_BAD = ["0", "-5", "50001", "abc", "1,5", "5OO"]
TOKENS_OK = ["192", "13,200", "200.7", "5000000", "1"]
TOKENS_BAD = ["0", "-1", "5000001", "x", "12,34"]

for p in PRICES_OK + PRICES_BAD:
    for t in TOKENS_OK + TOKENS_BAD:
        want = p in PRICES_OK and t in TOKENS_OK
        try:
            parse_line(strip_thousands(f"{p} {t}"), TODAY, 11.0)
            got = True
        except ParseError:
            got = False
        except Exception as e:
            got = f"{BOOM} {e}"
        check(f"'{p} {t}' → {'รับ' if want else 'ปฏิเสธ'}", got is want, str(got))

for extra, want in [
    ("x3", True), ("x1", True), ("x1000", True), ("x0", False), ("x1001", False),
    ("x99999999999", False), ("10.5", True), ("5", True), ("80", True),
    ("4.9", False), ("81", False), ("700/63", True), ("6048/60", True),
    ("60480/60", False), ("60/6048", False), ("0/5", False), ("5/0", False),
    ("ktb", True), ("ทรู", True), ("dime", True), ("เหมา", True),
    ("#Dual Hacker Scythe", True), ("abc", True), ("x3 10.5 ทรู #n", True),
]:
    try:
        parse_line(f"55 192 {extra}", TODAY, 11.0)
        got = True
    except ParseError:
        got = False
    except Exception as e:
        got = f"{BOOM} {e}"
    check(f"'55 192 {extra}' → {'รับ' if want else 'ปฏิเสธ'}", got is want, str(got))

for prefix, want_day in [("มว", date(2026, 9, 29)), ("y", date(2026, 9, 29)),
                         ("d15", date(2026, 9, 15)), ("วันที่1", date(2026, 9, 1)),
                         ("d31", date(2026, 8, 31)), ("d30", date(2026, 9, 30))]:
    try:
        s = parse_line(f"{prefix} 55 192", TODAY, 11.0)
        ok = s["sold_on"] == want_day.isoformat()
        extra = s["sold_on"]
    except Exception as e:
        ok, extra = False, str(e)
    check(f"วันที่ '{prefix}' → {want_day}", ok, extra)

for prefix in ("d0", "d32", "วันที่99"):
    try:
        parse_line(f"{prefix} 55 192", TODAY, 11.0)
        got = True
    except ParseError:
        got = False
    check(f"วันที่ '{prefix}' ต้องปฏิเสธ", got is False)

s = parse_line("55 192 x3 ทรู #ของ", TODAY, 11.0)
check("ตัวเลือกครบ อ่านถูกทุกช่อง",
      (s["price_baht"], s["tokens_spent"], s["item_count"], s["account"]) == (55, 192, 3, "truemoney")
      and "ของ" in s["note"], str(s))
s = parse_line("80 900 2297/130", TODAY, 11.0)
check("เรทเศษส่วน ≥13 ติดป้ายรับเหมาเอง", s["source"] == "hot_lot", s["source"])


# ==============================================================
section("C. ชั้นรับข้อความจาก Telegram (บั๊กที่เจอ 30 ก.ย.)")
# ==============================================================
reset()
say("/ซื้อ 1100 100")

r = tg("55 192", raise_in="จำลองฐานข้อมูลล่ม")
check("error ระหว่างทำข้อความ → บอทไม่ล้ม", BOOM not in r, r[:80])
check("error ระหว่างทำข้อความ → บอกเจ้าของพร้อมข้อความที่พัง",
      "ข้อผิดพลาด" in r and "55 192" in r, r[:120])
check("error → แนะนำให้เช็ก /รายการ ก่อนพิมพ์ซ้ำ", "/รายการ" in r, r[:200])
r = tg("<b>55</b> 192", raise_in="x")
check("error กับข้อความที่มี HTML → ไม่ทำให้การแจ้งเตือนพังซ้ำ", "&lt;b&gt;" in r, r[:120])

before = n_sales()
tg("55 192")
check("ข้อความปกติผ่านชั้น Telegram บันทึกได้", n_sales() == before + 1)
r = tg(edited="55 195")
check("กดแก้ข้อความใน Telegram → ไม่บันทึกซ้ำ", n_sales() == before + 1, str(n_sales() - before))
check("กดแก้ข้อความใน Telegram → บอกว่าไม่มีผล + วิธีแก้", "ไม่มีผล" in r and "/undo" in r, r[:100])
r = tg(edited="/ซื้อ 700 63")
check("กดแก้คำสั่ง /ซื้อ → ไม่ซื้อซ้ำ",
      conn.execute("SELECT COUNT(*) FROM purchase").fetchone()[0] == 1)

before = n_sales()
r = tg("55 192", chat=999)
check("คนอื่นทักบอท → ไม่บันทึก", n_sales() == before)
check("คนอื่นทักบอท → บอทเงียบ (ไม่เผยว่าเป็นบอทบัญชี)", r == "", r[:60])
r = tg(edited="55 192", chat=999)
check("คนอื่นแก้ข้อความ → บอทเงียบ", r == "", r[:60])
r = tg(None)
check("ข้อความไม่มี text (สติกเกอร์/รูป) → ไม่พัง ไม่ตอบ", r == "", r[:60])
out.clear()
bot.handle_update(conn, {"update_id": 9})
check("update ว่างเปล่า → ไม่พัง", True)

# callback ปุ่มเหตุผลวันไม่ได้เงิน
out.clear()
cb = {"update_id": 5, "callback_query": {"id": "c1", "data": "r|2026-09-29|no_inquiry",
                                         "message": {"chat": {"id": 777}}}}
try:
    bot.handle_update(conn, cb)
    ok = True
except Exception:
    ok = False
check("กดปุ่มเหตุผล → บันทึกได้", ok and any("บันทึกแล้ว" in x for x in out), " | ".join(out)[:80])
out.clear()
try:
    bot.handle_update(conn, {"update_id": 6, "callback_query": {
        "id": "c2", "data": "r|2026-09-29|ค่ามั่ว", "message": {"chat": {"id": 777}}}})
    ok = True
except Exception:
    ok = False
check("ปุ่มที่ข้อมูลเสีย → บอทไม่ล้ม", ok)
check("ปุ่มที่ข้อมูลเสีย → บอกเจ้าของว่ามีข้อผิดพลาด",
      any("ข้อผิดพลาด" in x for x in out), " | ".join(out)[:80])

# ราคาบูธขึ้นบรรทัดใหม่
reset()
say("/ซื้อ 1100 100")
before = n_sales()
tg("/นับ 3780 1660 639\n620 600 595\n499 380")
check("/นับ ขึ้นบรรทัดใหม่ → ไม่เกิดออเดอร์ปลอม", n_sales() == before, str(n_sales() - before))
check("/นับ ขึ้นบรรทัดใหม่ → รวมบูธครบทุกบรรทัด", booth() == 4993, str(booth()))
check("/นับ ขึ้นบรรทัดใหม่ → ยอดไอดีถูก", wallet() == 3780, str(wallet()))
tg("/บูธ 100 200\n300\n400 500")
check("/บูธ ขึ้นบรรทัดใหม่ → รวมครบ ไม่เกิดออเดอร์", booth() == 1500 and n_sales() == before)
tg("/นับ 3780 100\n620 600 5OO")
check("/นับ บรรทัดต่อพิมพ์ผิด → ไม่กลายเป็นออเดอร์ 620฿", n_sales() == before)
check("/นับ บรรทัดต่อพิมพ์ผิด → ไม่บันทึกบูธ", booth() == 1500, str(booth()))
before = n_sales()
tg("/นับ 3780 100\n/today\n55 192")
check("บรรทัดขายหลังคำสั่งอื่น → ยังเป็นขาย", n_sales() == before + 1)
before = n_sales()
tg("/ซื้อ 1100 100\n55 192\n60 200")
check("หลัง /ซื้อ บรรทัดขายยังเป็นขาย (ไม่ถูกต่อเข้าคำสั่ง)", n_sales() == before + 2)
before = n_sales()
tg("/บูธ 100\n55 ข้าว")
check("หลัง /บูธ บรรทัดที่มีตัวหนังสือ → ไม่ต่อ (เป็นบรรทัดขายที่พัง)", n_sales() == before)
tg("/นับ\n3780 100 200")
check("/นับ เปล่าแล้วขึ้นบรรทัดใหม่ → ต่อได้", wallet() == 3780 and booth() == 300, f"{wallet()} {booth()}")
tg("/นับ 3780 0\n\n\n100")
check("/นับ มีบรรทัดว่างคั่น → ยังต่อ (บรรทัดว่างถูกข้าม)", booth() == 100, str(booth()))

# ลูกน้ำคั่นรายการ / เลขยักษ์
before_b = booth()
r = tg("/บูธ 639,620,600 100")
check("/บูธ ลูกน้ำคั่นราคา → ไม่บันทึกเลขยักษ์", booth() == before_b and "เว้นวรรค" in r, r[:100])
r = tg("/นับ 3780 639,620,600")
check("/นับ ลูกน้ำคั่นราคา → ไม่บันทึก", "ยังไม่ได้บันทึก" in r and booth() == before_b, r[:80])
r = tg("/บูธ 150000")
check("/บูธ ยอดรวมเลขเดียวใหญ่ได้", booth() == 150000, r[:60])
r = tg("/บูธ 100001 5")
check("/บูธ หลายชิ้น ชิ้นเดียวเกิน 100,000 → ปฏิเสธ", booth() == 150000, r[:60])
r = tg("/บูธ 100000 5")
check("/บูธ ชิ้นละ 100,000 พอดี → รับ", booth() == 100005, r[:60])
w0 = wallet()
r = tg("/เช็ค 99999999999")
check("/เช็ค เลขเกินจริง → ไม่บันทึก", "ยังไม่ได้บันทึก" in r and wallet() == w0, r[:80])
r = tg("/นับ 99999999999 0")
check("/นับ ยอดไอดีเกินจริง → ไม่บันทึก", "ยังไม่ได้บันทึก" in r and wallet() == w0, r[:80])
r = tg("/นับ 10000000 0")
check("/นับ ยอดไอดีเท่าเพดานพอดี → รับ", wallet() == 10_000_000, r[:60])
r = tg("100,200 500")
check("ขาย '100,200 500' (ลูกน้ำแทนเว้นวรรค) → ปฏิเสธ", "ไม่ผ่าน" in r or "ผิดปกติ" in r, r[:80])

# /นับ ตำแหน่งตัวเลข
reset()
say("/ซื้อ 1100 100")
tg("/นับ 1000 0")
r = tg("/นับ 5OO 300 200")
check("/นับ ตัวแรกพิมพ์ผิด → ไม่เลื่อน 300 ไปเป็นยอดไอดี", wallet() == 1000, str(wallet()))
check("/นับ ตัวแรกพิมพ์ผิด → บอกคำที่ผิด", "5OO" in r and "ยังไม่ได้บันทึก" in r, r[:80])
r = tg("/นับ 1000 300 abc")
check("/นับ มีคำแปลกท้ายสุด → ไม่บันทึกบูธ", booth() == 0, str(booth()))
r = tg("/นับ 1000")
check("/นับ เลขเดียว → ถาม ไม่บันทึก", "ต่อท้าย" in r and booth() == 0, r[:80])
r = tg("/นับ")
check("/นับ เปล่า → วิธีใช้", "นับของทั้งหมด" in r, r[:60])
check("/นับ ลูกน้ำหลักพันที่ถูก", "ตรวจยอด Token" in tg("/นับ 3,780 1,660 639") and booth() == 2299)
check("/นับ เลขไทย", "ตรวจยอด Token" in tg("/นับ ๓๗๘๐ ๑๖๖๐") and booth() == 1660)
check("/นับ@ชื่อบอท (กดจากเมนู)", "ตรวจยอด Token" in tg("/นับ@TokenLedgerBot 3780 0"))
check("/นับ ซ้ำตัวเลขเดิม → ผลเหมือนเดิม (ไม่นับทบ)",
      (tg("/นับ 3780 500"), tg("/นับ 3780 500"), wallet(), booth())[2:] == (3780, 500))
r = tg("/นับ 3780 500")
check("/นับ แล้วไม่เตือนเลขบูธค้าง", "เลขบูธ" not in r, r[-120:])
tg("/เช็ค 4000")
check("/เช็ค อย่างเดียวหลัง /นับ → /ทุน เตือนเลขบูธค้าง", "เลขบูธ" in tg("/ทุน"))
check("คำเตือนเลขบูธค้าง แนะนำ /นับ", "/นับ" in tg("/ทุน"))
tg("/นับ 4000 500")
check("/นับ ใหม่ → หายเตือน", "เลขบูธ" not in tg("/ทุน"))

# เรทพ่อค้าเปลี่ยนได้ — บอทต้องเทียบกับเรทที่ซื้อจริงล่าสุด ไม่ใช่เลข 11 ตายตัว
# 15 ต.ค. 2026 พ่อค้าขาย 10.2 แต่บอทบอกว่าดีลเหมา "ดีกว่าเรท 11 อยู่ 1.17 เท่า"
reset()
tg("/ซื้อ 10200 1000")                                 # เรทพ่อค้า 10.2 พอดี
r = tg("/เหมา 25909 2000 3")                           # ดีลจริงคืน 15 ต.ค.
check("/เหมา เทียบกับเรทพ่อค้าล่าสุด 10.20 ไม่ใช่ 11", "10.20" in r and "เรท 11" not in r, r[:300])
check("/เหมา บอกเงินที่ประหยัดได้เป็นบาท", "ประหยัด 515฿" in r, r[:300])
check("/เหมา บอกกี่เท่าของเรทพ่อค้า (1.26 ไม่ใช่ 1.17)", "1.26 เท่า" in r, r[:300])
r = tg("/เหมา 1500 200")                               # เรท ~7.4 แย่กว่าซื้อโทตรงๆ
check("/เหมา แพงกว่าซื้อโทตรงๆ → เตือน", "แพงกว่าซื้อ Token" in r, r[:300])
r = tg("/เรท 25650 2000")
check("/เรท เทียบกับเรทพ่อค้าล่าสุด", "10.20" in r and "เรท 11" not in r, r[:300])
check("/เรท บอกเป็นเงินด้วย", "ประหยัด" in r, r[:300])
check("/ทุน ตีราคา Token ที่เรทพ่อค้าล่าสุด (10,200 โท = 1,000฿)",
      "1,000" in tg("/ทุน"), out[-1][:200])
reset()


# ==============================================================
section("D. ทุกคำสั่ง × หลายรูปแบบการพิมพ์ — ต้องไม่พัง และต้องตอบเสมอ")
# ==============================================================
reset()
say("/ซื้อ 1100 100")
say("55 192")
SKIP_ARGS = {"undo", "ยกเลิก"}      # ลบข้อมูลที่ส่วนอื่นใช้อยู่ ทดสอบแยกด้านล่าง
for w in sorted(bot.COMMAND_WORDS):
    for form in (f"/{w}", f"/{w} 100 50", f"/{w}@TokenLedgerBot", f"  /{w}  "):
        if w in SKIP_ARGS and form != f"/{w}":
            continue
        r = tg(form)
        check(f"{form.strip()!r} ตอบและไม่พัง",
              BOOM not in r and "ข้อผิดพลาด" not in r and r.strip() != "", r[:80])
for w in ("TODAY", "Help", "MONTH"):
    r = tg(f"/{w}")
    check(f"/{w} ตัวใหญ่ใช้ได้", "ไม่รู้จัก" not in r and r.strip(), r[:60])
for bare in ("today", "ทุน", "นับ"):
    r = tg(bare)
    check(f"'{bare}' ไม่มี / → เตือนให้ใส่ /", f"/{bare}" in r, r[:80])
r = tg("/คำสั่งมั่ว")
check("คำสั่งที่ไม่มีจริง → ตอบว่าไม่รู้จัก", r.strip() != "" and BOOM not in r, r[:60])
for junk in ("/", "//", "/ ", "🙂", "   ", "\n\n", "\t55\t192\t"):
    r = tg(junk)
    check(f"ข้อความแปลก {junk!r} → ไม่พัง", BOOM not in r and "ข้อผิดพลาด" not in r, r[:60])


# ==============================================================
section("E. สุ่มยิงข้อความแบบคนพิมพ์จริง 200 ข้อความ เทียบกับคำตอบที่ควรเป็น")
# ==============================================================
rng = random.Random(20260930)
LIST_CMDS = {"นับ", "บูธ", "booth"}


def rnum(lo, hi, comma=0.3):
    v = rng.randint(lo, hi)
    return f"{v:,}" if v >= 1000 and rng.random() < comma else str(v)


def sale_line():
    parts = []
    if rng.random() < 0.15:
        parts.append(rng.choice(["มว", "d29", "d15", "y"]))
    parts += [rnum(10, 3000), rnum(10, 20000)]
    if rng.random() < 0.4:
        parts.append(rng.choice(["x2", "10.5", "700/63", "ทรู", "เหมา", "#ของ", "abc",
                                 "5OO", "x0", "120", "2297/130"]))
    if rng.random() < 0.05:
        parts = [rng.choice(["55", "abc", "0", "-5"])]
    return " ".join(parts)


def cmd_line():
    k = rng.randrange(12)
    if k == 0:
        return f"/ซื้อ {rnum(500, 20000)} {rng.randint(50, 1500)}"
    if k == 1:
        return f"/เหมา {rnum(500, 8000)} {rng.randint(20, 200)}"
    if k == 2:
        return "/นับ " + " ".join(rnum(0, 50000) for _ in range(rng.randint(1, 6)))
    if k == 3:
        return "/บูธ " + " ".join(str(rng.randint(50, 2000)) for _ in range(rng.randint(1, 5)))
    if k == 4:
        return f"/เช็ค {rnum(0, 50000)}"
    if k == 5:
        return rng.choice(["/today", "/month", "/ทุน", "/กำไรจริง", "/รายการ", "/week"])
    if k == 6:
        return f"/โอน {rng.randint(1, 5000)} dime"
    if k == 7:
        return f"/จ่าย {rng.randint(10, 300)} ข้าว"
    if k == 8:
        return f"/กรุงไทย {rng.randint(0, 20000)}"
    if k == 9:
        return f"/ค่าใช้จ่าย {rng.randint(1, 100)} ค่าธรรมเนียม"
    if k == 10:
        return f"/ทัก {rng.randint(0, 20)}"
    return f"/ตั้ง {rng.randint(10, 5000)}"


def continuation():
    return " ".join(str(rng.randint(50, 2000)) for _ in range(rng.randint(1, 4)))


def expected_new_sales(text, today, rate):
    """
    นับว่าข้อความนี้ "ควร" ได้ออเดอร์ใหม่กี่อัน — คิดตามกติกา ไม่ได้เรียกโค้ดบอท
      - บรรทัดขึ้นต้น / = คำสั่ง ไม่ใช่ขาย
      - บรรทัดที่ทุกคำมีตัวเลข และตามหลัง /นับ /บูธ = ราคาบูธ ไม่ใช่ขาย
      - บรรทัดที่เหลือ = ขาย ถ้าแปลผ่าน
    """
    lines = [l for l in strip_thousands(text).splitlines() if l.strip()]
    if len(lines) == 1 and lines[0].strip().startswith("/"):
        return 0
    count, prev_is_list = 0, False
    has_cmd = any(l.strip().startswith("/") for l in lines)
    for l in lines:
        s = l.strip()
        if s.startswith("/"):
            prev_is_list = s.split()[0].lstrip("/").split("@")[0].lower() in LIST_CMDS
            continue
        numberish = all(any(c.isdigit() for c in w) for w in s.split())
        if has_cmd and prev_is_list and numberish:
            continue
        prev_is_list = False
        try:
            parse_line(s, today, rate)
            count += 1
        except ParseError:
            pass
    return count


reset()
say("/ซื้อ 1100 100")
for i in range(200):
    lines = []
    for _ in range(rng.randint(1, 4)):
        if lines and lines[-1].startswith(("/นับ", "/บูธ")) and rng.random() < 0.5:
            lines.append(continuation())
        elif rng.random() < 0.55:
            lines.append(sale_line())
        else:
            lines.append(cmd_line())
    msg = "\n".join(lines)
    want = expected_new_sales(msg, db.now_th().date(), db.current_rate(conn, 11.0))
    before = n_sales()
    r = tg(msg)
    got = n_sales() - before
    check(f"สุ่ม #{i:03d} ไม่พัง ตอบเสมอ",
          BOOM not in r and "ข้อผิดพลาด" not in r and r.strip() != "", f"{msg!r} → {r[:80]}")
    check(f"สุ่ม #{i:03d} ออเดอร์ใหม่ = {want}", got == want, f"ได้ {got} · {msg!r}")

# ยอด Token ในระบบต้องเท่ากับที่คิดจากตารางตรงๆ ทุกเมื่อ
raw = conn.execute(
    "SELECT (SELECT COALESCE(SUM(tokens),0) FROM purchase WHERE kind='token')"
    " + (SELECT COALESCE(SUM(tokens_realised),0) FROM purchase WHERE kind='lot')"
    " + (SELECT COALESCE(SUM(tokens),0) FROM token_move)"
    " - (SELECT COALESCE(SUM(tokens_spent),0) FROM sale)").fetchone()[0]
check("หลังสุ่มยิง ยอด Token ตรงกับผลรวมในตาราง", wallet() == raw, f"{wallet()} vs {raw}")
bad = conn.execute("SELECT COUNT(*) FROM sale WHERE price_baht <= 0 OR tokens_spent <= 0"
                   f" OR price_baht > {PRICE_MAX} OR tokens_spent > {TOKENS_MAX}"
                   " OR item_count < 1 OR item_count > 1000").fetchone()[0]
check("หลังสุ่มยิง ไม่มีออเดอร์ตัวเลขนอกเพดาน", bad == 0, str(bad))
for c in ("/today", "/week", "/month", "/band", "/ทุน", "/กำไรจริง", "/สุขภาพ",
          "/ส่วนตัว", "/รายการ", "/ค้าง", "/help"):
    r = tg(c)
    check(f"{c} หลังสุ่มยิง ยังตอบได้", BOOM not in r and "ข้อผิดพลาด" not in r and r.strip(), r[:60])
    check(f"{c} ทุกก้อนไม่เกิน 4,096 ตัวอักษร", all(len(x) <= 4096 for x in out))

# /undo ต้องลบตามลำดับที่บันทึกจริง แม้บันทึกในวินาทีเดียวกัน (บั๊กที่สุ่มยิงเจอ)
def counts():
    return tuple(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                 for t in ("sale", "purchase", "spend"))


reset()
say("/ซื้อ 1100 100")
tg("/จ่าย 50 ข้าว\n55 192")
s0 = counts()
tg("/undo")
check("ส่ง /จ่าย + ขาย พร้อมกัน → /undo ลบออเดอร์ (อันหลัง)",
      counts() == (s0[0] - 1, s0[1], s0[2]), f"{s0} → {counts()}")
tg("/undo")
check("/undo ครั้งที่สอง → ลบรายจ่าย", counts() == (s0[0] - 1, s0[1], s0[2] - 1), str(counts()))
tg("55 192\n/ซื้อ 700 63")
s0 = counts()
tg("/undo")
check("ส่ง ขาย + /ซื้อ พร้อมกัน → /undo ลบการซื้อ (อันหลัง)",
      counts() == (s0[0], s0[1] - 1, s0[2]), f"{s0} → {counts()}")
tg("/undo")
check("/undo ครั้งที่สอง → ลบออเดอร์", counts() == (s0[0] - 1, s0[1] - 1, s0[2]), str(counts()))
tg("55 192\n60 200\n70 300")
ids = [r[0] for r in conn.execute("SELECT id FROM sale ORDER BY id DESC LIMIT 3")]
tg("/undo")
check("ขาย 3 บรรทัดพร้อมกัน → /undo ลบบรรทัดสุดท้าย",
      conn.execute("SELECT MAX(id) FROM sale").fetchone()[0] == ids[1])
tg("/แก้ %d 80 400" % ids[1])
tg("/undo")
check("/แก้ ไม่ทำให้ /undo สับสน (ยังลบตามลำดับที่บันทึก)",
      conn.execute("SELECT MAX(id) FROM sale").fetchone()[0] == ids[2])
reset()
r = tg("/undo")
check("/undo ตอนไม่มีอะไร → บอกว่าไม่มีให้ลบ", "ไม่มีรายการ" in r, r[:60])
for _ in range(35):
    tg("55 192")
for _ in range(31):
    tg("/undo")
check("/undo ติดกันเกินที่กองจำ (30) → ยังลบได้ด้วยวิธีเดิม ไม่พัง", n_sales() == 4, str(n_sales()))

# /ทัก — 30 ก.ย. 2026 เจ้าของพิมพ์ /ทัก 4 ตอนมี 5 ออเดอร์ บอทโชว์ "ปิดได้ 125%"
#
# ล็อกเวลาเป็นบ่าย 2 เพราะ /ทัก ที่พิมพ์ก่อนตี 5 ลงวันที่เพิ่งจบ (กติกาใน BUSINESS.md)
# แต่ออเดอร์ลงวันตามปฏิทิน — ถ้ารันเทสต์ตอนตี 1 ออเดอร์อยู่วันนี้ /ทัก อยู่เมื่อวาน
# เทสต์เลยพังเฉพาะตอนกลางคืนทั้งที่บอทไม่ได้ผิด (เจอ 15 ต.ค. 2026 ตอนตี 1)
_real_now = db.now_th
_TZ = timezone(timedelta(hours=7))
_day = _real_now().date()
db.now_th = lambda: datetime(_day.year, _day.month, _day.day, 14, 0, tzinfo=_TZ)
try:
    reset()
    say("/ซื้อ 1100 100")
    for _ in range(5):
        tg("55 192")
    r = tg("/ทัก 4")
    check("/ทัก น้อยกว่าออเดอร์ → ไม่โชว์ % เกิน 100", "125" not in r and "ปิดได้" not in r, r[-120:])
    check("/ทัก น้อยกว่าออเดอร์ → บอกว่ามีคนซื้อหลายรอบ", "หลายรอบ" in r, r[-120:])
    r = tg("/ทัก 10")
    check("/ทัก มากกว่าออเดอร์ → โชว์อัตราปิดปกติ", "ปิดได้ 50.0%" in r, r[-80:])
    r = tg("/ทัก 5")
    check("/ทัก เท่าออเดอร์พอดี → ปิดได้ 100%", "ปิดได้ 100.0%" in r, r[-80:])
    tg("/ทัก 3")
    tg("/ทัก 8")
    check("/ทัก สองรอบ → ตัวหลังเขียนทับ ไม่บวกกัน",
          db.day_summary(conn, bot.business_day())["inquiries"] == 8)
    r = tg("/ทัก 0")
    check("/ทัก 0 ใช้ได้ ไม่หารศูนย์พัง", BOOM not in r and "ข้อผิดพลาด" not in r, r[-80:])

    # กติกาตอนตี 1: /ทัก ต้องลงวันที่เพิ่งจบ ไม่ใช่วันใหม่
    db.now_th = lambda: datetime(_day.year, _day.month, _day.day, 1, 0, tzinfo=_TZ)
    tg("/ทัก 7")
    yday = (_day - timedelta(days=1)).isoformat()
    check("/ทัก ตอนตี 1 → ลงวันที่เพิ่งจบ",
          db.day_summary(conn, yday)["inquiries"] == 7, str(db.day_summary(conn, yday)["inquiries"]))
finally:
    db.now_th = _real_now


# ==============================================================
section("F. สำเนาข้อมูลจริง (backup/) — ป้อนข้อความจริงบนข้อมูลจริง")
# ==============================================================
backups = sorted((ROOT / "backup").glob("supabase_*.db"))
if not backups:
    print("  (ข้าม — ไม่มีไฟล์สำรอง backup/supabase_*.db)")
else:
    conn.close()
    copy = ROOT / "data" / "realinput_realdata.db"
    shutil.copy(backups[-1], copy)
    db.DB_PATH = copy
    conn = db.connect()
    base_n = n_sales()
    base_rev = conn.execute("SELECT SUM(price_baht) FROM sale").fetchone()[0]
    check("สำเนาข้อมูลจริงเปิดได้ มีออเดอร์", base_n > 100, str(base_n))

    for c in ("/today", "/yesterday", "/week", "/month", "/band", "/ทุน", "/กำไรจริง",
              "/สุขภาพ", "/ส่วนตัว", "/รายการ", "/ค้าง", "/โอน", "/ยกยอด", "/ค่าใช้จ่าย",
              "/กรุงไทย", "/เหลือ", "/เช็ค", "/นับ", "/บูธ", "/help"):
        r = tg(c)
        check(f"ข้อมูลจริง {c} ตอบได้", BOOM not in r and "ข้อผิดพลาด" not in r and r.strip(), r[:60])

    # ข้อความปิดเดือน ก.ย. บนข้อมูลจริง ต้องตรงกับยอดเงินสดที่คิดตรงจากตาราง
    cs = db.cash_summary(conn, "2026-09-01", "2026-09-30")
    real_now = db.now_th
    db.now_th = lambda: datetime(2026, 10, 1, 9, 0, tzinfo=timezone(timedelta(hours=7)))
    try:
        mc = bot.text_month_close(conn)
    finally:
        db.now_th = real_now
    check("ปิดเดือนบนข้อมูลจริง: กำไรเงินสดตรงกับตาราง",
          f"{cs['profit_cash']:,.0f}" in mc, f"{cs['profit_cash']:,.0f} ไม่อยู่ใน {mc[:200]}")
    check("ปิดเดือนบนข้อมูลจริง: บอกเงินที่ย้ายออก 10,230", "10,230" in mc, mc[:300])
    check("ปิดเดือนบนข้อมูลจริง: ไม่ทายยอดกรุงไทย", "ควรอยู่ราว" not in mc)

    # คำสั่งจริงที่เจ้าของพิมพ์คืน 30 ก.ย. — ผลต้องออกมาเหมือนที่เห็นในแชท
    tg("/นับ 3780 1660 639 620 600 595 499 380 350 350 350 310 255 250 210 100 90")
    check("ข้อมูลจริง /นับ ของจริง → ไอดี 3,780", wallet() == 3780, str(wallet()))
    check("ข้อมูลจริง /นับ ของจริง → บูธ 7,258", booth() == 7258, str(booth()))
    check("ข้อมูลจริง /นับ ไม่เกิดออเดอร์", n_sales() == base_n)
    # เดิมเช็กเลข 344 · 653 · 11,066 ที่เห็นในแชทคืน 30 ก.ย. ซึ่งตีราคาที่เรท 11 ตายตัว
    # 15 ต.ค. 2026 เปลี่ยนให้ /ทุน ใช้เรทพ่อค้าครั้งล่าสุด (สำเนาข้อมูลนี้ = 10.0)
    # เลยคิดเลขที่ควรได้จากเรทในข้อมูลเอง ไม่ฝังเลขที่ขึ้นกับเรทเก่าไว้
    mr = db.current_rate(conn, 0) or bot.STOCK_RATE
    want_tok = 3780 / mr
    want_booth = 7258 * (1 - bot.BOOTH_FEE) / mr
    r = tg("/ทุน")
    check(f"ข้อมูลจริง /ทุน ตีราคา Token {want_tok:,.0f} · บูธ {want_booth:,.0f} (เรท {mr:g})",
          f"{want_tok:,.0f}" in r and f"{want_booth:,.0f}" in r, r[:200])
    check("ข้อมูลจริง /ทุน ไม่ตีราคาที่เรท 11 ตายตัวแล้ว", mr == 11 or "344" not in r, r[:200])
    tg("/กรุงไทย 10069")
    want_total = 10069 + want_tok + want_booth
    check(f"ข้อมูลจริง /ทุน รวม {want_total:,.0f}", f"{want_total:,.0f}" in tg("/ทุน"), out[-1][:200])

    tg("55 192")
    check("ข้อมูลจริง จดขายเพิ่มได้", n_sales() == base_n + 1)
    r = tg(edited="55 195")
    check("ข้อมูลจริง กดแก้ข้อความ → ไม่เพิ่มออเดอร์", n_sales() == base_n + 1)
    tg("/undo")
    rev = conn.execute("SELECT SUM(price_baht) FROM sale").fetchone()[0]
    check("ข้อมูลจริง /undo แล้วกลับมาเท่าเดิมเป๊ะ", n_sales() == base_n and abs(rev - base_rev) < 0.01,
          f"{n_sales()} {rev}")
    # เรทคิดจากชุด Token (LIFO) แก้ด้วยตัวเลขเดิม ต้นทุนต้องไม่ขยับ
    want_rate = round(db.lifo_costs(conn)[0][44], 3)
    r = tg("/แก้ 44 750 12801")
    row = conn.execute("SELECT * FROM sale WHERE id = 44").fetchone()
    check("ข้อมูลจริง /แก้ #44 ไม่เปลี่ยนเรท/วันที่/หมายเหตุ",
          row is not None and abs(row["token_rate"] - want_rate) < 0.001
          and row["sold_on"] == "2026-09-19" and "6,304" in (row["note"] or ""), str(dict(row) if row else None))
    conn.close()
    copy.unlink()


# ==============================================================
print("\n" + "=" * 62)
print(f"รันไป {n} เคส · ผ่าน {len(passed)} · พัง {len(failed)}")
if failed:
    print("\nที่ต้องแก้:")
    for f in failed:
        print(f"  - {f}")
print("=" * 62)

try:
    conn.close()
except Exception:
    pass
for p in (ROOT / "data" / "realinput.db",):
    try:
        p.unlink()
    except Exception:
        pass

sys.exit(1 if failed else 0)
