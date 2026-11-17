"""
เทสต์แบบรวดเดียว — รันด้วย  python tests/smoke.py

ยิงคำสั่งเข้าบอทจริงๆ โดยไม่ต่อ Telegram (สลับตัวส่งข้อความเป็นตัวปลอม)
ใช้ไล่เช็กว่าแก้โค้ดแล้วยังไม่พังตรงไหน
"""
import io
import os
import sys
from pathlib import Path

# ใช้ฐานข้อมูลแยกและ token ปลอม จะได้ไม่ไปแตะข้อมูลจริง
os.environ.setdefault("BOT_TOKEN", "test-token")

# ⚠️ บรรทัดนี้สำคัญที่สุดในไฟล์ ห้ามลบ
# บังคับให้เทสต์ใช้ SQLite เสมอ แม้จะตั้ง DATABASE_URL ไว้ใน .env
# เพราะ db.DB_PATH ข้างล่างมีผลเฉพาะตอนเป็น SQLite
# ถ้าไม่มีบรรทัดนี้ เทสต์จะวิ่งไปที่ Supabase แล้ว reset() จะสั่ง
# DELETE FROM ทุกตาราง = ล้างข้อมูลจริงทิ้งทั้งหมด
os.environ["LEDGER_FORCE_SQLITE"] = "1"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import db

db.DB_PATH = ROOT / "data" / "test_ledger.db"

import bot

out = []
bot.api = lambda method, **p: (out.append(p.get("text", "")), {"ok": True})[1]
conn = db.connect()

fails = []


def reset():
    # เพิ่มตารางใหม่แล้วต้องมาเพิ่มตรงนี้ด้วย ไม่งั้นข้อมูลค้างข้ามรอบเทสต์
    # แล้วเทสต์จะพังแบบงงๆ ทั้งที่โค้ดจริงไม่ได้ผิด
    for t in ("sale", "day_log", "purchase", "app_state", "job_log",
              "spend", "token_move", "transfer", "balance_snapshot",
              "pending_order", "expense"):
        conn.execute(f"DELETE FROM {t}")
    conn.commit()


def check(label, condition, detail=""):
    mark = "ok  " if condition else "พัง "
    if not condition:
        fails.append(label)
    print(f"  {mark} {label}" + (f"  · {detail}" if detail and not condition else ""))


def say(text):
    out.clear()
    bot.handle_text(conn, 1, text)
    return "\n".join(out)


def rows(sql):
    return [dict(r) for r in conn.execute(sql)]


print("ข้อความว่าง ไม่ทำให้บอทล้ม")
reset()
for t in ("", "   ", "\n\n"):
    check(f"{t!r}", "ว่าง" in say(t))

print("\nคำสั่งต้องมี / นำหน้า · บรรทัดขายห้ามถูกมองเป็นคำสั่ง")
reset()
say("/ซื้อ 700 63")
say("เมื่อวาน 80 300 ระเบิด a")
check("เมื่อวาน ... ถูกบันทึกเป็นการขาย", len(rows("SELECT * FROM sale")) == 1)
check("ลงวันที่เมื่อวานถูก", rows("SELECT sold_on FROM sale")[0]["sold_on"]
      == (db.now_th().date().replace(day=db.now_th().day) .__sub__(__import__("datetime").timedelta(days=1))).isoformat())
check("พิมพ์ ย่อย เปล่าๆ ได้คำเตือนเรื่อง /", "ต้องมี /" in say("ย่อย"))
check("คำสั่งมั่วได้ข้อความบอก", "ไม่รู้จักคำสั่ง" in say("/มั่ว"))

print("\nเรทต้องไม่ถูกตั้งเป็นค่าที่หารไม่ได้")
reset()
say("/เหมา 2297 130 7")
before = db.current_rate(conn, 11)
say("/ย่อย 0")
say("/ย่อย -50")
check("/ย่อย 0 และติดลบ ไม่เปลี่ยนเรท", db.current_rate(conn, 11) == before,
      f"เรทกลายเป็น {db.current_rate(conn, 11)}")
check("ขายต่อได้ปกติ", "กำไร" in say("55 192"))
check("/ซื้อ สลับเลข ถูกปฏิเสธ", "นอกช่วง" in say("/ซื้อ 63 700"))

print("\nข้อความยาวต้องถูกหั่นให้ Telegram รับได้")
reset()
say("/ซื้อ 700 63")
out.clear()
bot.handle_text(conn, 1, "\n".join("55 192 ดาบ a" for _ in range(60)))
check("60 บรรทัด ส่งออกหลายก้อน", len(out) > 1, f"ส่งออก {len(out)} ก้อน")
check("ทุกก้อนไม่เกิน 4096", all(len(s) <= 4096 for s in out))
check("บันทึกครบ 60 รายการ", len(rows("SELECT * FROM sale")) == 60)

print("\n/close ต้องไม่ถามวันที่ขายได้อยู่แล้ว")
reset()
say("/ซื้อ 700 63")
say("80 300")
# ระบุ "วันนี้" ให้ชัด เพราะ /close เปล่าๆ อ้างวันทำการ ซึ่งเปลี่ยนตามเวลาที่รันเทสต์
check("วันที่มีขายแล้ว บอทบอกว่าไม่ต้องระบุ",
      "ไม่ต้องระบุสาเหตุ" in say("/close วันนี้"))

print("\nรายจ่ายส่วนตัวต้องไม่ปนกับกำไรธุรกิจ")
reset()
say("/ซื้อ 700 63")
say("170 371 ดาบ a")
say("/จ่าย 50 ข้าว 120 เที่ยว")
cash = db.cash_summary(conn, "2000-01-01", "2100-01-01")
check("กำไรธุรกิจไม่ถูกหักด้วยค่าข้าว", abs(cash["profit_cash"] - 107.0) < 0.01,
      f"ได้ {cash['profit_cash']}")
check("รายจ่ายส่วนตัวเก็บแยก",
      db.spend_total(conn, "2000-01-01", "2100-01-01") == 170.0)
check("/เหลือ คำนวณได้", "ใช้ได้วันละ" in say("/เหลือ 1024"))
check("/ส่วนตัว สรุปได้", "งบ" in say("/ส่วนตัว"))

print("\nการย้ายเงินต้องไม่ทำให้กำไรเปลี่ยน")
#
# กฎเดียวกับตาราง spend แต่พลาดง่ายกว่า เพราะเงินที่ย้ายออกจากบัญชีร้าน
# "รู้สึก" เหมือนเงินออกจากธุรกิจ  แต่มันแค่ย้ายกระเป๋า ยังเป็นเงินเจ้าของอยู่
# ถ้าเผลอเอาไปหักจากกำไร กำไรจะต่ำกว่าจริงตามจำนวนที่ย้าย
# ซึ่งเป็นอาการเดียวกับที่ทำให้ ก.ย. 2026 บอทบอกว่าเก็บเงินได้ 95 บาท
reset()
say("/ซื้อ 700 63")
say("170 371 ดาบ a")
before = db.cash_summary(conn, "2000-01-01", "2100-01-01")["profit_cash"]
say("/โอน 5600 dime")
say("/โอน 4000 kbank ไว้ใช้")
after = db.cash_summary(conn, "2000-01-01", "2100-01-01")["profit_cash"]
check("กำไรไม่เปลี่ยนหลังย้ายเงิน 9,600฿", abs(before - after) < 0.01,
      f"ก่อน {before} หลัง {after}")
check("ยอดที่ย้ายเก็บแยกไว้",
      db.transfer_total(conn, "2000-01-01", "2100-01-01") == 9600.0)
check("ควักเงินตัวเองใส่ร้านจดเป็นค่าลบได้",
      db.add_transfer(conn, -500, "เติมเข้าร้าน") > 0
      and db.transfer_total(conn, "2000-01-01", "2100-01-01") == 9100.0)
check("/โอน สรุปปลายทางได้", "dime" in say("/โอน"))
check("/กำไรจริง แสดง 3 ชั้น",
      all(s in say("/กำไรจริง") for s in ("กำไรเงินสด", "ของที่ตุนไว้", "กำไรจริง")))
check("/กรุงไทย บอกว่าเงินไม่ได้อยู่ที่เดียว",
      "ย้ายออกไปเก็บแล้ว" in say("/กรุงไทย 1095"))

# เรทเฉลี่ยถ่วงน้ำหนัก
#
# ค่าสำรองที่ส่งเข้าไปตั้งเป็น 99.0 ซึ่งเป็นเลขที่เกิดจากข้อมูลจริงไม่ได้
# ถ้าเผลอคืนค่าสำรองมาแทนที่จะคำนวณ เทสต์จะจับได้ทันที
# (รอบแรกเขียนเทสต์นี้ด้วยเลขที่เรทออกมา 11.0 เท่าค่าสำรองพอดี
#  เทสต์ผ่านทั้งที่ยังแยกไม่ออกว่าคำนวณจริงหรือใช้ค่าสำรอง)
FAKE = 99.0
reset()
say("/ซื้อ 1200 100")                 # ได้ 1,200 Token จ่าย 100฿ = เรท 12
rate_before, pending_before = db.blended_rate(conn, FAKE)
check("คิดเรทเฉลี่ยจากข้อมูลจริง ไม่ใช่ค่าสำรอง",
      abs(rate_before - 12.0) < 0.01, f"ได้ {rate_before}")

say("/เหมา 2800 100")                 # RAP 2,800 จ่าย 100฿ · ยังไม่ได้ย่อย
rate_after, pending_after = db.blended_rate(conn, FAKE)
check("ล็อตที่ยังไม่ย่อย นับเงินที่จ่ายแต่ยังไม่นับ Token",
      abs(rate_after - 6.0) < 0.01, f"ได้ {rate_after} ควรเป็น 1200/200")
check("นับได้ว่ามีล็อตค้างกี่ล็อต", pending_after == pending_before + 1)

# ไม่ /ย่อย แต่ Token จากของเหมาเข้ามาทาง /นับ (adjust) — ต้องนับด้วย
# 16 พ.ย. 2026 สูตรเดิมไม่นับ เรทจริงออกมา 9.82 ต่ำกว่าทุกแหล่ง
mv = db.add_token_move(conn, 2700, "adjust")
rate_adj, _ = db.blended_rate(conn, FAKE)
check("Token ที่เข้ามาทาง /นับ ถูกนับในเรทเฉลี่ย",
      abs(rate_adj - 19.5) < 0.01, f"ได้ {rate_adj} ควรเป็น 3900/200")
conn.execute("DELETE FROM token_move WHERE id = ?", (mv,)); conn.commit()

db.set_lot_realised(conn, db.latest_lot(conn)["id"], 2700)
rate_done, pending_done = db.blended_rate(conn, FAKE)
check("กรอกย่อยแล้วเรทขึ้นและไม่ค้าง",
      abs(rate_done - 19.5) < 0.01 and pending_done == pending_before,
      f"เรท {rate_done} ควรเป็น 3900/200 · ค้าง {pending_done}")
# กลับทิศ 30 ก.ย. 2026 — เจ้าของจะไม่ /ย่อย (ของเหมาปนกันในบูธ จำไม่ได้)
# คำเตือนที่ไม่มีวันหายไป = เสียงรบกวน · กำไรถูกอยู่แล้วเพราะ /นับ เห็นของทั้งสองที่
check("/กำไรจริง ไม่ตามทวง /ย่อย แล้ว",
      "ยังไม่ได้บอกว่าย่อยได้" not in (say("/เหมา 500 20"), say("/กำไรจริง"))[1])

print("\nเตือนเมื่อเลขบูธค้างจนนับซ้ำ")
#
# เกิดจริง 27 ก.ย. 2026 — /บูธ 9773 จดไว้เมื่อวาน แล้ววันนี้ /เช็ค 13773
# ของในบูธที่ขายออกไปแล้วกลายเป็น Token ในไอดี แต่เลขบูธไม่ลดตาม
# บอทเลยนับของตุนเป็น 23,448 ทั้งที่ของจริงมีราว 16,000
reset()
say("/ซื้อ 700 63")
say("/บูธ 5000")
check("จดบูธแล้วยังไม่เตือน", "เลขบูธ" not in say("/ทุน"))
check("/บูธ ใส่ราคาหลายชิ้นแล้วบวกให้เอง",
      "3,051" in say("/บูธ 599 529 488 459 269 269 269 169"))
check("เก็บยอดรวมถูก", int(db.get_state(conn, "booth_tokens")) == 3051)
say("/บูธ 5000")
say("/เช็ค 400")
check("เช็คหลังจดบูธ ต้องเตือนว่านับซ้ำ", "เลขบูธ" in say("/ทุน"))
check("เตือนใน /กำไรจริง ด้วย", "เลขบูธ" in say("/กำไรจริง"))
say("/บูธ 0")
check("อัปเดตบูธแล้วเลิกเตือน", "เลขบูธ" not in say("/ทุน"))

print("\nจดยอดเงินตั้งต้นแล้วกระทบยอดได้")
reset()
check("ยังไม่จดยอด บอทบอกให้ไปจด", "ยกยอด" in say("/กำไรจริง"))
check("/ยกยอด บวกหลายบัญชีให้เอง", "17,351" in say("/ยกยอด 1095 10000 3600 2656"))
check("เก็บยอดรวมถูก",
      db.last_snapshot(conn)["cash_baht"] == 17351.0)

# จดยอดตั้งต้นต่ำ แล้วยอดปลายสูงขึ้นมากกว่ากำไรที่ทำได้
# แปลว่ามีเงินจากนอกธุรกิจเข้ามา บอทต้องทักแบบนั้น ไม่ใช่บอกว่าถอนไปใช้
reset()
db.add_snapshot(conn, 1000, taken_on="2000-01-01")
say("/ซื้อ 700 63")
say("170 371 ดาบ a")
db.add_snapshot(conn, 50000)
check("เงินเพิ่มเกินกำไร บอทบอกว่ามีเงินนอกเข้ามา",
      "เงินจากนอกธุรกิจ" in say("/กำไรจริง"))

reset()
db.add_snapshot(conn, 50000, taken_on="2000-01-01")
say("/ซื้อ 700 63")
say("170 371 ดาบ a")
db.add_snapshot(conn, 1000)
check("เงินหายเกินกำไร บอทบอกว่าถอนไปใช้",
      "ถอนไปใช้ส่วนตัว" in say("/กำไรจริง"))

print("\nสรุปยอดและงานตามเวลาไม่ล้ม")
reset()
say("/ซื้อ 700 63")
say("55 192 ดาบ a")
for fn, label in ((bot.text_today, "/today"), (bot.text_week, "/week"),
                  (bot.text_month, "/month"), (bot.text_band, "/band"),
                  (bot.text_month_close, "ข้อความปิดเดือน")):
    try:
        fn(conn)
        check(label, True)
    except Exception as e:
        check(label, False, f"{type(e).__name__}: {e}")
out.clear()
try:
    bot.run_scheduled_jobs(conn)
    n = len(out)
    bot.run_scheduled_jobs(conn)
    check("งานตามเวลาไม่ยิงซ้ำ", len(out) == n)
except Exception as e:
    check("งานตามเวลา", False, f"{type(e).__name__}: {e}")

print("\nคำสั่งวิเคราะห์ใน analysis/queries.sql")
ok = bad = 0
sql = (ROOT / "analysis" / "queries.sql").read_text(encoding="utf-8")
for block in (s for s in sql.split(";") if s.strip() and not all(
        l.strip().startswith("--") or not l.strip() for l in s.splitlines())):
    try:
        conn.execute(block).fetchall()
        ok += 1
    except Exception as e:
        bad += 1
        print(f"    พัง: {e}")
check(f"query รันผ่าน {ok} ข้อ", bad == 0)

print("\nค่าธรรมเนียมต้องหักจากกำไรร้าน")
#
# ตารางเงินมี 4 ตัว และกฎไม่เหมือนกัน — จุดที่สับสนง่ายที่สุดในระบบนี้
#   purchase  ของเข้าร้าน        ลดกำไร
#   expense   ค่าธรรมเนียม ฯลฯ   ลดกำไร   ← เพิ่ม 27 ก.ย. 2026
#   spend     เงินส่วนตัว        ไม่แตะกำไร
#   transfer  ย้ายกระเป๋า        ไม่แตะกำไร
#
# ที่มา: ทรูหัก 25 บาทตอนดึงเงินเข้าธนาคารเพราะใช้เกินโควตาฟรีของเดือน
# ออเดอร์นั้นรับมา 60 บาท ค่าธรรมเนียมกินไป 65% ของกำไร
# และการกระทบยอดธนาคารจับไม่ได้ เพราะหักจากวอลเล็ทไม่ใช่กรุงไทย
reset()
say("/ซื้อ 700 63")
say("60 240")
before = db.cash_summary(conn, "2000-01-01", "2100-01-01")["profit_cash"]
say("/ค่าใช้จ่าย 25 ค่าธรรมเนียมทรู")
after = db.cash_summary(conn, "2000-01-01", "2100-01-01")["profit_cash"]
check("ค่าธรรมเนียมทำให้กำไรลดลง 25฿", abs((before - after) - 25) < 0.01,
      f"{before} -> {after}")
check("เก็บยอดแยกไว้",
      db.expense_total(conn, "2000-01-01", "2100-01-01") == 25.0)
check("/ค่าใช้จ่าย สรุปตามหมวดได้", "ค่าธรรมเนียมทรู" in say("/ค่าใช้จ่าย"))
check("/กำไรจริง แสดงบรรทัดค่าธรรมเนียม", "ค่าธรรมเนียม" in say("/กำไรจริง"))

base = db.cash_summary(conn, "2000-01-01", "2100-01-01")["profit_cash"]
say("/จ่าย 100 ข้าว")
say("/โอน 500 dime")
check("จ่ายส่วนตัวกับย้ายเงินยังไม่แตะกำไร",
      abs(db.cash_summary(conn, "2000-01-01", "2100-01-01")["profit_cash"] - base) < 0.01)

print("\nออเดอร์ค้างส่งต้องไม่ถูกนับเป็นกำไร")
#
# เงินที่ลูกค้าโอนมาแล้วแต่ยังไม่ได้ส่งของ ยังไม่ใช่กำไร เพราะยังติดหนี้ของอยู่
# ถ้าเผลอนับ กำไรจะสูงเกินจริงทันทีที่เงินเข้า
reset()
say("/ซื้อ 700 63")
say("170 371")
before = db.cash_summary(conn, "2000-01-01", "2100-01-01")["profit_cash"]
say("/ค้าง 750 น้องคนนั้น")
after = db.cash_summary(conn, "2000-01-01", "2100-01-01")["profit_cash"]
check("จดออเดอร์ค้างแล้วกำไรต้องไม่ขยับ", abs(before - after) < 0.01,
      f"{before} -> {after}")
check("ยอดค้างเก็บแยกไว้", db.pending_total(conn) == 750.0)
check("/ค้าง แสดงรายการที่ค้างอยู่", "น้องคนนั้น" in say("/ค้าง"))
check("/กำไรจริง เตือนว่ามีออเดอร์ค้าง", "ค้างส่ง" in say("/กำไรจริง"))

pid = db.open_pendings(conn)[0]["id"]
check("/ส่งแล้ว ปิดรายการได้", "ส่งของแล้ว" in say(f"/ส่งแล้ว {pid}"))
check("ปิดแล้วยอดค้างเหลือ 0", db.pending_total(conn) == 0.0)
check("ปิดซ้ำต้องบอกว่าไม่เจอ", "ไม่เจอ" in say(f"/ส่งแล้ว {pid}"))
say("/ค้าง 300 ลูกค้าเปลี่ยนใจ")
pid2 = db.open_pendings(conn)[0]["id"]
check("/คืนเงิน ปิดรายการได้", "คืนเงินแล้ว" in say(f"/คืนเงิน {pid2}"))
check("ประวัติยังอยู่ ไม่ได้ถูกลบทิ้ง",
      conn.execute("SELECT COUNT(*) FROM pending_order").fetchone()[0] == 2)

print("\nบัญชีที่เงินเข้า")
reset()
say("/ซื้อ 700 63")
say("100 300")
check("ไม่ระบุบัญชี = กรุงไทยโดยปริยาย",
      conn.execute("SELECT account FROM sale ORDER BY id DESC LIMIT 1"
                   ).fetchone()[0] == "ktb")
r = say("100 300 ทรู")
check("ระบุ ทรู แล้วเก็บเป็น truemoney",
      conn.execute("SELECT account FROM sale ORDER BY id DESC LIMIT 1"
                   ).fetchone()[0] == "truemoney")
check("บอกในข้อความตอบกลับด้วยว่าเข้าบัญชีอื่น", "เข้า truemoney" in r, r[:90])
r = say("100 300")
check("รายการปกติไม่ต้องบอกบัญชี", "เข้า ktb" not in r)

print("\nถามจำนวนคนทักตอนสรุปกลางคืน")
#
# งานกลางคืนยิงเฉพาะช่วง NIGHTLY_HOUR ถึง +5 ชั่วโมง (เที่ยงคืน–ตี 5)
# ถ้ารันเทสต์ตอนกลางวันจะไม่ยิงเลย ผลเทสต์เลยขึ้นกับเวลาที่รัน
# ต้องปลอมนาฬิกาให้อยู่ในช่วงนั้น เทสต์ถึงจะให้ผลเหมือนกันทุกครั้ง
from datetime import datetime as _DT, timedelta as _TD           # noqa: E402

_real_now = db.now_th
_yesterday = (_real_now().date() - _TD(days=1))


def _fake_now():
    """ตี 0:30 ของวันนี้ — เวลาที่งานสรุปของ 'เมื่อวาน' ควรทำงาน"""
    return _DT.combine(_real_now().date(), _DT.min.time()).replace(
        hour=0, minute=30, tzinfo=db.TH)


reset()
say("/ซื้อ 700 63")
say("มว 100 300")                       # ขายเมื่อวาน = วันที่งานกลางคืนจะสรุป
db.now_th = _fake_now
try:
    out.clear()
    bot.run_scheduled_jobs(conn)
    nightly = "\n".join(out)
    # 16 พ.ย. 2026 เลิกถาม — ไม่ได้จด = เติมให้ว่าปิด 100% แล้วบอกให้รู้แทน
    check("สรุปกลางคืน ไม่ได้จดคนทัก → เติมให้และบอก",
          "ถือว่าปิดได้ 100%" in nightly
          and db.day_summary(conn, _yesterday.isoformat())["inquiries"] == 1, nightly[:300])

    db.set_inquiries(conn, _yesterday.isoformat(), 12)
    conn.execute("DELETE FROM job_log")
    conn.commit()
    out.clear()
    bot.run_scheduled_jobs(conn)
    check("ตอบแล้วไม่ถามซ้ำ", "มีคนทักกี่คน" not in "\n".join(out))
finally:
    db.now_th = _real_now

print("\nฐานข้อมูลเก่าต้องถูกเติมคอลัมน์ให้เองตอนเปิด")
#
# บั๊กจริง 27 ก.ย. 2026 — เพิ่มคอลัมน์ account ใน schema.sql
# แต่ CREATE TABLE IF NOT EXISTS ไม่แตะตารางที่มีอยู่แล้ว
# ฐานข้อมูลจริงเลยไม่มีคอลัมน์นั้น แล้วบอทจดของไม่ได้เลยทั้งวัน
#
# เทสต์เดิมไม่จับ เพราะสร้างฐานใหม่ทุกครั้งซึ่งมีคอลัมน์ครบอยู่แล้ว
# เทสต์นี้จำลอง "ฐานเก่าที่ใช้มาแล้ว" โดยสร้างตารางแบบไม่มีคอลัมน์ใหม่
import sqlite3 as _sq                                            # noqa: E402

_old_db = ROOT / "data" / "old_shape.db"
if _old_db.exists():
    _old_db.unlink()
_old = _sq.connect(_old_db)
_old.executescript("""
    CREATE TABLE sale (
        id INTEGER PRIMARY KEY, sold_on TEXT NOT NULL, logged_at TEXT NOT NULL,
        price_baht REAL NOT NULL, tokens_spent INTEGER NOT NULL,
        token_rate REAL NOT NULL, source TEXT NOT NULL DEFAULT 'seller',
        item_count INTEGER NOT NULL DEFAULT 1, note TEXT);
    INSERT INTO sale (sold_on, logged_at, price_baht, tokens_spent, token_rate)
    VALUES ('2026-09-20', '2026-09-20T12:00:00+07:00', 100, 500, 11);
""")
_old.commit()
_old.close()

_saved_path = db.DB_PATH
try:
    db.DB_PATH = _old_db
    old_conn = db.connect()
    cols = {r[1] for r in old_conn.execute("PRAGMA table_info(sale)").fetchall()}
    check("เปิดฐานเก่าแล้วคอลัมน์ account ถูกเติมให้เอง", "account" in cols,
          f"มี {sorted(cols)}")
    check("ข้อมูลเดิมยังอยู่ครบ",
          old_conn.execute("SELECT COUNT(*) FROM sale").fetchone()[0] == 1)
    check("แถวเดิมได้ค่าปริยาย ktb",
          old_conn.execute("SELECT account FROM sale").fetchone()[0] == "ktb")
    new_id = db.insert_sale(old_conn, {"price_baht": 50, "tokens_spent": 200,
                                       "token_rate": 11})
    check("จดรายการใหม่ลงฐานเก่าได้", new_id > 0)
    old_conn.close()
except Exception as e:
    check("เติมคอลัมน์ให้ฐานเก่า", False, f"{type(e).__name__}: {e}")
finally:
    db.DB_PATH = _saved_path
    if _old_db.exists():
        try:
            _old_db.unlink()
        except OSError:
            pass

conn = db.connect()      # ต่อฐานเทสต์กลับคืน

print("\nเทสต์ต้องไม่มีทางไปแตะฐานข้อมูลจริง")
#
# 28 ก.ย. 2026 เกือบพัง — พอตั้ง DATABASE_URL ใน .env
# เทสต์วิ่งไปที่ Supabase ทันที ทั้งที่ตั้ง db.DB_PATH ชี้ไฟล์ทดสอบไว้แล้ว
# (ค่านั้นมีผลเฉพาะตอนเป็น SQLite) แล้ว reset() สั่ง DELETE FROM ทุกตาราง
# ถ้าตอนนั้นข้อมูลอยู่บน Supabase แล้ว = หายทั้งหมดโดยไม่มีอะไรเตือน
import store as _store                                           # noqa: E402
check("เทสต์นี้กำลังใช้ SQLite ไม่ใช่ Postgres",
      _store.backend() == "sqlite", f"กำลังใช้ {_store.backend()}")
check("ไฟล์ฐานข้อมูลที่ใช้เป็นไฟล์ทดสอบ",
      "test" in str(db.DB_PATH), str(db.DB_PATH))
check("ทั้งสองไฟล์เทสต์บังคับ SQLite ไว้",
      all("LEDGER_FORCE_SQLITE" in (ROOT / "tests" / f).read_text(encoding="utf-8")
          for f in ("smoke.py", "adversarial.py")))

print("\ntransaction ต้องย้อนกลับได้จริง และ Postgres ต้องเป็น autocommit")
#
# 28 ก.ย. 2026 เจอบั๊กบนของจริง: Postgres เปิด transaction ให้ทุก SELECT
# แล้วถ้ามีคำสั่งไหน error ทุกคำสั่งหลังจากนั้นพังหมด (InFailedSqlTransaction)
# เจ้าของพิมพ์ผิดครั้งเดียว = บอทใช้ไม่ได้ทั้งตัว
#
# SQLite ไม่มีพฤติกรรมนี้ เทสต์ตรงนี้เลยจับบั๊กตัวจริงไม่ได้
# ทำได้แค่ตรวจว่าโค้ดตั้ง autocommit=True ไว้ และห้ามมีใครเปลี่ยนกลับ
# ส่วนพิสูจน์บนของจริงอยู่ใน tools/check_live.py (ไม่แตะข้อมูล)
_store_src = (ROOT / "src" / "store.py").read_text(encoding="utf-8")
check("Postgres ต่อแบบ autocommit=True",
      "autocommit=True" in _store_src and "autocommit=False" not in _store_src)

reset()
say("/ซื้อ 700 63")
before = conn.execute("SELECT COUNT(*) FROM sale").fetchone()[0]
try:
    with conn.transaction():
        conn.execute("INSERT INTO sale (sold_on, logged_at, price_baht, tokens_spent,"
                     " token_rate) VALUES ('2026-09-28', '2026-09-28T12:00:00+07:00',"
                     " 100, 200, 11)")
        raise RuntimeError("จงใจให้พังกลางก้อน")
except RuntimeError:
    pass
check("transaction() พังกลางก้อนแล้วย้อนกลับหมด",
      conn.execute("SELECT COUNT(*) FROM sale").fetchone()[0] == before)

with conn.transaction():
    conn.execute("INSERT INTO sale (sold_on, logged_at, price_baht, tokens_spent,"
                 " token_rate) VALUES ('2026-09-28', '2026-09-28T12:00:00+07:00',"
                 " 100, 200, 11)")
check("transaction() สำเร็จแล้วบันทึกจริง",
      conn.execute("SELECT COUNT(*) FROM sale").fetchone()[0] == before + 1)

_mig_src = (ROOT / "tools" / "migrate_to_supabase.py").read_text(encoding="utf-8")
check("ตัวย้ายข้อมูลใช้ transaction() ไม่ใช่ rollback() เฉยๆ",
      "with conn.transaction():" in _mig_src and "conn.rollback()" not in _mig_src)

print("\nตัวย้ายข้อมูลต้องรู้จักทุกตาราง")
#
# 28 ก.ย. 2026 เกือบพลาด — สร้างตาราง transfer/balance_snapshot/pending_order/expense
# ทีหลังแล้วลืมเพิ่มในรายการของ tools/migrate_to_supabase.py
# ถ้าย้ายไปเลย ข้อมูลสี่ตารางนั้นจะหายโดยไม่มีอะไรฟ้อง
# เทสต์นี้เทียบรายชื่อในตัวย้ายกับตารางจริงใน schema.sql
try:
    import re as _re
    _mig = (ROOT / "tools" / "migrate_to_supabase.py").read_text(encoding="utf-8")
    listed = set(_re.findall(r'"([a-z_]+)"',
                             _re.search(r"TABLES = \[(.*?)\]", _mig,
                                        _re.S).group(1)))
    real = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
        " AND name NOT LIKE 'sqlite_%'").fetchall()}
    check("ตัวย้ายข้อมูลครอบคลุมทุกตาราง", listed == real,
          f"ขาด {sorted(real - listed)} · เกิน {sorted(listed - real)}")
except Exception as e:
    check("อ่านรายชื่อตารางในตัวย้ายข้อมูล", False, f"{type(e).__name__}: {e}")

print("\nสคีมา SQLite กับ Postgres ต้องตรงกัน")
#
# มีไฟล์สคีมาสองไฟล์แล้ว (schema.sql ใช้ตอนเทสต์ · schema_pg.sql คือของจริง)
# ความเสี่ยงที่จะเกิดขึ้นแน่ๆ คือวันหลังเพิ่มคอลัมน์ในไฟล์เดียวแล้วลืมอีกไฟล์
# แล้วจะกลายเป็น "เทสต์ผ่านแต่ของจริงพัง" ซึ่งหาสาเหตุยากมาก
#
# ตรวจโดยดัดชนิดข้อมูลของฝั่ง Postgres ให้ SQLite อ่านได้ แล้วเอามาเทียบ
# ชื่อตารางกับชื่อคอลัมน์ ไม่ได้เทียบชนิดข้อมูล เพราะตั้งใจให้ต่างกัน
import re
import sqlite3


def schema_shape(sql_text, pg=False):
    if pg:
        sql_text = re.sub(r"BIGINT GENERATED BY DEFAULT AS IDENTITY",
                          "INTEGER", sql_text)
        sql_text = re.sub(r"numeric\(\d+,\s*\d+\)", "REAL", sql_text)
        sql_text = re.sub(r"\btimestamptz\b", "TEXT", sql_text)
        sql_text = re.sub(r"\bdate\b(?!_)", "TEXT", sql_text)
    mem = sqlite3.connect(":memory:")
    mem.executescript(sql_text)
    shape = {}
    for (name, kind) in mem.execute(
            "SELECT name, type FROM sqlite_master"
            " WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'"
            " ORDER BY name"):
        shape[name] = sorted(r[1] for r in mem.execute(
            f"PRAGMA table_info({name})"))
    mem.close()
    return shape


try:
    lite = schema_shape((ROOT / "schema.sql").read_text(encoding="utf-8"))
    pg = schema_shape((ROOT / "schema_pg.sql").read_text(encoding="utf-8"),
                      pg=True)
    check("มีตาราง/VIEW ชุดเดียวกัน", set(lite) == set(pg),
          f"ต่างกัน: {set(lite) ^ set(pg)}")
    for name in sorted(set(lite) & set(pg)):
        check(f"คอลัมน์ {name} ตรงกัน", lite[name] == pg[name],
              f"ต่างกัน: {set(lite[name]) ^ set(pg[name])}")
except Exception as e:
    check("อ่านสคีมาทั้งสองไฟล์", False, f"{type(e).__name__}: {e}")

print("\n/เที่ยว กองเที่ยว — ตัดสินตามกติกา เงินกองเที่ยวเท่านั้น")
#
# ล็อกวันเป็น 10 พ.ย. 2026 (วันที่ทำคำสั่งนี้) ไม่งั้นจำนวนเดือนที่เหลือ
# เปลี่ยนตามวันที่รันเทสต์ แล้วคำตอบ ไปได้/ไม่ได้ จะเปลี่ยนตาม
from datetime import date as _D                                   # noqa: E402

reset()
_real_now2 = db.now_th
db.now_th = lambda: _DT(2026, 11, 10, 14, 0, tzinfo=db.TH)
try:
    check("เดือน 6/70 = มิ.ย. 2027 (พ.ศ. สองหลัก)",
          bot.parse_trip_month("6/70", _D(2026, 11, 10)) == _D(2027, 6, 1))
    check("เดือน 6/27 = มิ.ย. 2027 (ค.ศ. สองหลัก)",
          bot.parse_trip_month("6/27", _D(2026, 11, 10)) == _D(2027, 6, 1))
    check("เดือน 2/2571 = ก.พ. 2028",
          bot.parse_trip_month("2/2571", _D(2026, 11, 10)) == _D(2028, 2, 1))
    check("เดือน 13/70 อ่านไม่ออก", bot.parse_trip_month("13/70", _D(2026, 11, 10)) is None)
    check("เดือนนี้ยังนับได้", bot.parse_trip_month("11/69", _D(2026, 11, 10)) == _D(2026, 11, 1))

    r = say("/เที่ยว 13925 32000 6/70")
    check("ยังไม่บอกยอด → ขอยอดก่อน ไม่เดา", "ยังไม่รู้ยอด" in r, r[:120])

    r = say("/เที่ยว 10,500")
    check("บันทึกยอดกอง (มีลูกน้ำได้)", db.get_state(conn, "trip_balance") == "10500.0", r[:120])
    check("โชว์คาดการณ์ยอดล่วงหน้า", "ถ้าเก็บตามนี้" in r and "14,000" in r, r[:300])

    # ปักกิ่ง ธ.ค. 69: เงินเข้าอีก 1 ครั้ง → 14,000 ไม่พองบ 24,000
    r = say("/เที่ยว 8080 24000 12/69")
    check("ปักกิ่งสิ้นปี = ไม่ไป", "❌ ไม่ไป" in r and "ขาด <b>10,000฿</b>" in r, r[:400])
    check("ปักกิ่ง: ค่าตั๋วจองได้ แต่ทั้งทริปไม่ได้", "✅ <b>ตอนจอง</b>" in r, r[:200])

    # ญี่ปุ่น มิ.ย. 70: ตอนไปพอ (35,000) แต่ตอนนี้ยังจ่ายค่าตั๋วไม่ได้
    r = say("/เที่ยว 13925 32000 6/2027")
    check("ญี่ปุ่น มิ.ย.: ตอนนี้ยังจองไม่ได้", "❌ <b>ตอนจอง</b>" in r, r[:300])
    check("ญี่ปุ่น มิ.ย.: บอกเดือนที่จองได้เร็วสุด", "จองได้เร็วสุดต้น ธ.ค.69" in r, r[:400])
    check("ตอนไปพอแต่ยังจองไม่ได้ = รอจอง ไม่ใช่ ไม่ไป",
          "⏳ ไปได้ แต่ยังจองตอนนี้ไม่ได้" in r and "❌ ไม่ไป" not in r, r[-400:])
    check("ญี่ปุ่น มิ.ย.: เหลือ 3,000 จากงบ 32,000 = เตือนเฉียดด้วย", "⚠️ และ" in r, r[-300:])

    # ตั๋วแพงเกินกว่าจะเก็บทันก่อนบิน = ไม่ไป
    r = say("/เที่ยว 30000 31000 12/69")
    check("ค่าตั๋วเก็บไม่ทันก่อนบิน = ไม่ไป", "❌ ไม่ไป" in r and "เก็บไม่ทัน" in r, r[-400:])

    r = say("/เที่ยว 8000 50000 2/71")
    check("ญี่ปุ่น ก.พ. 71 ตามแผนเดิม = ไปได้", "✅ ไปได้" in r and "63,000" in r, r[:400])
    r2 = say("/เที่ยว 50000 8000 2/71")
    check("ใส่ตั๋วกับงบสลับกัน ได้ผลเดียวกัน", r2 == r)

    # เหลือเผื่อไม่ถึง 10% = เฉียด
    r = say("/เที่ยว 5000 60000 2/71")
    check("เหลือเผื่อน้อย = ไปได้แต่เฉียด", "⚠️ ไปได้แต่เฉียด" in r, r[-300:])

    say("/เที่ยว เดือนละ 5000")
    check("เปลี่ยนยอดเก็บต่อเดือน", db.get_state(conn, "trip_monthly") == "5000.0")
    r = say("/เที่ยว 8080 24000 12/69")
    check("ใช้ยอดเก็บใหม่ในการคิด", "10,500 + 5,000 × 1" in r, r[:400])

    r = say("/เที่ยว 9000")
    check("ยอดลดลง → เตือนว่ามีการดึงเงินกอง", "ยอดลดลง" in r, r[:300])

    before = db.get_state(conn, "trip_balance")
    for bad in ("/เที่ยว nan", "/เที่ยว inf", "/เที่ยว 100 200 1/69",
                "/เที่ยว 100 200 6/70 7/70 x", "/เที่ยว -5", "/เที่ยว 0 0 6/70"):
        r = say(bad)
        check(f"รับค่าเพี้ยนไม่พัง ไม่แก้ยอด: {bad}",
              r and db.get_state(conn, "trip_balance") == before, r[:150])

    r = say("เที่ยว")
    check("พิมพ์ เที่ยว ไม่มี / → เตือน ไม่กลายเป็นออเดอร์",
          "ต้องมี / นำหน้า" in r and conn.execute("SELECT COUNT(*) FROM sale").fetchone()[0] == 0)
    say("/จ่าย 120 เที่ยว")
    check("/จ่าย 120 เที่ยว ยังเป็นรายจ่าย ไม่ใช่คำสั่งกองเที่ยว",
          conn.execute("SELECT COUNT(*) FROM spend").fetchone()[0] == 1)

    # ยอดที่อ่านไว้เดือนก่อน ยังไม่รวมเงินที่โอนเข้าวันที่ 1 เดือนนี้
    db.now_th = lambda: _DT(2026, 12, 3, 14, 0, tzinfo=db.TH)
    r = say("/เที่ยว")
    check("ยอดเก่าข้ามเดือน → เตือนให้อัปเดต", "ก่อนวันที่ 1 เดือนนี้" in r, r[:300])
finally:
    db.now_th = _real_now2

# ของตุนต้นเดือนต้องนับบูธแบบเดียวกับปลายเดือน
# 16 พ.ย. 2026 ต้นเดือนไม่นับบูธ ปลายเดือนนับ → บูธ 15,650 ที่จดไว้ตั้งแต่ ต.ค.
# ถูกนับเป็นกำไรจริงของ พ.ย. เกินมา ~1,475฿
reset()
_ms = "2026-11-01"
db.set_state(conn, "booth_tokens", 10000)
conn.execute("UPDATE app_state SET updated_at = '2026-10-20T00:00:00+07:00' "
             "WHERE key = 'booth_tokens'"); conn.commit()
check("บูธที่จดก่อนต้นเดือน นับเข้าของตุนต้นเดือน",
      abs(bot.stock_tokens_at(conn, _ms) - 9900) < 0.01, str(bot.stock_tokens_at(conn, _ms)))
conn.execute("UPDATE app_state SET updated_at = '2026-11-05T00:00:00+07:00' "
             "WHERE key = 'booth_tokens'"); conn.commit()
check("บูธที่จดระหว่างเดือน ไม่นับเข้าต้นเดือน (ไม่รู้ว่าต้นเดือนมีเท่าไหร่)",
      bot.stock_tokens_at(conn, _ms) == 0, str(bot.stock_tokens_at(conn, _ms)))
from datetime import date as _D                                  # noqa: E402
bot.save_month_stock(conn, _D(2026, 11, 16))
_saved = db.get_state(conn, "stock_tokens_2026-11")
db.set_state(conn, "booth_tokens", 50000)                        # จดบูธใหม่ทีหลัง
bot.save_month_stock(conn, _D(2026, 11, 20))
check("จดของตุนต้นเดือนครั้งเดียว ไม่เปลี่ยนตามบูธที่จดทีหลัง",
      _saved is not None and db.get_state(conn, "stock_tokens_2026-11") == _saved)

# ต้นทุนแบบ LIFO ตามกติกาเจ้าของ 16 พ.ย. 2026
# "ซื้อ 4,200 เรท 21 หมดแล้วใช้ 10.5 ที่ซื้อก่อนหน้า หมดอีกใช้ 10"
reset()
say("/ซื้อ 1000 100")        # เรท 10
say("/ซื้อ 1050 100")        # เรท 10.5
say("/ซื้อ 4200 200")        # เรท 21
say("400 5000")              # 4,200 @21 + 800 @10.5
s1 = conn.execute("SELECT * FROM v_sale ORDER BY id DESC LIMIT 1").fetchone()
check("LIFO: ใช้ชุดล่าสุดก่อน หมดแล้วต่อชุดก่อนหน้า",
      abs(float(s1["cost_baht"]) - (200 + 800 / 10.5)) < 0.05, str(s1["cost_baht"]))
say("100 500")               # เหลือ 250 @10.5 + 250 @10
s2 = conn.execute("SELECT * FROM v_sale ORDER BY id DESC LIMIT 1").fetchone()
check("LIFO: ชุด 10.5 หมดแล้วย้อนไปชุด 10",
      abs(float(s2["cost_baht"]) - (250 / 10.5 + 250 / 10)) < 0.05, str(s2["cost_baht"]))
check("LIFO: คิดซ้ำอีกรอบ ตัวเลขไม่ไหล", db.recost_sales(conn) == [])
check("LIFO: ต้นทุนรวมเท่าเงินที่จ่ายพอดีเมื่อใช้ Token หมด (ไม่นับเกิน/ขาด)",
      abs(sum(float(r["cost_baht"]) for r in conn.execute("SELECT cost_baht FROM v_sale"))
          - (200 + 800 / 10.5 + 250 / 10.5 + 250 / 10)) < 0.05)
say("/undo")
check("LIFO: ลบออเดอร์แล้ว ออเดอร์ก่อนหน้าไม่เปลี่ยน",
      abs(float(conn.execute("SELECT cost_baht FROM v_sale").fetchone()[0])
          - float(s1["cost_baht"])) < 0.01)

# ไม่ได้จด /ทัก = ถือว่าปิดได้ 100% (เจ้าของสั่ง 16 พ.ย. 2026)
reset()
db.insert_sale(conn, {"sold_on": "2026-11-10", "price_baht": 55, "tokens_spent": 500,
                      "token_rate": 11.0})
db.insert_sale(conn, {"sold_on": "2026-11-10", "price_baht": 60, "tokens_spent": 500,
                      "token_rate": 11.0})
db.mark_day(conn, "2026-11-11", shop_open=1, no_sale_reason="no_inquiry")
db.mark_day(conn, "2026-11-12", shop_open=0, no_sale_reason="not_open")
db.insert_sale(conn, {"sold_on": "2026-11-13", "price_baht": 55, "tokens_spent": 500,
                      "token_rate": 11.0})
db.fill_default_inquiries(conn, "2026-11-12")
_d = {r["log_date"]: r for r in conn.execute("SELECT * FROM v_day")}
check("ไม่ได้จดคนทัก → คนทัก = ออเดอร์ (ปิด 100%)",
      _d["2026-11-10"]["inquiries"] == 2 and _d["2026-11-10"]["close_rate_pct"] == 100)
check("วันไม่มีคนทัก → คนทัก 0", _d["2026-11-11"]["inquiries"] == 0)
check("วันปิดร้าน ไม่เดา", _d["2026-11-12"]["inquiries"] is None)
check("วันที่ยังไม่จบ ไม่เติม", _d["2026-11-13"]["inquiries"] is None)
check("ใส่ป้ายว่าบอทเติมเอง", db.AUTO_INQ_NOTE in (_d["2026-11-10"]["note"] or "")
      if "note" in _d["2026-11-10"].keys() else
      db.AUTO_INQ_NOTE in conn.execute("SELECT note FROM day_log WHERE log_date='2026-11-10'").fetchone()[0])
db.set_inquiries(conn, "2026-11-10", 5)
_r = conn.execute("SELECT inquiries, note FROM day_log WHERE log_date='2026-11-10'").fetchone()
check("/ทัก ทับค่าที่เติม และลบป้ายออก", _r["inquiries"] == 5 and not _r["note"], str(dict(_r)))

reset()
print("\n" + ("ผ่านหมด" if not fails else f"มีปัญหา {len(fails)} จุด: " + ", ".join(fails)))
sys.exit(1 if fails else 0)
