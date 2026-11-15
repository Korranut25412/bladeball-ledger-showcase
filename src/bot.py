"""
บอท Telegram สำหรับจดการขาย Blade Ball

ทำไมเขียนด้วย requests ตรงๆ ไม่ใช้ไลบรารีบอทสำเร็จรูป:
โค้ดทั้งหมดอ่านรู้เรื่องทีละบรรทัด ไม่มีอะไรทำงานลับหลัง
เจ้าของอ่านโค้ดออกอยู่แล้ว จะได้ตามทันและแก้เองได้ทีหลัง

วิธีทำงาน: วนถาม Telegram ว่ามีข้อความใหม่มั้ย (long polling)
ไม่ต้องมี public URL ไม่ต้อง deploy รันจากคอมที่บ้านได้เลย
"""

import html
import math
import os
import re
import sys
import time
import traceback
from datetime import date, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db
from parser import (parse_message, parse_line, describe, DEFAULT_RATE, ParseError,
                    strip_thousands)

ROOT = Path(__file__).resolve().parent.parent

# หน้าต่าง cmd ของ Windows ปริยายเป็น cp1252 ซึ่งพิมพ์ภาษาไทยไม่ได้ (โปรแกรมจะพัง)
# บรรทัดนี้บังคับให้ใช้ UTF-8 แทน
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

# ---------------------------------------------------------------- ตั้งค่า

def load_env() -> dict:
    """
    อ่านค่าตั้งจากไฟล์ .env แบบง่ายๆ ไม่ต้องลงแพ็กเกจเพิ่ม
    ถ้าไม่มีไฟล์ จะใช้ตัวแปรสภาพแวดล้อมแทน (ใช้ตอนรันเทสต์ หรือถ้าย้ายขึ้นคลาวด์)
    """
    env = dict(os.environ)
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


ENV = load_env()
BOT_TOKEN = ENV.get("BOT_TOKEN", "")
CHAT_ID = ENV.get("CHAT_ID", "").strip()
# สรุปตอนเที่ยงคืน เพราะช่วงที่ขายดีที่สุดคือ 1 ทุ่ม–4 ทุ่ม (เด็กเลิกเรียน)
# ถ้าตั้งไว้ก่อน 5 โมงเช้า บอทจะเข้าใจว่าให้สรุป "วันที่เพิ่งผ่านไป" ไม่ใช่วันปัจจุบัน
NIGHTLY_HOUR = int(ENV.get("NIGHTLY_HOUR", "0"))
MONTHLY_HOUR = int(ENV.get("MONTHLY_HOUR", "9"))

# เป้าหมายจากชีตแผนการเงิน
TARGET_DAY = float(ENV.get("TARGET_DAY", "290"))
TARGET_WEEK = float(ENV.get("TARGET_WEEK", "2030"))
TARGET_MONTH = float(ENV.get("TARGET_MONTH", "8800"))
KTB_FLOAT = float(ENV.get("KTB_FLOAT", "1000"))
MONTHLY_TRANSFER = float(ENV.get("MONTHLY_TRANSFER", "3828"))
MONTHLY_DCA = float(ENV.get("MONTHLY_DCA", "500"))
# เงินใช้ส่วนตัวที่ยืดหยุ่นได้จริง = 3,828 - ผ่อนมือถือ 748 - YouTube 80
PERSONAL_BUDGET = float(ENV.get("PERSONAL_BUDGET", "3000"))
# วันแรกที่เริ่มเก็บข้อมูล — วันก่อนหน้านี้ไม่นับว่า "ไม่ได้เปิดร้าน" เพราะยังไม่มีบอท
START_DATE = ENV.get("START_DATE", "2026-09-15")

# เรทที่ใช้ตีราคา Token ที่ยังกองอยู่ในเกม
#
# ใช้เรทที่ซื้อจากพ่อค้าได้ ไม่ใช่เรทเฉลี่ยถ่วงน้ำหนักจากทุกแหล่ง
# เหตุผล 2 ข้อ ซึ่งเจ้าของเป็นคนชี้ให้เห็นเอง 27 ก.ย. 2026
#
#   1) Token ที่กองอยู่มีค่าเท่ากับ "ถ้าไม่มีแล้วต้องไปซื้อเท่าไหร่"
#      ซึ่งคือเรทพ่อค้า  ส่วนเรทดีๆ จากของเหมาเป็นผลจากการไปหาของเอง
#      ไม่ใช่ราคาตลาดที่จะได้แน่นอนเมื่อไหร่ก็ได้
#
#   2) เรทเฉลี่ยถ่วงน้ำหนักต้องใช้ tokens_realised ของล็อตเหมา
#      ซึ่งมี 10 ล็อตที่เป็นค่าประมาณ และเคยนับซ้ำผิดมาแล้ว
#      เลขที่ไม่พึ่งข้อมูลเสีย ดีกว่าสูตรที่ถูกกว่าแต่กินข้อมูลเสียเข้าไป
#
# ยังคำนวณเรทเฉลี่ยไว้ให้ดูเทียบ แต่ไม่ได้เอามาคิดมูลค่า
#
# 15 ต.ค. 2026: เลิกใช้ 11 ตายตัว — stock_value() ไปตามเรทพ่อค้าครั้งล่าสุดแทน
# (ต.ค. พ่อค้าขึ้นเป็น 10.2 ถ้ายังใช้ 11 มูลค่าของตุนจะต่ำกว่าจริง ~8%)
# ค่านี้เหลือไว้ใช้ตอนยังไม่เคยจดซื้อ Token เลยสักครั้งเท่านั้น
# ชนกันติดกันกี่รอบถึงจะเตือน (รอบละ 5 วินาที)
# ตั้ง 6 = 30 วินาที ซึ่งนานพอให้ deploy ทับกันหายไปเองก่อน
CONFLICT_BEFORE_WARN = 6

STOCK_RATE = float(ENV.get("STOCK_RATE", "11"))
if not 1 <= STOCK_RATE <= 100:
    # ค่านี้เป็นตัวหาร ถ้าเป็น 0 บอทจะพังทุกคำสั่งที่แสดงมูลค่าของตุน
    # และถ้าติดลบ มูลค่าของที่ตุนไว้จะกลายเป็นติดลบโดยไม่มีอะไรฟ้อง
    # พิมพ์ผิดใน .env ทีเดียวแล้วบอทใช้ไม่ได้ทั้งตัว จึงต้องกันไว้ตรงนี้
    print(f"⚠️  STOCK_RATE={STOCK_RATE} ใช้ไม่ได้ (ต้องอยู่ระหว่าง 1-100) "
          f"→ ใช้ {DEFAULT_RATE} แทน")
    STOCK_RATE = DEFAULT_RATE

if not BOT_TOKEN:
    sys.exit("ยังไม่ได้ใส่ BOT_TOKEN — ก๊อป .env.example เป็น .env "
             "แล้วเอา token จาก @BotFather มาวาง")

API = f"https://api.telegram.org/bot{BOT_TOKEN}"

TH_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
             "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]

# ค่าธรรมเนียมบูธตอนตั้งขายไอเทม — วัดจากในเกมจริง
#   ตั้ง 17 ได้ 16 · ตั้ง 20 ได้ 19 · ตั้ง 40,000 ได้ 39,600
# ทั้งสามเคสตรงกับสูตร floor(ราคาที่ตั้ง x 0.99) พอดี
BOOTH_FEE = 0.01


def booth_net(listing_price: int) -> int:
    """ตั้งขายราคานี้ จะได้ Token กลับมาเท่าไหร่"""
    return math.floor(listing_price * (1 - BOOTH_FEE))


def booth_list_price(want: int) -> int:
    """อยากได้ Token กลับมาเท่านี้ ต้องตั้งขายเท่าไหร่ (น้อยที่สุด)"""
    return math.ceil(want / (1 - BOOTH_FEE))


def set_rate(conn, rate: float, source: str) -> bool:
    """
    ตั้งเรทที่จะใช้กับรายการขายต่อไป

    ต้องกันไม่ให้ค่าประหลาดหลุดเข้ามา เพราะเรทเป็นตัวหาร
    ถ้าเผลอตั้งเป็น 0 หรือติดลบ รายการขายทุกอันหลังจากนั้นจะเพี้ยนหมด
    """
    from parser import RATE_MIN, RATE_MAX
    if not (RATE_MIN <= rate <= RATE_MAX):
        return False
    db.set_state(conn, "current_rate", round(rate, 4))
    db.set_state(conn, "current_rate_src", source)
    return True


def merchant_rate(conn) -> float:
    """
    เรทซื้อ Token จากพ่อค้าครั้งล่าสุด = ถ้าวันนี้ไม่มีของเหมาเลย ต้องจ่ายเท่าไหร่

    ใช้เป็นเส้นเทียบว่าดีลเหมาคุ้มมั้ย และใช้ตีมูลค่า Token ที่ตุนไว้
    เดิมเทียบกับเลข 11 ตายตัว พอ ต.ค. 2026 พ่อค้าขึ้นราคาเป็น 10.2
    บอทเลยบอกว่าดีลเหมา "ดีกว่าเรท 11 อยู่ 1.17 เท่า" ทั้งที่จริงดีกว่า 1.26 เท่า
    — เลขตายตัวจะผิดทุกครั้งที่ตลาดขยับ ต้องตามเรทที่ซื้อจริงล่าสุด

    current_rate ถูกตั้งเฉพาะตอน /ซื้อ Token เท่านั้น (ไม่ตั้งตอน /เหมา)
    จึงเป็นเรทพ่อค้าเสมอ ไม่โดนเรทสูงๆ ของของเหมาปนเข้ามา
    """
    return db.current_rate(conn, DEFAULT_RATE)


DAY_WORDS = {"เมื่อวาน", "มว", "y", "ytd"}

REASON_LABELS = {
    "not_open": "ไม่ได้เปิดร้าน",
    "no_inquiry": "เปิดแต่ไม่มีคนทัก",
    "no_close": "มีคนทักแต่ปิดไม่ได้",
    "forgot": "ขายได้แต่ลืมจด",
}


# ---------------------------------------------------------------- Telegram API

def api(method: str, **params):
    r = requests.post(f"{API}/{method}", json=params, timeout=40)
    data = r.json()
    if not data.get("ok"):
        print(f"[telegram] {method} ล้มเหลว: {data}")
    return data


TG_MAX_CHARS = 4000   # Telegram จำกัด 4096 เผื่อไว้หน่อย


def _split_message(text: str):
    """
    ตัดข้อความยาวเป็นหลายก้อน โดยพยายามตัดตรงรอยขึ้นบรรทัด
    จำเป็นเพราะถ้าจดรวดเดียว 40-50 รายการ คำตอบจะยาวเกินที่ Telegram รับได้
    แล้วข้อความจะหายไปทั้งก้อนโดยไม่มีอะไรเตือน
    """
    if len(text) <= TG_MAX_CHARS:
        return [text]
    chunks, current = [], ""
    for line in text.split("\n"):
        # บรรทัดเดียวที่ยาวเกินก้อน ต้องหั่นดิบๆ
        while len(line) > TG_MAX_CHARS:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:TG_MAX_CHARS])
            line = line[TG_MAX_CHARS:]
        if len(current) + len(line) + 1 > TG_MAX_CHARS:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


def send(chat_id, text, buttons=None):
    result = None
    parts = _split_message(text)
    for i, part in enumerate(parts):
        params = {"chat_id": chat_id, "text": part, "parse_mode": "HTML",
                  "disable_web_page_preview": True}
        # ปุ่มติดไปกับก้อนสุดท้ายเท่านั้น
        if buttons and i == len(parts) - 1:
            params["reply_markup"] = {"inline_keyboard": buttons}
        result = api("sendMessage", **params)
    return result


def push(text, buttons=None):
    """ส่งหาเจ้าของ (ใช้กับข้อความสรุปตามเวลา)"""
    if not CHAT_ID:
        print("[push] ยังไม่ได้ตั้ง CHAT_ID ใน .env — ข้ามการแจ้งเตือน")
        return
    send(CHAT_ID, text, buttons)


def _to_float(text):
    try:
        return float(text)
    except ValueError:
        return None


def fmt_date(date_str: str) -> str:
    y, m, d = (int(x) for x in date_str.split("-"))
    return f"{d} {TH_MONTHS[m - 1]}"


def bar(value, target, width=10):
    """
    แถบความคืบหน้า + ตัวเลข %

    เดิมใช้ █ กับ ░ แต่ฟอนต์ใน Telegram แสดงสองตัวนี้ใกล้กันมาก
    มองเป็นแท่งดำทึบก้อนเดียว อ่านไม่ออกว่าไปถึงไหนแล้ว
    """
    if target <= 0:
        return ""
    pct = value / target
    filled = max(0, min(width, round(width * pct)))
    return "●" * filled + "○" * (width - filled) + f"  {pct * 100:.0f}%"


def days_counted(start: str, end: str) -> int:
    """
    จำนวนวันในช่วงนี้ที่ระบบเก็บข้อมูลจริง
    ไม่นับวันก่อนเริ่มใช้บอท และไม่นับวันที่ยังมาไม่ถึง
    """
    a = max(date.fromisoformat(start), date.fromisoformat(START_DATE))
    b = min(date.fromisoformat(end), db.now_th().date())
    return max(0, (b - a).days + 1)


# ---------------------------------------------------------------- ข้อความสรุป

def text_today(conn, date_str=None) -> str:
    date_str = date_str or db.today_th()
    s = db.day_summary(conn, date_str)
    lines = [f"<b>{fmt_date(date_str)}</b>"]

    if s["orders"] == 0:
        reason = REASON_LABELS.get(s["no_sale_reason"] or "", None)
        lines.append("ยังไม่มีการขาย" + (f" · {reason}" if reason else ""))
    else:
        lines.append(f"ขาย {s['orders']} ครั้ง · รับเงิน {s['revenue_baht']:,.0f}฿ "
                     f"· ทุน {s['cost_baht']:,.0f}฿")
        lines.append(f"<b>กำไร {s['profit_baht']:,.0f}฿</b> / เป้า {TARGET_DAY:,.0f}฿  "
                     f"{bar(s['profit_baht'], TARGET_DAY)}")
        if s["profit_baht"] < TARGET_DAY:
            lines.append(f"ขาดอีก {TARGET_DAY - s['profit_baht']:,.0f}฿")
        else:
            lines.append(f"เกินเป้า {s['profit_baht'] - TARGET_DAY:,.0f}฿ 🎉")
        lines.append(f"ใช้ Token ไป {s['tokens_spent']:,}")

    if s.get("inquiries"):
        rate = s.get("close_rate_pct")
        # ออเดอร์มากกว่าคนทัก = มีคนซื้อหลายออเดอร์ (กติกานับ /ทัก นับคน ไม่นับออเดอร์)
        # เดิมโชว์ "ปิดได้ 125%" ซึ่งเป็นไปไม่ได้ (30 ก.ย. 2026 · 4 คน 5 ออเดอร์)
        # อัตราปิดจริงต้องใช้จำนวนคนที่ซื้อ ซึ่งบอทไม่รู้ จึงไม่แสดง % แทนการโชว์เลขผิด
        if rate is not None and rate > 100:
            lines.append(f"คนทัก {s['inquiries']} คน · ซื้อ {s['orders']} ออเดอร์ "
                         "<i>(มีคนซื้อหลายรอบ)</i>")
        else:
            lines.append(f"คนทัก {s['inquiries']} คน"
                         + (f" · ปิดได้ {rate}%" if rate is not None else ""))
    return "\n".join(lines)


def week_bounds(date_str=None):
    """ขอบเขตสัปดาห์แบบ จันทร์–อาทิตย์"""
    d = date.fromisoformat(date_str) if date_str else db.now_th().date()
    start = d - timedelta(days=d.weekday())
    return start.isoformat(), (start + timedelta(days=6)).isoformat()


def month_bounds(offset_months=0):
    """ต้นเดือน–ปลายเดือน · offset -1 = เดือนที่แล้ว"""
    d = db.now_th().date().replace(day=1)
    for _ in range(abs(offset_months)):
        if offset_months < 0:
            d = (d - timedelta(days=1)).replace(day=1)
        else:
            d = (d + timedelta(days=32)).replace(day=1)
    end = (d + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    return d.isoformat(), end.isoformat()


def text_week(conn, date_str=None) -> str:
    start, end = week_bounds(date_str)
    s = db.range_summary(conn, start, end)
    lines = [f"<b>สัปดาห์นี้</b> ({fmt_date(start)} – {fmt_date(end)})",
             f"ขาย {s['orders']} ครั้ง · กำไร <b>{s['profit_baht']:,.0f}฿</b> "
             f"/ เป้า {TARGET_WEEK:,.0f}฿",
             bar(s["profit_baht"], TARGET_WEEK)]
    gap = TARGET_WEEK - s["profit_baht"]
    lines.append(f"ขาดอีก {gap:,.0f}฿" if gap > 0 else f"ถึงเป้าแล้ว เกิน {-gap:,.0f}฿ 🎉")
    n = days_counted(start, end)
    lines.append(f"เปิดร้าน {s['open_days']} / {n} วันที่เก็บข้อมูล "
                 f"· ขายได้ {s['selling_days']} วัน")
    if s["selling_days"]:
        lines.append(f"วันที่ขายได้ ทำกำไรเฉลี่ย {s['profit_baht'] / s['selling_days']:,.0f}฿")
    return "\n".join(lines)


def text_month(conn) -> str:
    start, end = month_bounds()
    s = db.range_summary(conn, start, end)
    days_left = (date.fromisoformat(end) - db.now_th().date()).days + 1

    lines = [f"<b>เดือน {TH_MONTHS[int(start[5:7]) - 1]}</b>",
             f"ขาย {s['orders']} ครั้ง · กำไร <b>{s['profit_baht']:,.0f}฿</b> "
             f"/ เป้า {TARGET_MONTH:,.0f}฿",
             bar(s["profit_baht"], TARGET_MONTH)]
    gap = TARGET_MONTH - s["profit_baht"]
    if gap > 0:
        lines.append(f"ขาดอีก {gap:,.0f}฿ · เหลือ {days_left} วัน "
                     f"→ ต้องได้วันละ {gap / max(days_left, 1):,.0f}฿")
    else:
        lines.append(f"ถึงเป้าแล้ว เกิน {-gap:,.0f}฿ 🎉")
    n = days_counted(start, end)
    lines.append(f"เปิดร้าน {s['open_days']} / {n} วันที่เก็บข้อมูล "
                 f"· ขายได้ {s['selling_days']} วัน")

    zero = db.zero_day_breakdown(conn, start, end)
    if zero:
        lines.append("\n<b>วันที่ไม่ได้เงิน</b>")
        for row in zero:
            label = REASON_LABELS.get(row["reason"], row["reason"])
            lines.append(f"· {label}: {row['days']} วัน")
    return "\n".join(lines)


def text_band(conn) -> str:
    """กำไรแยกตามช่วงราคา Token — ตอบว่าของถูกหรือของแพงคุ้มกว่า"""
    start, end = month_bounds()
    rows = db.band_breakdown(conn, start, end)
    if not rows:
        return "ยังไม่มีข้อมูลพอในเดือนนี้"

    out = ["<b>กำไรแยกตามช่วงราคา Token</b> (เดือนนี้)", "<pre>",
           "ช่วง Token      ครั้ง  กำไร/ครั้ง  กำไร/Token  เท่า"]
    for r in rows:
        out.append(f"{r['token_band']:<14} {r['orders']:>4}  "
                   f"{r['avg_profit']:>9,.0f}฿  {r['avg_profit_per_token']:>10.3f}  "
                   f"{r['avg_markup_x']:>4.1f}x")
    out.append("</pre>")
    out.append("อ่านยังไง: <b>กำไร/ครั้ง</b> สูง = คุ้มเวลา · "
               "<b>กำไร/Token</b> สูง = คุ้มเงินทุน")
    return "\n".join(out)


HELP = """<b>วิธีจด</b> — พิมพ์บรรทัดเดียวจบ ส่งทีละหลายบรรทัดได้

<code>55 192</code>
ได้เงิน 55฿ · กดของจากบูธไป 192 Token
⚠️ <b>ใส่ราคาที่กดจากบูธ ไม่ใช่ Your Value ในหน้าต่าง Trade</b>
Your Value คือ RAP ของที่ส่ง ซึ่งมักต่ำกว่าที่จ่ายจริง 2-4%

<code>55 192 10.5</code>
ระบุเรทเฉพาะบรรทัดนี้

<code>150 565 x3</code>
ออเดอร์นี้มี 3 ชิ้น

<code>เมื่อวาน 55 192</code>
ลงย้อนหลัง — ใช้ตอนขายดึกหลังเที่ยงคืนไปแล้ว

<code>100 300 ทรู</code>
เงินเข้าบัญชีอื่น — ไม่ใส่ = กรุงไทย
<i>ktb · ทรู · kbank · dime · สด</i>

<b>ขายโท / กิฟพาส / สุ่มสปิน ใช้แบบเดียวกัน</b>
<code>55 500</code> = ได้เงิน 55฿ ส่ง Token ออกไป 500
เงินเข้า Token ออก เหมือนขายไอเทมทุกอย่าง
<i>อยากแยกทีหลังก็ใส่หมายเหตุ</i> <code>55 500 #ขายโท</code>

<b>⭐ ของเข้าร้าน — บันทึกครั้งเดียว ใช้ทั้งคืน</b>

<code>/ซื้อ 700 63</code>
ซื้อ Token จากพ่อค้า 63฿ ได้ 700 Token → เรท 11.1
ได้ Token มาเลย เอาไปกดของได้ทันที

<code>/เหมา 2297 130 7</code>
รับเหมา 130฿ ได้ของ 7 ชิ้น RAP รวม 2,297 → เรท 17.7
<b>ของเหมายังไม่ใช่ Token</b> ต้องตั้งบูธย่อยขายก่อน Token ถึงเข้าตัว

<code>/ตั้ง 670</code>
ของ RAP 670 ต้องตั้งขายที่บูธเท่าไหร่ถึงได้ทุนคืนครบ
(บูธกิน 1% ปัดลง — ตั้งเท่า RAP เป๊ะจะขาดทุน)

<b>⭐ ก่อนนอน นับของในเกม</b>
<code>/นับ 3780 1660 639 620 600</code>
Token ในไอดี ตามด้วยราคาของในบูธทุกชิ้น (บูธว่างพิมพ์ <code>/นับ 3780 0</code>)
บอทบอกว่าตรงกับที่จดมั้ย · ของเหมาย่อยออกแล้วหรือยังไม่ต้องจำ นับเจอเองทั้งสองที่

<code>/โทเข้า 670 #ขายปืนที่บูธ</code>
<code>/โทออก 46 #ของลูกค้าเก่า</code>
Token เข้า-ออกที่ไม่ใช่การซื้อขายปกติ

ทั้งสองคำสั่งจะ<b>ตั้งเรทที่ใช้อยู่</b>ให้เอง
รายการขายหลังจากนั้นพิมพ์แค่ <code>55 192</code> ก็พอ

ถ้าอยากใส่เรทเฉพาะบรรทัด: <code>55 192 10.5</code>
หรือเขียนเป็นเศษส่วน: <code>55 192 700/63</code>

<b>ตัวเลือกที่ใส่ได้</b> (สลับลำดับได้)
จำนวนชิ้น: <code>x3</code>
รับเหมา: <code>เหมา</code> (ใส่เรทเป็นเศษส่วนก็ติดให้อัตโนมัติ)
หมายเหตุ: <code>#Dual Hacker Scythe</code>

<b>เงินส่วนตัว</b> — คนละก้อนกับธุรกิจ ไม่ปนกับกำไร
<code>/จ่าย 50 ข้าว</code>
<code>/จ่าย 50 ข้าว 120 เที่ยว 60 รถ</code>
<code>/กรุงไทย 1496</code> บอกยอดบัญชีการค้า → เก็บได้แล้วเท่าไหร่
<code>/เหลือ 1024</code> บอกยอด K-eSavings → ใช้ได้วันละเท่าไหร่
<code>/ส่วนตัว</code> สรุปเดือนนี้ เทียบงบ 3,000
<code>/เที่ยว 13925 32000 6/70</code> ทริปนี้ไปได้มั้ย ตามกติกากองเที่ยว

<b>คำสั่ง</b>
/ซื้อ 700 63 ซื้อ Token · /เหมา 2297 130 7 รับเหมา
/ตั้ง 670 ตั้งขายที่บูธเท่าไหร่
/นับ 3780 1660 639 นับ Token ในไอดี + ราคาของในบูธ ทีเดียวจบ
/โทเข้า 670 · /โทออก 46 · /ยกมา 200
/today วันนี้ · /yesterday เมื่อวาน
/week สัปดาห์นี้ · /month เดือนนี้
/band กำไรแยกตามช่วงราคา Token
/rate 2297 130 คิดเรทให้ดูเฉยๆ ก่อนตัดสินใจซื้อ (ไม่บันทึก)
/inq 5 วันนี้มีคนทัก 5 คน
/close ระบุว่าวันนี้ทำไมไม่ได้เงิน
/รายการ ดู 10 อันล่าสุด · /แก้ 12 170 859 แก้รายการเก่า
/ทุน มูลค่ากิจการ (เงินสด + Token + ของในบูธ)
/สุขภาพ เช็กว่าข้อมูลเดือนนี้น่าเชื่อถือแค่ไหน
/undo ลบรายการล่าสุด"""


# ---------------------------------------------------------------- รับข้อความ

def reason_buttons(date_str):
    return [[{"text": REASON_LABELS["not_open"], "callback_data": f"r|{date_str}|not_open"}],
            [{"text": REASON_LABELS["no_inquiry"], "callback_data": f"r|{date_str}|no_inquiry"}],
            [{"text": REASON_LABELS["no_close"], "callback_data": f"r|{date_str}|no_close"}],
            [{"text": REASON_LABELS["forgot"], "callback_data": f"r|{date_str}|forgot"}]]


def parser_rate_ok(rate: float, is_lot: bool = False) -> bool:
    from parser import RATE_MIN, RATE_MAX, LOT_RATE_MAX
    return RATE_MIN <= rate <= (LOT_RATE_MAX if is_lot else RATE_MAX)


def business_day(now=None) -> str:
    """
    "วันทำการ" ที่คำสั่งอย่าง /close และ /inq หมายถึง

    ช่วงขายดีคือ 1 ทุ่ม–4 ทุ่ม แล้วมักจดตอนเที่ยงคืน
    ถ้าพิมพ์ /close ตอนตี 1 แปลว่าหมายถึงวันที่เพิ่งจบ ไม่ใช่วันใหม่ที่เพิ่งเริ่ม
    """
    now = now or db.now_th()
    d = now.date()
    return (d - timedelta(days=1)).isoformat() if now.hour < 5 else d.isoformat()


# ชื่อคำสั่งทั้งหมด ใช้ตอนเตือนว่าลืมใส่ /
COMMAND_WORDS = {
    "start", "help", "ช่วย", "today", "วันนี้", "yesterday", "เมื่อวาน",
    "buy", "ซื้อ", "เหมา", "lot", "split", "ย่อย", "list", "ตั้ง",
    "rate", "เรท", "week", "สัปดาห์", "month", "เดือน", "band", "ช่วง",
    "close", "ปิดวัน", "inq", "ทัก", "undo", "ยกเลิก",
    "tokenin", "โทเข้า", "tokenout", "โทออก", "open", "ยกมา",
    "check", "เช็ค", "นับ",
    "spend", "จ่าย", "ใช้", "balance", "เหลือ", "personal", "ส่วนตัว",
    "ktb", "กรุงไทย", "บัญชี", "list_sales", "รายการ", "ดู",
    "edit", "แก้", "health", "สุขภาพ", "ตรวจ",
    "booth", "บูธ", "capital", "ทุน", "มูลค่า",
    "transfer", "โอน", "ย้าย", "trueprofit", "กำไรจริง", "กำไร",
    "snapshot", "ยกยอด", "ยอดเงิน",
    "pending", "ค้าง", "ค้างส่ง", "delivered", "ส่งแล้ว",
    "refund", "คืนเงิน", "forfeit", "ตัดหนี้",
    "expense", "ค่าใช้จ่าย", "ค่าธรรมเนียม",
    "trip", "เที่ยว", "ทริป",
}


# คำสั่งที่รับรายการตัวเลขยาวๆ — บรรทัดตัวเลขที่ตามมาเป็นของคำสั่งนี้ ไม่ใช่บรรทัดขาย
LIST_COMMANDS = {"นับ", "บูธ", "booth"}


def _merge_list_lines(lines):
    """
    ต่อบรรทัดตัวเลขที่ตามหลัง /นับ หรือ /บูธ เข้าไปในคำสั่งนั้น

    พิมพ์ราคาในบูธ 16 ชิ้นบนมือถือ กด Enter ขึ้นบรรทัดใหม่เป็นเรื่องปกติ
        /นับ 3780 1660 639
        620 600 595
    เดิมบรรทัดสองกลายเป็นบรรทัดขาย "ได้ 620 บาท ใช้ 600 Token" ← ออเดอร์ปลอม
    เงินในบอทเกินจริงทันทีโดยไม่มีอะไรเตือน

    ต่อบรรทัดที่ทุกคำมีตัวเลขอยู่ และหยุดทันทีที่เจอคำสั่ง / ตัวถัดไป
    ที่ไม่บังคับตัวเลขล้วน เพราะ "620 600 5OO" (โอใหญ่) ถ้าไม่ต่อ จะกลายเป็น
    ออเดอร์ 620 บาทที่มีหมายเหตุ "5OO" — ต่อเข้าไปแล้ว /นับ จะปฏิเสธทั้งก้อนแทน
    """
    def numberish(line):
        return all(any(ch.isdigit() for ch in w) for w in line.split())

    out = []
    for line in lines:
        s = line.strip()
        prev = out[-1].strip() if out else ""
        prev_cmd = prev.split()[0].lstrip("/").split("@")[0].lower() if prev.startswith("/") else ""
        if prev_cmd in LIST_COMMANDS and not s.startswith("/") and numberish(s):
            out[-1] = prev + " " + s
        else:
            out.append(line)
    return out


def handle_text(conn, chat_id, text):
    # "8,340" → "8340" ตรงนี้ที่เดียว ทุกคำสั่งกับบรรทัดขายได้ประโยชน์หมด
    # ไม่ต้องไปแก้ทีละจุดที่อ่านตัวเลข (มี isdigit / _to_float กระจายอยู่ 20 กว่าที่)
    text = strip_thousands(text)
    words = text.strip().split()
    if not words:
        return send(chat_id, "ส่งข้อความว่างมาครับ · พิมพ์ /help ดูวิธีใช้")

    # ข้อความหลายบรรทัดที่มีคำสั่งปนอยู่ ต้องแยกทำทีละก้อน
    # เดิมอ่านแค่บรรทัดแรกแล้วทิ้งที่เหลือเงียบๆ — ส่ง "/กรุงไทย 1699"
    # กับ "/เช็ค 2441" พร้อมกัน แล้วอันที่สองหายไปโดยไม่มีอะไรเตือน
    lines = _merge_list_lines([l for l in text.splitlines() if l.strip()])
    if len(lines) == 1 and lines[0].lstrip().startswith("/"):
        text = lines[0]
        words = text.strip().split()
    if len(lines) > 1 and any(l.lstrip().startswith("/") for l in lines):
        batch = []          # บรรทัดขายที่ติดกัน รวมส่งทีเดียวเหมือนเดิม
        for line in lines:
            if line.lstrip().startswith("/"):
                if batch:
                    handle_sale_lines(conn, chat_id, "\n".join(batch))
                    batch = []
                handle_text(conn, chat_id, line)
            else:
                batch.append(line)
        if batch:
            handle_sale_lines(conn, chat_id, "\n".join(batch))
        return None

    # คำสั่งต้องขึ้นต้นด้วย / เสมอ
    # ถ้าไม่บังคับ บรรทัดขายที่ขึ้นต้นด้วย "เมื่อวาน 80 300" จะถูกมองเป็น
    # คำสั่ง /yesterday แล้วยอดขายหายไปเงียบๆ
    if not text.strip().startswith("/"):
        if words[0].lower() in COMMAND_WORDS and len(words) == 1:
            return send(chat_id, f"ถ้าจะใช้คำสั่ง ต้องมี / นำหน้า → "
                                 f"<code>/{words[0]}</code>")
        return handle_sale_lines(conn, chat_id, text)

    cmd = words[0].lower().lstrip("/").split("@")[0]

    if cmd in ("start", "help", "ช่วย"):
        return send(chat_id, HELP)
    if cmd in ("today", "วันนี้"):
        return send(chat_id, text_today(conn))
    if cmd in ("yesterday", "เมื่อวาน"):
        return send(chat_id, text_today(
            conn, (db.now_th().date() - timedelta(days=1)).isoformat()))
    if cmd in ("buy", "ซื้อ", "เหมา", "lot"):
        return handle_purchase(conn, chat_id, text, cmd)

    if cmd in ("split", "ย่อย"):
        # ระบุล็อตได้ด้วย #4 เพราะล็อตเก่าอาจยังขายไม่หมดตอนรับล็อตใหม่มา
        # ถ้าไม่ระบุจะใช้ล็อตล่าสุดเหมือนเดิม
        parts = [w for w in text.split() if not re.fullmatch(r"#\d+", w)]
        target = next((int(w[1:]) for w in text.split() if re.fullmatch(r"#\d+", w)), None)
        lot = db.purchase_by_id(conn, target) if target else db.latest_lot(conn)
        if lot is None or lot["kind"] != "lot":
            return send(chat_id,
                        f"ไม่มีล็อตเหมา #{target}" if target else
                        "ยังไม่มีล็อตเหมาในระบบ · บันทึกด้วย "
                        "<code>/เหมา 2297 130</code> ก่อน")
        got = _to_float(parts[1].lstrip("=")) if len(parts) > 1 else None
        if got is None or got <= 0:
            msg = (f"ล็อตล่าสุด #{lot['id']} · จ่าย {lot['baht']:,.0f}฿ "
                   f"RAP รวม {lot['rap_total']:,}\n"
                   "ย่อยขายที่บูธได้กี่ Token? <code>/ย่อย 1800</code>")
            if got is not None:
                msg = "จำนวน Token ต้องมากกว่า 0 ครับ\n\n" + msg
            return send(chat_id, msg)
        # /ย่อย = "ขายได้เพิ่มอีกเท่าไหร่" บวกสะสมให้เอง
        # เดิมออกแบบให้ใส่ยอดสะสม แล้วเจ้าของใส่เป็นยอดครั้งล่าสุดตามสัญชาตญาณ
        # ทำให้ยอดเก่าถูกทับและ Token ในระบบลดลงทั้งที่ควรเพิ่ม
        # ถ้าจะแก้ยอดสะสมทั้งก้อน ใช้ /ย่อย =977
        absolute = parts[1].startswith("=")
        added = int(got)
        before = lot["tokens_realised"] or 0
        total = added if absolute else before + added
        db.set_lot_realised(conn, lot["id"], total)
        lot = db.purchase_by_id(conn, lot["id"])
        # ไม่ตั้งเรทที่ใช้อยู่จากล็อตเหมา เพราะ Token ที่ได้จะไปปนกับ Token
        # ที่ซื้อมาเรทปกติในกระเป๋าเดียวกัน ถ้าเอาเรท 49 มาใช้กับทุกรายการ
        # ทุนจะต่ำกว่าจริงหลายเท่า · ถ้าขายของจากล็อตนี้ตรงๆ ให้ใส่เรทในบรรทัดเอง
        sold = lot["sold_through_pct"]
        verdict = ("ขายหมดแล้ว" if sold >= 99 else
                   f"ยังเหลือของค้างอีกราว {100 - sold:.0f}%")
        change = f"ตั้งยอดสะสมเป็น {total:,}" if absolute else f"ครั้งนี้ +{added:,}"
        return send(chat_id,
                    f"ล็อต #{lot['id']} · จ่าย {lot['baht']:,.0f}฿\n"
                    f"{change} · ย่อยได้แล้วรวม <b>{total:,}</b> Token\n"
                    f"เรทจริงถึงตอนนี้ <b>{lot['rate_actual']:.2f}</b> "
                    f"({verdict})\n\n"
                    f"<i>ถ้าขายของจากล็อตนี้ให้ลูกค้าตรงๆ ใส่เรทในบรรทัดเป็น</i> "
                    f"<code>{lot['rap_total']}/{lot['baht']:.0f}</code>")

    if cmd in ("tokenin", "โทเข้า", "tokenout", "โทออก", "open", "ยกมา"):
        return handle_token_move(conn, chat_id, text, cmd, words)

    if cmd in ("spend", "จ่าย", "ใช้"):
        return handle_spend(conn, chat_id, text, words)

    if cmd in ("list_sales", "รายการ", "ดู"):
        rows = db.recent_sales(conn, 10)
        if not rows:
            return send(chat_id, "ยังไม่มีรายการขาย")
        lines = ["<b>10 รายการล่าสุด</b>"]
        for r in rows:
            tag = f" · {html.escape(r['note'][:18])}" if r["note"] else ""
            lines.append(f"<code>#{r['id']}</code> {fmt_date(r['sold_on'])} · "
                         f"{r['price_baht']:,.0f}฿ · {r['tokens_spent']:,} Token "
                         f"· กำไร {r['profit_baht']:,.0f}฿{tag}")
        lines.append("\n<i>แก้ได้ด้วย</i> <code>/แก้ 12 170 859</code>")
        return send(chat_id, "\n".join(lines))

    if cmd in ("edit", "แก้"):
        parts = text.split(None, 2)
        if len(parts) < 3 or not parts[1].lstrip("#").isdigit():
            return send(chat_id, "ใช้แบบนี้: <code>/แก้ 12 170 859</code>\n"
                                 "<i>เลขหลัง /แก้ คือเลขรายการ ดูได้จาก</i> "
                                 "<code>/รายการ</code>")
        sale_id = int(parts[1].lstrip("#"))
        old = db.sale_by_id(conn, sale_id)
        if old is None:
            return send(chat_id, f"ไม่มีรายการ #{sale_id}")
        try:
            new = parse_line(parts[2], db.now_th().date(),
                             db.current_rate(conn, DEFAULT_RATE))
        except ParseError as e:
            return send(chat_id, f"อ่านไม่ออก: {e}")
        # ไม่ได้พิมพ์เรทมา = ตั้งใจแก้แค่ราคา/Token ต้องใช้เรทเดิมของออเดอร์นั้น
        # เดิมไปหยิบเรทปัจจุบันมาใช้ — แก้ออเดอร์ 19 ก.ย. (เรท 11.006) ตอนเรทเป็น 10.0
        # ต้นทุนจะเปลี่ยนเงียบๆ ทั้งที่ไม่ได้ตั้งใจแตะเรทเลย
        if new["rate_from_default"]:
            new["token_rate"] = old["token_rate"]
            new["source"] = old["source"]
        # ไม่ได้พิมพ์ #หมายเหตุ มา = เก็บของเดิมไว้ ไม่ใช่ลบทิ้ง
        if new["note"] is None:
            new["note"] = old["note"]
        db.update_sale(conn, sale_id, new)
        row = db.sale_by_id(conn, sale_id)
        return send(chat_id,
                    f"<b>แก้รายการ #{sale_id} แล้ว</b>\n"
                    f"เดิม {old['price_baht']:,.0f}฿ · {old['tokens_spent']:,} Token "
                    f"· กำไร {old['profit_baht']:,.0f}฿\n"
                    f"ใหม่ {row['price_baht']:,.0f}฿ · {row['tokens_spent']:,} Token "
                    f"· กำไร {row['profit_baht']:,.0f}฿\n\n"
                    + text_today(conn, row["sold_on"]))

    if cmd in ("health", "สุขภาพ", "ตรวจ"):
        start, end = month_bounds()
        h = db.data_health(conn, start, db.today_th())
        lines = [f"<b>คุณภาพข้อมูลเดือน {TH_MONTHS[int(start[5:7]) - 1]}</b>"]
        if h["adjust_times"] == 0:
            lines.append("✅ ไม่เคยต้องปรับยอด Token เลย")
        else:
            pct = 100 * h["adjust_size"] / h["tokens"] if h["tokens"] else 0
            lines.append(f"ปรับยอด Token {h['adjust_times']} ครั้ง "
                         f"· รวม {h['adjust_net']:+,} (ขนาดรวม {h['adjust_size']:,})")
            lines.append(f"คิดเป็น {pct:.1f}% ของ Token ที่ใช้ทั้งเดือน")
            lines.append("<i>ถ้าเกิน 3% ทุกวันแบบสม่ำเสมอ = ต้นทุนแฝงจากการกดของ"
                         "แพงกว่า RAP · ถ้ากระโดดไปมา = ลืมจดบางออเดอร์</i>")
        if h["days_unexplained"]:
            lines.append(f"\n⚠️ มี {h['days_unexplained']} วันที่ไม่มียอดและยังไม่ระบุสาเหตุ"
                         "\n<i>ใช้</i> <code>/close</code> <i>ระบุย้อนหลังได้</i>")
        if h["orders"]:
            lines.append(f"\nจาก {h['orders']} ออเดอร์ "
                         f"· ไม่ได้ใส่หมายเหตุ {h['no_note']}")
            lines.append("<i>หมายเหตุใส่ชื่อไอเทมไว้ก็พอ ใช้ย้อนดูตอนลูกค้า"
                         "ทักกลับมาว่าเคยซื้ออะไรไป</i>")
        return send(chat_id, "\n".join(lines))

    if cmd in ("booth", "บูธ"):
        nums = [int(w) for w in words[1:] if w.isdigit()]
        if not nums:
            return send(chat_id,
                        "<b>บอกว่าในบูธมีอะไรตั้งขายอยู่</b>\n"
                        "เปิดบูธในเกม แล้วพิมพ์ราคาทุกชิ้นเรียงมาเลย "
                        "บอทบวกให้เอง\n"
                        "<code>/บูธ 599 529 488 459 269 269 269 169</code>\n\n"
                        "<i>หรือถ้าบวกมาแล้วก็ใส่ยอดเดียว</i> <code>/บูธ 3051</code>\n"
                        "<i>ถ้าในบูธไม่เหลืออะไรเลย</i> <code>/บูธ 0</code>")
        skipped = [w for w in words[1:] if not w.isdigit()]
        bad = _count_sanity(0, nums)
        if bad:
            return send(chat_id, bad)
        return send(chat_id, booth_record_text(conn, nums, skipped)
                    + "\n\n" + text_capital(conn))

    # /นับ 3780 1660 639 620 ... = Token ในไอดี ตามด้วยราคาของในบูธทุกชิ้น
    #
    # เดิมต้องสั่ง /เช็ค กับ /บูธ แยกกัน และต้องทำคู่กันทุกครั้ง
    # ถ้าลืม /บูธ บอทจะนับของที่ขายออกจากบูธไปแล้วซ้ำ (27 ก.ย. 2026 นับเกินไป 7,000)
    # กฎที่ต้องจำ = กฎที่จะถูกลืม รวมเป็นคำสั่งเดียวแล้วลืมไม่ได้อีก
    #
    # ตัวแรกเป็น Token ในไอดีเสมอ ที่เหลือคือบูธ · บูธว่างพิมพ์ 0 ต่อท้าย
    if cmd == "นับ":
        nums = [w for w in words[1:] if w.isdigit()]
        if len(nums) < 2:
            if nums:
                # เลขเดียวไม่รู้ว่าบูธว่างหรือลืมใส่ — ไม่เดา ไม่บันทึกอะไร
                return send(chat_id,
                            "ใส่ราคาของในบูธต่อท้ายด้วยครับ\n"
                            f"<code>/นับ {nums[0]} 1660 639 620</code>\n"
                            f"<i>ถ้าบูธว่าง</i> <code>/นับ {nums[0]} 0</code>")
            return send(chat_id,
                        "<b>นับของทั้งหมดในเกม</b> — Token ในไอดี ตามด้วยราคาของในบูธทุกชิ้น\n"
                        "<code>/นับ 3780 1660 639 620 600 595</code>\n\n"
                        "<i>บูธว่างพิมพ์</i> <code>/นับ 3780 0</code>\n"
                        "<i>ของเหมาที่ย่อยออกแล้วหรือยัง ไม่ต้องจำ บอทนับเจอเองทั้งสองที่</i>")
        skipped = [w for w in words[1:] if not w.isdigit()]
        # ต่างจาก /บูธ ตรงที่ /นับ ปฏิเสธทั้งก้อนถ้ามีคำแปลก ไม่ข้ามแล้วทำต่อ
        # เพราะตำแหน่งมีความหมาย: "/นับ 5OO 300 200" ถ้าข้าม 5OO
        # ยอดในไอดีจะกลายเป็น 300 แล้วปรับยอด Token ผิดทั้งระบบ
        if skipped:
            return send(chat_id,
                        "⚠️ <b>ยังไม่ได้บันทึก</b> — มีคำที่ไม่ใช่ตัวเลข: "
                        + " ".join(f"<code>{html.escape(w)}</code>" for w in skipped)
                        + "\n<i>พิมพ์ใหม่ทั้งชุดเป็นตัวเลขล้วน คั่นด้วยเว้นวรรค</i>")
        wallet, booth = int(nums[0]), [int(n) for n in nums[1:]]
        bad = _count_sanity(wallet, booth)
        if bad:
            return send(chat_id, bad)
        # ลำดับสำคัญ: นับ Token ก่อน แล้วค่อยจดบูธ
        # booth_check_id จะชี้ไปที่การนับครั้งนี้ บอทจึงไม่เตือนว่าเลขบูธค้าง
        check = token_check_text(conn, wallet)
        return send(chat_id, check + "\n\n" + booth_record_text(conn, booth, skipped)
                    + "\n\n" + text_capital(conn))

    if cmd in ("capital", "ทุน", "มูลค่า"):
        return send(chat_id, text_capital(conn))

    if cmd in ("snapshot", "ยกยอด", "ยอดเงิน"):
        return handle_snapshot(conn, chat_id, words)

    if cmd in ("expense", "ค่าใช้จ่าย", "ค่าธรรมเนียม"):
        return handle_expense(conn, chat_id, words)

    if cmd in ("pending", "ค้าง", "ค้างส่ง"):
        return handle_pending(conn, chat_id, words, text)

    if cmd in ("delivered", "ส่งแล้ว"):
        return handle_close_pending(conn, chat_id, words, "delivered")

    if cmd in ("refund", "คืนเงิน"):
        return handle_close_pending(conn, chat_id, words, "refunded")

    if cmd in ("forfeit", "ตัดหนี้"):
        return handle_close_pending(conn, chat_id, words, "forfeited")

    if cmd in ("transfer", "โอน", "ย้าย"):
        return handle_transfer(conn, chat_id, words, text)

    if cmd in ("trueprofit", "กำไรจริง", "กำไร"):
        return send(chat_id, text_true_profit(conn))

    if cmd in ("ktb", "กรุงไทย", "บัญชี"):
        return handle_ktb(conn, chat_id, words)

    if cmd in ("balance", "เหลือ"):
        return handle_balance(conn, chat_id, words)

    if cmd in ("personal", "ส่วนตัว"):
        return send(chat_id, text_spend(conn))

    if cmd in ("trip", "เที่ยว", "ทริป"):
        return handle_trip(conn, chat_id, words)

    if cmd in ("check", "เช็ค"):
        return handle_token_check(conn, chat_id, words)

    if cmd in ("list", "ตั้ง"):
        parts = text.split()
        if len(parts) < 2 or _to_float(parts[1]) is None:
            return send(chat_id,
                        "<b>ตั้งขายที่บูธเท่าไหร่ดี</b> — <code>/ตั้ง [RAP ของไอเทม]</code>\n"
                        "เช่น <code>/ตั้ง 670</code>\n\n"
                        f"<i>บูธกินค่าธรรมเนียม {BOOTH_FEE:.0%} ปัดลง "
                        "ถ้าตั้งเท่า RAP เป๊ะจะได้กลับมาไม่ครบ</i>")
        rap = int(_to_float(parts[1]))
        need = booth_list_price(rap)
        lines = [f"<b>RAP {rap:,}</b>",
                 f"ตั้ง <b>{need:,}</b> → ได้ {booth_net(need):,} "
                 f"(น้อยที่สุดที่ยังได้ทุนคืนครบ)"]
        for extra in (1.01, 1.02, 1.05):
            p = round(rap * extra)
            if p > need:
                lines.append(f"ตั้ง {p:,} → ได้ {booth_net(p):,} "
                             f"(เกินทุน {booth_net(p) - rap:+,})")
        lines.append(f"\n<i>ตั้งเท่า RAP เป๊ะ ({rap:,}) จะได้แค่ {booth_net(rap):,} "
                     f"ขาดทุน {rap - booth_net(rap):,}</i>")
        return send(chat_id, "\n".join(lines))

    if cmd in ("rate", "เรท"):
        parts = text.split()
        if len(parts) < 3:
            return send(chat_id,
                        "คิดเรทให้: <code>/เรท [Token ที่ได้] [บาทที่จ่าย]</code>\n"
                        "เช่น <code>/เรท 2297 130</code> = ของที่รับเหมามา\n"
                        "หรือ <code>/เรท 700 63</code> = ซื้อ Token จากพ่อค้า\n\n"
                        "<i>จะพิมพ์ในบรรทัดขายตรงๆ ก็ได้ ไม่ต้องคิดเอง เช่น</i>\n"
                        "<code>80 900 2297/130 x3</code>")
        tk, bt = _to_float(parts[1]), _to_float(parts[2])
        if tk is None or bt is None or bt <= 0 or tk <= 0:
            return send(chat_id, "ใส่เป็นตัวเลขบวกทั้งคู่ครับ")
        r = tk / bt
        mr = merchant_rate(conn)
        cmp_txt = (f"ดีกว่าเรทซื้อ Token ล่าสุด ({mr:.2f}) อยู่ {r / mr:.2f} เท่า" if r > mr
                   else f"แย่กว่าเรทซื้อ Token ล่าสุด ({mr:.2f}) อยู่ {mr / r:.2f} เท่า")
        # บอกเป็นเงินด้วย เพราะดีลใหญ่เรทต่ำแต่ประหยัดเป็นร้อย ดีลเล็กเรทสูงแต่ได้หลักสิบ
        # ดูแค่เรทจะเลือกผิด (CLAUDE.md ข้อ 2 — ดูกำไรต่อดีล ไม่ใช่ต่อหน่วย)
        diff = tk / mr - bt
        money_txt = (f"ถ้าซื้อ Token เท่านี้ที่เรท {mr:.2f} ต้องจ่าย {tk / mr:,.0f}฿ "
                     + (f"→ ประหยัด <b>{diff:,.0f}฿</b>" if diff > 0
                        else f"→ แพงกว่า <b>{-diff:,.0f}฿</b>"))
        return send(chat_id,
                    f"<b>{r:.2f} Token ต่อ 1 บาท</b> · {cmp_txt}\n"
                    f"{money_txt}\n"
                    f"ของราคา 1,000 Token จะมีทุน {1000 / r:,.1f}฿\n\n"
                    f"<i>เวลาจดขาย พิมพ์เรทเป็น</i> <code>{parts[1]}/{parts[2]}</code> "
                    f"<i>ได้เลย ไม่ต้องหาร</i>")
    if cmd in ("week", "สัปดาห์"):
        return send(chat_id, text_week(conn))
    if cmd in ("month", "เดือน"):
        return send(chat_id, text_month(conn))
    if cmd in ("band", "ช่วง"):
        return send(chat_id, text_band(conn))
    if cmd in ("close", "ปิดวัน"):
        # ปริยายคือ "วันทำการ" (ตี 1 = ยังหมายถึงเมื่อวาน)
        # พิมพ์ วันนี้ / เมื่อวาน ต่อท้ายเพื่อบังคับ
        if "วันนี้" in words[1:]:
            day = db.today_th()
        elif "เมื่อวาน" in words[1:]:
            day = (db.now_th().date() - timedelta(days=1)).isoformat()
        else:
            day = business_day()

        # วันที่ขายได้อยู่แล้ว ไม่ต้องถามว่าทำไมไม่ได้เงิน
        if db.day_summary(conn, day)["orders"] > 0:
            return send(chat_id,
                        f"{fmt_date(day)} มีการขายอยู่แล้ว ไม่ต้องระบุสาเหตุครับ\n\n"
                        + text_today(conn, day)
                        + "\n\n<i>ถ้าจะระบุวันอื่น พิมพ์</i> "
                          "<code>/close เมื่อวาน</code> <i>หรือ</i> "
                          "<code>/close วันนี้</code>")

        return send(chat_id, f"<b>{fmt_date(day)}</b> ไม่ได้เงิน เพราะอะไร?\n"
                             "<i>ถ้าไม่ใช่วันนี้ที่ต้องการ พิมพ์</i> "
                             "<code>/close วันนี้</code>",
                    reason_buttons(day))

    if cmd in ("inq", "ทัก"):
        nums = [w for w in words[1:] if w.isdigit()]
        if not nums:
            return send(chat_id, "ใช้แบบนี้: <code>/inq 5</code> (มีคนทัก 5 คน)\n"
                                 "<i>ต่อท้ายด้วย</i> <code>วันนี้</code> "
                                 "<i>ถ้าอยากลงวันตามปฏิทินแทนวันทำการ</i>")
        day = db.today_th() if "วันนี้" in words[1:] else business_day()
        db.set_inquiries(conn, day, int(nums[0]))
        return send(chat_id, f"บันทึกแล้ว · {fmt_date(day)} มีคนทัก {int(nums[0])} คน\n\n"
                             + text_today(conn, day))

    if cmd in ("undo", "ยกเลิก"):
        # ใช้ลำดับที่บันทึกจริงก่อน (ดู db.pop_undo ว่าทำไม)
        top = db.pop_undo(conn)
        if top:
            kind, rid = top
            if kind == "spend":
                sp = conn.execute("SELECT * FROM spend WHERE id = ?", (rid,)).fetchone()
                db.delete_spend(conn, rid)
                return send(chat_id, f"ลบรายจ่ายส่วนตัวล่าสุดแล้ว: "
                                     f"{sp['baht']:,.0f}฿ {sp['category'] or ''}".rstrip())
            if kind == "purchase":
                p = db.purchase_by_id(conn, rid)
                db.delete_purchase(conn, rid)
                label = "เหมา" if p["kind"] == "lot" else "ซื้อ Token"
                return send(chat_id, f"ลบรายการซื้อล่าสุดแล้ว: {label} #{rid} "
                                     f"· {p['baht']:,.0f}฿\n"
                                     "<i>เรทที่ตั้งไว้ยังเป็นค่าเดิม ถ้าต้องการเปลี่ยน "
                                     "ให้บันทึกการซื้อใหม่</i>")
            s = db.sale_by_id(conn, rid)
            db.delete_sale(conn, rid)
            return send(chat_id, f"ลบรายการขายล่าสุดแล้ว: #{rid} {s['price_baht']:,.0f}฿ "
                                 f"· {s['tokens_spent']:,} Token")

        # กองว่าง = ของที่บันทึกก่อนมีระบบจำลำดับ — ใช้วิธีเดิม (เทียบเวลา)
        sale, purch = db.last_sale(conn), db.last_purchase(conn)
        sp = db.last_spend(conn)
        newest = max((r["logged_at"] for r in (sale, purch, sp) if r), default=None)
        if sp is not None and sp["logged_at"] == newest:
            db.delete_spend(conn, sp["id"])
            return send(chat_id, f"ลบรายจ่ายส่วนตัวล่าสุดแล้ว: "
                                 f"{sp['baht']:,.0f}฿ {sp['category'] or ''}".rstrip())
        # ลบอันที่เพิ่งบันทึกล่าสุดจริงๆ ไม่ว่าจะเป็นการขายหรือการซื้อ
        if sale is None and purch is None:
            return send(chat_id, "ยังไม่มีรายการให้ลบ")
        if purch is not None and (sale is None or purch["logged_at"] > sale["logged_at"]):
            db.delete_purchase(conn, purch["id"])
            kind = "เหมา" if purch["kind"] == "lot" else "ซื้อ Token"
            return send(chat_id, f"ลบรายการซื้อล่าสุดแล้ว: {kind} #{purch['id']} "
                                 f"· {purch['baht']:,.0f}฿\n"
                                 "<i>เรทที่ตั้งไว้ยังเป็นค่าเดิม ถ้าต้องการเปลี่ยน "
                                 "ให้บันทึกการซื้อใหม่</i>")
        db.delete_sale(conn, sale["id"])
        return send(chat_id, f"ลบรายการขายล่าสุดแล้ว: {sale['price_baht']:,.0f}฿ "
                             f"· {sale['tokens_spent']:,} Token")

    return send(chat_id, f"ไม่รู้จักคำสั่ง <code>/{html.escape(cmd)}</code> "
                         "· พิมพ์ /help ดูวิธีใช้")


def handle_sale_lines(conn, chat_id, text):
    """บันทึกรายการขาย — ข้อความที่ไม่ได้ขึ้นต้นด้วย / จะมาที่นี่ทั้งหมด"""
    today = db.now_th().date()
    rate = db.current_rate(conn, DEFAULT_RATE)
    sales, errors = parse_message(text, today, rate)

    reply = []
    if sales:
        total_profit = 0.0
        reply.append(f"<b>บันทึก {len(sales)} รายการ</b>")
        dupes = []
        for s in sales:
            dup = db.find_duplicate(conn, s)
            sale_id = db.insert_sale(conn, s)
            if dup:
                dupes.append((sale_id, dup["id"]))
            total_profit += s["price_baht"] - s["tokens_spent"] / s["token_rate"]
            reply.append(f"#{sale_id} {html.escape(describe(s, today))}")
        if len(sales) > 1:
            reply.append(f"\nรวมกำไร {total_profit:,.1f}฿")
        if dupes:
            reply.append("\n⚠️ <b>เหมือนจดซ้ำ</b>")
            for new_id, old_id in dupes:
                reply.append(f"#{new_id} ซ้ำกับ #{old_id} ที่เพิ่งจดไปเมื่อกี้")
            reply.append("<i>ถ้าจดซ้ำจริง พิมพ์</i> <code>/undo</code> <i>ลบอันล่าสุด</i>")
        if any(s["rate_from_default"] for s in sales):
            src = db.get_state(conn, "current_rate_src", "ค่าปริยาย")
            reply.append(f"<i>บรรทัดที่ไม่ได้ใส่เรท คิดที่ {rate:.2f} — จาก {src}</i>")

        # เตือนเมื่อทุนสูงกว่าราคาขายมากผิดปกติ
        #
        # ปกติขายได้ 1.2-3 เท่าของทุน ขาดทุนบ้างก็เกิดได้ แต่ทุนเกิน 3 เท่า
        # ของราคาขายแทบเป็นไปไม่ได้ ส่วนใหญ่คือพิมพ์ Token เกินหลัก
        # (เช่น 1990 แทน 199) ซึ่งเดิมบันทึกเงียบๆ แล้วกำไรทั้งเดือนเพี้ยน
        weird = [s for s in sales
                 if s["tokens_spent"] / s["token_rate"] > s["price_baht"] * 3]
        if weird:
            reply.append("\n⚠️ <b>ตัวเลขดูผิดปกติ</b>")
            for s in weird:
                cost = s["tokens_spent"] / s["token_rate"]
                reply.append(f"ขาย {s['price_baht']:,.0f}฿ แต่ทุน {cost:,.0f}฿ "
                             f"({s['tokens_spent']:,} Token) — พิมพ์ Token เกินหลักมั้ย")
            reply.append("<i>ถ้าพิมพ์ผิด</i> <code>/undo</code> <i>แล้วจดใหม่</i>")

    for line_no, raw, msg in errors:
        reply.append(f"⚠️ บรรทัด {line_no} ไม่ผ่าน: <code>{html.escape(raw)}</code>\n   {msg}")

    if not sales and not errors:
        reply.append("อ่านไม่ออกครับ พิมพ์ /help ดูตัวอย่าง")
    if sales:
        # แสดงยอดของวันที่เพิ่งลงไป (อาจเป็นเมื่อวานถ้าลงย้อนหลัง)
        for d in dict.fromkeys(s["sold_on"] for s in sales):
            reply.append("\n" + text_today(conn, d))

    return send(chat_id, "\n".join(reply))


def handle_spend(conn, chat_id, text, words):
    """
    /จ่าย 50 ข้าว              จดรายจ่ายส่วนตัว 1 รายการ
    /จ่าย 50 ข้าว 120 เที่ยว    จดหลายรายการในข้อความเดียว

    เงินก้อนนี้คนละก้อนกับธุรกิจ ไม่มีวันไปปนกับตัวเลขกำไร
    """
    note = None
    body = text
    if "#" in body:
        body, _, note = body.partition("#")
        note = note.strip() or None

    day = ((db.now_th().date() - timedelta(days=1)).isoformat()
           if any(w.lower() in DAY_WORDS for w in words[1:]) else db.today_th())

    # อ่านเป็นคู่ "จำนวนเงิน ตามด้วยชื่อหมวด" ชื่อหมวดจะไม่ใส่ก็ได้
    items, pending = [], None
    for w in body.split()[1:]:
        if w.lower() in DAY_WORDS:
            continue
        n = _to_float(w)
        if n is not None:
            if pending is not None:
                items.append((pending, None))
            pending = n
        elif pending is not None:
            items.append((pending, w))
            pending = None
    if pending is not None:
        items.append((pending, None))

    items = [(b, c) for b, c in items if b > 0]
    if not items:
        return send(chat_id,
                    "<b>จดรายจ่ายส่วนตัว</b>\n"
                    "<code>/จ่าย 50 ข้าว</code>\n"
                    "<code>/จ่าย 50 ข้าว 120 เที่ยว 60 รถ</code>\n\n"
                    "<i>เงินก้อนนี้แยกจากธุรกิจ ไม่ไปปนกับตัวเลขกำไร</i>")

    for baht, cat in items:
        db.add_spend(conn, baht, cat, note, day)

    total = sum(b for b, _ in items)
    lines = [f"<b>จด {len(items)} รายการ · {fmt_date(day)}</b>"]
    for baht, cat in items:
        lines.append(f"· {baht:,.0f}฿ {html.escape(cat) if cat else ''}".rstrip())
    if len(items) > 1:
        lines.append(f"รวม {total:,.0f}฿")
    lines.append("\n" + text_spend(conn))
    return send(chat_id, "\n".join(lines))


def text_spend(conn) -> str:
    """สรุปรายจ่ายส่วนตัวเดือนนี้ เทียบงบ"""
    start, end = month_bounds()
    today = db.now_th().date()
    used = db.spend_total(conn, start, today.isoformat())
    days_left = (date.fromisoformat(end) - today).days + 1
    left = PERSONAL_BUDGET - used

    lines = [f"<b>ส่วนตัวเดือน {TH_MONTHS[int(start[5:7]) - 1]}</b>",
             f"ใช้ไป {used:,.0f}฿ / งบ {PERSONAL_BUDGET:,.0f}฿  "
             f"{bar(used, PERSONAL_BUDGET)}"]
    if left >= 0:
        lines.append(f"เหลืองบ {left:,.0f}฿ · อีก {days_left} วัน "
                     f"→ ใช้ได้วันละ {left / max(days_left, 1):,.0f}฿")
    else:
        lines.append(f"⚠️ เกินงบ {-left:,.0f}฿ แล้ว")

    rows = db.spend_by_category(conn, start, today.isoformat())
    if rows:
        lines.append("")
        for r in rows[:6]:
            lines.append(f"· {r['category']} {r['total']:,.0f}฿ ({r['times']} ครั้ง)")
    return "\n".join(lines)


def stock_value(conn):
    """
    มูลค่าของที่ตุนไว้ คิดเป็นเงินบาทตามต้นทุนที่จ่ายมาจริง

    ทำไมต้องมี: บอทเดิมนับแต่เงินสด วันไหนเอาเงินไปตุนของเยอะ
    ตัวเลขจะดูเหมือนธุรกิจกำลังพัง ทั้งที่ของยังอยู่ครบและขายได้

    ใช้เรทเฉลี่ยถ่วงน้ำหนัก ไม่ใช่เรทของการซื้อครั้งล่าสุด
    เพราะ Token ที่กองอยู่มาจากหลายแหล่งคนละเรท (พ่อค้า ~11 · เหมา 20-50)
    แล้วแยกไม่ออกว่าตัวไหนมาจากไหน — ดูเหตุผลเต็มใน db.blended_rate()
    """
    blended, pending_lots = db.blended_rate(conn, DEFAULT_RATE)
    # ดูเหตุผลที่ไม่ใช้ blended ตรงที่ประกาศ STOCK_RATE
    # ใช้เรทพ่อค้าครั้งล่าสุด (ราคาที่ต้องจ่ายถ้าวันนี้ต้องซื้อใหม่)
    # STOCK_RATE เหลือไว้เป็นค่าสำรองตอนยังไม่เคยซื้อ Token เลย
    rate = db.current_rate(conn, 0) or STOCK_RATE
    # กันไว้อีกชั้นเผื่อมีใครเซ็ต bot.STOCK_RATE ตอนรัน (เทสต์ทำแบบนั้น)
    if rate <= 0:
        rate = DEFAULT_RATE
    tokens = db.token_balance(conn)["expected"]
    booth = int(db.get_state(conn, "booth_tokens", 0) or 0)
    booth_net_tokens = booth * (1 - BOOTH_FEE)

    # ยอดบูธเป็นเลขที่นับมือแล้วจดไว้ มันไม่ลดเองเวลาของในบูธขายออก
    # ของที่ขายออกจากบูธจะกลายเป็น Token ในไอดี ซึ่ง /เช็ค จะไปนับเจอ
    # ถ้า /เช็ค ใหม่กว่า /บูธ แปลว่าเลขบูธอาจค้างของที่ขายไปแล้ว = นับซ้ำ
    #
    # เกิดขึ้นจริง 27 ก.ย. 2026 บูธค้างอยู่ที่ 9,773 จากเมื่อวาน
    # พอ /เช็ค ได้ 13,773 บอทเลยรวมเป็น 23,448 ทั้งที่ของจริงมีราว 16,000
    booth_at = db.state_updated_at(conn, "booth_tokens")
    marker = db.get_state(conn, "booth_check_id")
    if marker is not None:
        # จำไว้ว่าตอนจดเลขบูธ นับ Token ไปถึงรายการที่เท่าไหร่แล้ว
        booth_stale = bool(booth and db.last_token_check_id(conn) > int(marker))
    else:
        # ข้อมูลเก่าที่จดก่อนมีตัวนับนี้ — เทียบวันที่แทน
        check_at = db.last_token_check_at(conn)
        booth_stale = bool(booth and booth_at and check_at
                           and check_at[:10] > booth_at[:10])

    return {"rate": rate, "blended": blended, "pending_lots": pending_lots,
            "tokens": tokens, "booth": booth,
            "booth_stale": booth_stale, "booth_at": booth_at,
            "on_hand": tokens + booth_net_tokens,
            "tokens_baht": tokens / rate, "booth_baht": booth_net_tokens / rate,
            "total_baht": (tokens + booth_net_tokens) / rate}


# เพดานกันพิมพ์ผิด — ไม่ใช่กฎธุรกิจ
# ปัญหาจริงคือลูกน้ำ: "639,620,600" ถูกอ่านเป็นเลขเดียว 639,620,600 (ตัดลูกน้ำหลักพัน)
# และเลขเกิน 2,147,483,647 ทำให้ Postgres ปฏิเสธทั้งคำสั่ง (SQLite ในเทสต์ไม่ฟ้อง)
BOOTH_ITEM_MAX = 100_000        # ของชิ้นเดียวในบูธ แพงสุดที่เคยเห็นยังไม่ถึงหลักหมื่นปลาย
WALLET_MAX = 10_000_000         # Token ในไอดี


def _count_sanity(wallet, booth) -> str:
    """คืนข้อความเตือนถ้าตัวเลขดูผิด · คืน "" ถ้าปกติ"""
    if wallet > WALLET_MAX:
        return (f"⚠️ <b>ยังไม่ได้บันทึก</b> — Token ในไอดี {wallet:,} ดูผิดปกติ\n"
                "<i>ถ้าคั่นราคาด้วยลูกน้ำ ให้ใช้เว้นวรรคแทน</i>")
    # เลขเดียว = ยอดรวมที่บวกมาแล้ว (/บูธ 3051) ใหญ่ได้ · หลายตัว = ราคาทีละชิ้น
    cap = BOOTH_ITEM_MAX if len(booth) > 1 else WALLET_MAX
    big = [n for n in booth if n > cap]
    if big:
        return (f"⚠️ <b>ยังไม่ได้บันทึก</b> — ราคาในบูธ {big[0]:,} ดูผิดปกติ "
                f"(เกิน {cap:,})\n"
                "<i>ถ้าคั่นราคาด้วยลูกน้ำ เช่น 639,620 บอทจะอ่านเป็นเลขเดียว "
                "ให้ใช้เว้นวรรคแทน:</i> <code>639 620</code>")
    return ""


def booth_record_text(conn, nums, skipped) -> str:
    """จดของในบูธ — ใช้ร่วมกันระหว่าง /บูธ กับ /นับ"""
    # ใส่หลายตัวได้ บอทบวกให้ — พิมพ์ตามที่เห็นในเกมได้เลย ไม่ต้องบวกมือ
    # (บวกมือเองแล้วพิมพ์ผิดตัวเดียว ของตุนจะเพี้ยนโดยไม่มีอะไรเตือน)
    nums = [int(n) for n in nums]
    total = sum(nums)
    db.set_state(conn, "booth_tokens", total)
    # จำไว้ว่าเลขบูธนี้จดตอนที่นับ Token ไปถึงรายการไหนแล้ว
    # ถ้ามีการนับใหม่หลังจากนี้ แปลว่าเลขบูธอาจค้างของที่ขายไปแล้ว
    db.set_state(conn, "booth_check_id", db.last_token_check_id(conn))
    head = f"บันทึกของในบูธ {total:,} Token"
    if len(nums) > 1:
        head += f"\n<i>{len(nums)} ชิ้น · " + " + ".join(
            f"{n:,}" for n in nums) + "</i>"
    head += (f"\n<i>บูธหัก {BOOTH_FEE:.0%} → ได้จริงราว "
             f"{booth_net(total):,} Token</i>")
    # คำที่ไม่ใช่ตัวเลขล้วนจะถูกมองข้าม ต้องบอกให้รู้
    # พิมพ์ 5OO (โอใหญ่) แทน 500 คือเรื่องที่เกิดได้จริงตอนพิมพ์เร็วๆ
    # ถ้าเงียบไป ของตุนจะหายไป 500 Token โดยไม่มีใครรู้
    if skipped:
        head += ("\n\n⚠️ ข้ามคำที่ไม่ใช่ตัวเลขไป: "
                 + " ".join(f"<code>{html.escape(w)}</code>" for w in skipped)
                 + "\n<i>ถ้าตั้งใจให้เป็นราคา ให้พิมพ์ใหม่ทั้งชุด</i>")
    return head


def booth_warning(st) -> str:
    """ข้อความเตือนเลขบูธค้าง — ใช้ซ้ำหลายคำสั่ง"""
    if not st["booth_stale"]:
        return ""
    return (f"⚠️ เลขบูธ {st['booth']:,} จดไว้ตั้งแต่ {fmt_date(st['booth_at'][:10])} "
            f"แต่นับ Token ในไอดีหลังจากนั้น\n"
            f"<i>ของในบูธที่ขายไปแล้วจะถูกนับสองรอบ ทำให้ของตุนดูเยอะเกินจริง</i>\n"
            f"<i>นับใหม่ทั้งสองที่พร้อมกัน</i> <code>/นับ [Token] [ราคาในบูธทุกชิ้น]</code> "
            f"<i>· บูธว่างพิมพ์</i> <code>/นับ [Token] 0</code>")


def text_true_profit(conn) -> str:
    """
    กำไรจริง 3 ชั้น — คำสั่ง /กำไรจริง

    ทำไมต้องมีคำสั่งนี้แยกจาก /month
    --------------------------------
    /month รายงานกำไรที่คิดต้นทุนรายออเดอร์ด้วยเรทตอนที่ขาย
    ซึ่งใช้เทียบออเดอร์กันได้ แต่เอามารวมเป็นยอดเดือนแล้วต่ำกว่าจริง
    ก.ย. 2026 วัดได้ว่าต่ำไป 709 บาท เพราะของเหมาถูกกว่าที่บอทคิด

    ชั้นที่ 1 เป็นตัวที่เถียงไม่ได้ ไม่ต้องเดาเรทอะไรเลย
    ชั้นที่ 2 เป็นค่าประมาณ เพราะต้องตีราคาของที่ยังขายไม่ออก
    จึงแสดงแยกกัน ไม่ยุบเป็นเลขเดียว เจ้าของต้องเห็นว่าอันไหนแน่อันไหนเดา
    """
    start, end = month_bounds()
    st = stock_value(conn)

    # ของที่ตุนไว้ตอนต้นเดือน — ถ้าเดือนก่อนมีบันทึกไว้ให้ใช้ของจริง
    # ถ้าไม่มี (เดือนแรกที่ใช้ระบบ) ย้อนคำนวณจากรายการเข้าออก
    snapshot = db.get_state(conn, f"stock_tokens_{start[:7]}")
    if snapshot is not None:
        tokens_start = float(snapshot)
        start_note = None
    else:
        day_before = (date.fromisoformat(start) - timedelta(days=1)).isoformat()
        tokens_start = max(db.token_balance(conn, day_before)["expected"], 0)
        start_note = "ของตุนตอนต้นเดือนย้อนคำนวณให้ ยังไม่ได้บันทึกไว้ตอนนั้น"

    t = db.true_profit(conn, start, end, st["rate"],
                       st["on_hand"], tokens_start)
    moved = db.transfer_total(conn, start, end)

    month_name = TH_MONTHS[int(start[5:7]) - 1]
    lines = [
        f"<b>กำไรจริงเดือน {month_name}</b>",
        "",
        "<b>ชั้น 1 · เงินสด</b> — ไม่ต้องเดาเรท เถียงไม่ได้",
        f"  ลูกค้าโอนเข้า      {t['cash_in']:>9,.0f}฿",
        f"  จ่ายซื้อของ       {-t['cash_out']:>9,.0f}฿",
    ]
    if t.get("expenses"):
        lines.append(f"  ค่าธรรมเนียม      {-t['expenses']:>9,.0f}฿")
    lines += [
        f"  <b>กำไรเงินสด      {t['profit_cash']:>9,.0f}฿</b>",
        "",
        "<b>ชั้น 2 · ของที่ตุนไว้</b> — เป็นค่าประมาณ",
        f"  Token คงเหลือ {st['on_hand']:>12,.0f} หน่วย",
        f"  ตีที่เรทพ่อค้า {st['rate']:.0f}    {t['stock_end']:>9,.0f}฿",
        f"  ตอนต้นเดือนมี      {-t['stock_start']:>8,.0f}฿",
        f"  <b>ตุนเพิ่มขึ้น       {t['stock_change']:>8,.0f}฿</b>",
        "",
        f"<b>ชั้น 3 · กำไรจริง   {t['profit_true']:>9,.0f}฿</b>",
        f"เป้า {TARGET_MONTH:,.0f}฿",
        bar(t["profit_true"], TARGET_MONTH),
    ]
    gap = TARGET_MONTH - t["profit_true"]
    lines.append(f"ขาดอีก {gap:,.0f}฿" if gap > 0
                 else f"เกินเป้า {-gap:,.0f}฿ 🎉")

    lines += ["", f"<i>เทียบ: /month คิดรายออเดอร์ได้ "
                  f"{t['profit_attributed']:,.0f}฿</i>"]

    if moved:
        lines.append(f"<i>ย้ายเงินออกจากบัญชีร้านเดือนนี้ {moved:,.0f}฿ "
                     f"— ไม่ใช่รายจ่าย ยังเป็นเงินเรา</i>")

    # เงินที่รับมาแล้วแต่ยังไม่ได้ส่งของ ต้องโชว์แยก เพราะยังไม่ใช่กำไร
    owed = db.pending_total(conn)
    if owed:
        n_owed = len(db.open_pendings(conn))
        lines.append(f"⚠️ มีออเดอร์ค้างส่ง {n_owed} รายการ {owed:,.0f}฿ "
                     f"— รับเงินแล้วแต่ยังติดของลูกค้าอยู่\n"
                     f"<i>ยอดนี้ยังไม่ควรนับเป็นกำไร ดูที่</i> <code>/ค้าง</code>")

    # กระทบยอดกับเงินจริง ถ้ามีการจดยอดตั้งต้นไว้
    #
    # นี่คือการตรวจทานว่า "กำไรที่บอทคิดได้" กับ "เงินที่เพิ่มขึ้นจริง" ตรงกันมั้ย
    # ต่างกันเท่าไหร่ = ที่ใช้ส่วนตัว + เงินที่ได้มาจากนอกธุรกิจ
    # ซึ่งบอทไม่มีทางรู้เอง ต้องให้เจ้าของดูแล้วตอบว่าสมเหตุสมผลมั้ย
    opening = db.snapshot_on_or_before(conn, start)
    latest = db.last_snapshot(conn)
    if opening and latest and latest["id"] != opening["id"]:
        grew = ((latest["cash_baht"] + t["stock_end"])
                - (opening["cash_baht"] + t["stock_start"]))
        unexplained = t["profit_true"] - grew
        lines += ["",
                  f"<b>เทียบกับเงินจริง</b> "
                  f"({fmt_date(opening['taken_on'])} → {fmt_date(latest['taken_on'])})",
                  f"  เงินเพิ่มขึ้นจริง   {grew:>9,.0f}฿",
                  f"  กำไรที่ทำได้      {t['profit_true']:>9,.0f}฿",
                  f"  <b>ต่างกัน         {unexplained:>9,.0f}฿</b>"]
        if unexplained > 0:
            lines.append(f"<i>= ที่ถอนไปใช้ส่วนตัว (วันละ ~"
                         f"{unexplained / max(days_counted(start, end), 1):,.0f}฿)</i>")
        else:
            lines.append("<i>เงินเพิ่มมากกว่ากำไร = มีเงินจากนอกธุรกิจเข้ามา "
                         "เช่น ทุน เงินเดือน หรือรายได้ทางอื่น</i>")
    elif latest:
        lines.append(f"<i>จดยอดเงินไว้แล้ว ({fmt_date(latest['taken_on'])}) "
                     f"— สั่ง</i> <code>/ยกยอด</code> <i>อีกครั้งสิ้นเดือน "
                     f"แล้วบอทจะกระทบยอดให้</i>")
    else:
        lines.append("<i>ยังไม่เคยจดยอดเงินตั้งต้น → </i><code>/ยกยอด</code>"
                     "<i> แล้วเดือนหน้าบอทจะกระทบยอดให้เอง</i>")
    warn = booth_warning(st)
    if warn:
        lines += ["", warn]
    # เคยเตือน "มี 8 ล็อตที่ยังไม่ได้ /ย่อย" ตรงนี้ — ถอดออก 30 ก.ย. 2026
    # ของเหมาปนกันในบูธ จำไม่ได้ว่าชิ้นไหนมาจากล็อตไหน ขายออกแล้วหรือยัง
    # เจ้าของบอกตรงๆ ว่าจะไม่มีวันจด (กฎข้อ 8: ช่องที่ไม่มีใครกรอก แย่กว่าไม่มีช่อง)
    # และไม่จำเป็นด้วย — /นับ เห็นของเหมาทั้งตอนอยู่ในบูธและตอนขายออกเป็น Token แล้ว
    # กำไรรวมจึงถูกโดยไม่ต้อง /ย่อย · เสียไปแค่การวัดว่า "ล็อตไหนคุ้มที่สุด"
    if start_note:
        lines.append(f"<i>{start_note}</i>")
    return "\n".join(lines)


def handle_expense(conn, chat_id, words):
    """
    /ค่าใช้จ่าย 25 ค่าธรรมเนียมทรู — ต้นทุนธุรกิจที่ไม่ใช่ของเข้าร้าน

    ทำไมต้องมีแยกจาก /จ่าย (ส่วนตัว) และ /โอน (ย้ายกระเป๋า)
    ค่าธรรมเนียมโอนเงินเป็นต้นทุนจริงของธุรกิจ ต้องหักจากกำไร
    แต่ไม่ใช่ของเข้าร้าน เลยใส่ใน purchase ไม่ได้ (จะทำให้เรทเฉลี่ยเพี้ยน)

    และเป็นต้นทุนที่การกระทบยอดธนาคารจับไม่ได้ ถ้าหักจากวอลเล็ท
    ไม่ได้หักจากกรุงไทย — ถ้าไม่จดตรงนี้ เงินก้อนนี้จะหายไปจากระบบเลย
    """
    nums = [_to_float(w) for w in words[1:] if _to_float(w) is not None]
    start, end = month_bounds()

    if not nums:
        rows = db.expense_by_category(conn, start, end)
        msg = ["<b>จดต้นทุนธุรกิจที่ไม่ใช่ของเข้าร้าน</b>",
               "<code>/ค่าใช้จ่าย 25 ค่าธรรมเนียมทรู</code>",
               "",
               "<i>ต่างจาก</i> <code>/จ่าย</code> <i>ซึ่งเป็นเงินส่วนตัว "
               "และ</i> <code>/โอน</code> <i>ซึ่งแค่ย้ายกระเป๋า</i>",
               "<i>อันนี้หักจากกำไรร้านจริง</i>"]
        if rows:
            msg += ["", f"<b>เดือนนี้เสียไป "
                        f"{db.expense_total(conn, start, end):,.0f}฿</b>"]
            for r in rows:
                msg.append(f"  {r['category']:<14} {r['total']:>6,.0f}฿ "
                           f"({r['times']} ครั้ง)")
        return send(chat_id, "\n".join(msg))

    baht = nums[0]
    if baht <= 0:
        return send(chat_id, "ยอดต้องมากกว่า 0")
    rest = [w for w in words[1:] if _to_float(w) is None]
    category = rest[0] if rest else None
    note = " ".join(rest[1:]) if len(rest) > 1 else None

    eid = db.add_expense(conn, baht, category, note)
    total = db.expense_total(conn, start, end)
    cash = db.cash_summary(conn, start, end)
    return send(chat_id,
                f"#{eid} ต้นทุน {baht:,.0f}฿"
                + (f" · {html.escape(category)}" if category else "")
                + f"\nเดือนนี้เสียไปแล้ว <b>{total:,.0f}฿</b>"
                + f"\n<i>หักจากกำไรแล้ว — กำไรเงินสดเดือนนี้ "
                  f"{cash['profit_cash']:,.0f}฿</i>")


def handle_pending(conn, chat_id, words, text):
    """
    /ค้าง 750 น้องคนนั้น — ลูกค้าโอนมาแล้วแต่ยังไม่ได้ส่งของ
    /ค้าง                 — ดูรายการที่ยังค้างอยู่

    ทำไมต้องแยกจากรายการขาย
    -----------------------
    เงินที่รับมาแล้วแต่ยังไม่ได้ส่งของ ยังไม่ใช่กำไร เพราะยังติดหนี้ของอยู่
    ถ้าเอาไปจดเป็นรายการขายเลย กำไรจะสูงเกินจริงทันทีที่เงินเข้า
    และถ้าวันหลังต้องคืนเงิน จะหาไม่เจอแล้วว่าก้อนไหน

    ก.ย. 2026 เจอเคสจริง ลูกค้าโอน 750 บาทแล้วหายไปเลย
    ตอนนั้นไม่มีที่จด เลยต้องมานั่งไล่ย้อนตอนกระทบยอดสิ้นเดือน
    """
    nums = [_to_float(w) for w in words[1:] if _to_float(w) is not None]

    if not nums:
        rows = db.open_pendings(conn)
        if not rows:
            return send(chat_id,
                        "<b>ไม่มีออเดอร์ค้างส่ง</b>\n\n"
                        "<i>ถ้าลูกค้าโอนมาแล้วยังไม่ได้ส่งของ จดไว้ก่อน</i>\n"
                        "<code>/ค้าง 750 น้องคนนั้น</code>\n\n"
                        "<i>เงินที่ยังไม่ได้ส่งของ ยังไม่นับเป็นกำไร</i>")
        today = db.now_th().date()
        lines = [f"<b>ค้างส่ง {len(rows)} ออเดอร์ "
                 f"· {db.pending_total(conn):,.0f}฿</b>", ""]
        for r in rows:
            days = (today - date.fromisoformat(r["received_on"])).days
            age = "วันนี้" if days == 0 else f"ค้างมา {days} วัน"
            tag = f" · {html.escape(r['note'])}" if r["note"] else ""
            lines.append(f"<code>#{r['id']}</code> {r['baht']:,.0f}฿ "
                         f"({age}){tag}")
        lines += ["", "<i>ส่งของแล้ว</i> <code>/ส่งแล้ว 3</code>",
                  "<i>คืนเงินไป</i> <code>/คืนเงิน 3</code>",
                  "<i>ลูกค้าหายไปเลย นับเป็นรายได้</i> <code>/ตัดหนี้ 3</code>"]
        return send(chat_id, "\n".join(lines))

    baht = nums[0]
    if baht <= 0:
        return send(chat_id, "ยอดต้องมากกว่า 0")
    rest = [w for w in words[1:] if _to_float(w) is None]
    note = " ".join(rest) or None
    pid = db.add_pending(conn, baht, note)
    return send(chat_id,
                f"#{pid} ค้างส่ง {baht:,.0f}฿" + (f" · {html.escape(note)}" if note else "")
                + f"\n<i>ค้างทั้งหมด {db.pending_total(conn):,.0f}฿ "
                  f"— ยังไม่นับเป็นกำไรจนกว่าจะส่งของ</i>"
                + "\n<i>ส่งแล้วพิมพ์</i> <code>/ส่งแล้ว " + str(pid) + "</code>")


def handle_close_pending(conn, chat_id, words, outcome):
    """ปิดออเดอร์ค้าง — ส่งแล้ว / คืนเงิน / ตัดเป็นรายได้"""
    label = {"delivered": "ส่งของแล้ว", "refunded": "คืนเงินแล้ว",
             "forfeited": "ตัดเป็นรายได้"}[outcome]
    nums = [w.lstrip("#") for w in words[1:] if w.lstrip("#").isdigit()]
    if not nums:
        rows = db.open_pendings(conn)
        if not rows:
            return send(chat_id, "ไม่มีออเดอร์ค้างส่งอยู่")
        listing = "\n".join(f"<code>#{r['id']}</code> {r['baht']:,.0f}฿"
                            + (f" · {html.escape(r['note'])}" if r["note"] else "")
                            for r in rows)
        return send(chat_id, f"ระบุเลขรายการด้วย เช่น "
                             f"<code>/{words[0].lstrip('/')} {rows[0]['id']}</code>\n\n"
                             f"<b>ที่ค้างอยู่</b>\n{listing}")

    pid = int(nums[0])
    if not db.close_pending(conn, pid, outcome):
        return send(chat_id, f"ไม่เจอออเดอร์ค้าง #{pid} (อาจปิดไปแล้ว)")

    msg = [f"#{pid} {label}"]
    left = db.pending_total(conn)
    msg.append(f"<i>ยังค้างอีก {left:,.0f}฿</i>" if left
               else "<i>ไม่มีออเดอร์ค้างแล้ว</i>")
    if outcome == "delivered":
        msg.append("\n⚠️ <b>อย่าลืมจดเป็นรายการขายด้วย</b> เช่น <code>150 565</code>\n"
                   "<i>ตารางนี้จดแค่ว่าติดของใคร ไม่ได้นับเป็นยอดขาย</i>")
    elif outcome == "forfeited":
        msg.append("\n<i>ถ้าจะนับเป็นรายได้จริง ให้จดเป็นรายการขายด้วย</i>")
    return send(chat_id, "\n".join(msg))


def handle_snapshot(conn, chat_id, words):
    """
    /ยกยอด 1095 10000 3600 2656 — จดยอดทุกบัญชีรวมกัน ใส่กี่ตัวก็ได้ บอทบวกให้

    ทำไมต้องมี
    27 ก.ย. 2026 เสียเวลาเป็นชั่วโมงไล่ย้อนหาว่าวันเริ่มต้นมีเงินเท่าไหร่
    และไล่ผิด 3 รอบ เพราะไม่เคยจดไว้ ต้องเดาย้อนจากยอดปลายทาง
    จดเดือนละครั้งครั้งเดียว ปัญหานี้จะไม่เกิดอีก
    """
    nums = [_to_float(w) for w in words[1:] if _to_float(w) is not None]
    if not nums:
        last = db.last_snapshot(conn)
        msg = ["<b>จดยอดเงินทุกบัญชี</b> — ทำเดือนละครั้งพอ",
               "<code>/ยกยอด 1095 10000 3600 2656</code>",
               "<i>ใส่ยอดกี่บัญชีก็ได้ บอทบวกให้เอง</i>",
               "<i>เรียงตามที่ถนัด เช่น กรุงไทย · Dime · หุ้น · K-bank</i>",
               "",
               "<i>ไม่ต้องใส่ของในเกม บอทนับจาก Token ให้อยู่แล้ว</i>"]
        if last:
            msg += ["", f"<b>ครั้งก่อน {fmt_date(last['taken_on'])}</b> "
                        f"{last['cash_baht']:,.0f}฿"]
            if last["note"]:
                msg.append(f"<i>{html.escape(last['note'])}</i>")
        return send(chat_id, "\n".join(msg))

    total = sum(nums)
    if total <= 0:
        return send(chat_id, "ยอดรวมต้องมากกว่า 0")

    breakdown = " + ".join(f"{n:,.0f}" for n in nums) if len(nums) > 1 else None
    sid = db.add_snapshot(conn, total, breakdown)

    st = stock_value(conn)
    lines = [f"#{sid} จดยอดวันที่ {fmt_date(db.today_th())} แล้ว"]
    if breakdown:
        lines.append(f"<i>{breakdown}</i>")
    lines += [f"<b>เงินสดรวม {total:,.0f}฿</b>",
              f"+ ของในเกม {st['total_baht']:,.0f}฿",
              f"= <b>{total + st['total_baht']:,.0f}฿</b>",
              "",
              "<i>สิ้นเดือนสั่ง</i> <code>/กำไรจริง</code> "
              "<i>บอทจะเทียบให้เองว่าเงินเพิ่มขึ้นตรงกับกำไรที่ทำได้มั้ย</i>"]
    return send(chat_id, "\n".join(lines))


def handle_transfer(conn, chat_id, words, text):
    """
    /โอน 5600 dime — จดเงินที่ย้ายออกจากบัญชีร้าน

    ทำไมต้องจด: ก.ย. 2026 กรุงไทยเหลือ 100 บาท แล้วบอทรายงานว่าเก็บเงินได้ 0
    ทั้งที่กำไรจริง 9,682 บาท เพราะเงินย้ายไป Dime กับ K-bank แล้ว
    แต่ไม่มีที่จด บอทจึงเข้าใจว่าเงินหายไป
    """
    nums = [w for w in words[1:] if _to_float(w) is not None]
    if not nums:
        start, end = month_bounds()
        rows = db.transfer_by_destination(conn, start, end)
        msg = ["<b>จดเงินที่ย้ายออกจากบัญชีร้าน</b>",
               "<code>/โอน 5600 dime</code>",
               "<code>/โอน 4000 kbank ไว้ใช้</code>",
               "<code>/โอน -500 เติมเงินตัวเองใส่ร้าน</code>",
               "",
               "<i>การย้ายเงินไม่ใช่รายจ่าย ไม่ทำให้กำไรลด</i>",
               "<i>จดไว้เพื่อให้รู้ว่าทำไมกรุงไทยเหลือน้อย</i>"]
        if rows:
            msg += ["", "<b>เดือนนี้ย้ายไปแล้ว</b>"]
            for r in rows:
                msg.append(f"  {r['destination']:<10} {r['total']:>7,.0f}฿ "
                           f"({r['times']} ครั้ง)")
        return send(chat_id, "\n".join(msg))

    baht = _to_float(nums[0])
    if baht == 0:
        return send(chat_id, "ย้ายเงิน 0 บาทไม่ต้องจดครับ")

    # คำที่เหลือหลังตัวเลขคือปลายทาง เช่น dime / kbank / หุ้น
    rest = [w for w in words[1:] if _to_float(w) is None]
    destination = rest[0] if rest else None
    note = " ".join(rest[1:]) if len(rest) > 1 else None

    tid = db.add_transfer(conn, baht, destination, note)
    direction = "ออกจากบัญชีร้าน" if baht > 0 else "เข้าบัญชีร้าน"
    where = f" → {destination}" if destination else ""
    start, end = month_bounds()
    total = db.transfer_total(conn, start, end)
    return send(chat_id,
                f"#{tid} ย้ายเงิน {abs(baht):,.0f}฿ {direction}{where}\n"
                f"<i>เดือนนี้ย้ายออกรวม {total:,.0f}฿ "
                f"— ไม่กระทบกำไร ดูกำไรจริงที่</i> <code>/กำไรจริง</code>")


def text_capital(conn) -> str:
    s = stock_value(conn)
    cash = float(db.get_state(conn, "ktb_balance", 0) or 0)
    at = (db.get_state(conn, "ktb_balance_at") or "")[:10]
    total = cash + s["total_baht"]

    lines = ["<b>มูลค่ากิจการตอนนี้</b>",
             f"เงินสดกรุงไทย        {cash:>8,.0f}฿" + (f"  ({fmt_date(at)})" if at else ""),
             f"Token {s['tokens']:,} หน่วย   {s['tokens_baht']:>8,.0f}฿"]
    if s["booth"]:
        lines.append(f"ของในบูธ {s['booth']:,}    {s['booth_baht']:>8,.0f}฿")
    else:
        lines.append("<i>ยังไม่ได้บอกยอดของในบูธ → </i><code>/บูธ 9773</code>")
    lines += [f"{'─' * 26}",
              f"<b>รวม {total:,.0f}฿</b>",
              "",
              f"<i>ตีราคาที่เรทพ่อค้า {s['rate']:.0f}/บาท คือราคาที่ต้องจ่าย"
              "ถ้าจะซื้อ Token เพิ่มวันนี้ ไม่ใช่ราคาขาย</i>",
              "<i>ขายจริงได้ราว 2-3 เท่าของทุน</i>"]
    warn = booth_warning(s)
    if warn:
        lines += ["", warn]
    return "\n".join(lines)


def handle_ktb(conn, chat_id, words):
    """
    /กรุงไทย 1496 — บอกยอดบัญชีการค้า แล้วบอทคำนวณความคืบหน้าให้

    ธนาคารไทยไม่มี API ให้ดึงยอดเอง และไม่ควรเอารหัสแอปธนาคารมาใส่บอท
    จึงใช้วิธีเดียวกับ /เช็ค ของ Token คือเจ้าของอ่านเลขมาให้ บอทคิดต่อ
    """
    nums = [w for w in words[1:] if _to_float(w) is not None]
    if not nums:
        prev = db.get_state(conn, "ktb_balance")
        at = db.get_state(conn, "ktb_balance_at")
        msg = "เปิดแอปกรุงไทยดูยอดแล้วพิมพ์ <code>/กรุงไทย 1496</code>"
        if prev:
            when = f" ({fmt_date(at[:10])})" if at else ""
            msg += f"\n\n<i>ครั้งก่อนบันทึกไว้ {float(prev):,.0f}฿{when}</i>"
        return send(chat_id, msg)

    actual = _to_float(nums[0])
    start, end = month_bounds()
    today = db.now_th().date()
    days_left = (date.fromisoformat(end) - today).days + 1

    st = stock_value(conn)
    moved = db.transfer_total(conn, start, end)

    # กำไรสะสมเดือนนี้ "อยู่" 3 ที่ คือเงินในกรุงไทย ของที่ตุนไว้ และเงินที่ย้ายออกไปแล้ว
    #
    # เดิมบอทคิดแค่ (กรุงไทย - เงินค้าง) ซึ่งพังทันทีที่ย้ายเงินออก
    # ก.ย. 2026 กรุงไทยเหลือ 1,095 บอทเลยบอกว่าเก็บได้ 95 บาท
    # ทั้งที่เดือนนั้นกำไรจริง 9,682 บาท — เงินอยู่ใน Dime กับ K-bank หมดแล้ว
    kept = (actual - KTB_FLOAT) + st["total_baht"] + moved
    goal = MONTHLY_TRANSFER

    lines = [f"<b>กรุงไทย {actual:,.0f}฿</b>",
             f"หักเงินค้าง {KTB_FLOAT:,.0f}฿ → เหลือในบัญชีร้าน "
             f"{actual - KTB_FLOAT:,.0f}฿",
             "",
             "<b>แต่กำไรเดือนนี้ไม่ได้อยู่ในกรุงไทยที่เดียว</b>",
             f"  ในบัญชีร้าน        {actual - KTB_FLOAT:>8,.0f}฿",
             f"  ของที่ตุนไว้        {st['total_baht']:>8,.0f}฿ "
             f"(Token {st['on_hand']:,.0f})"]
    if moved:
        lines.append(f"  ย้ายออกไปเก็บแล้ว   {moved:>8,.0f}฿")
    else:
        lines.append("  <i>ย้ายเงินออกไปแล้วยังไม่ได้จด → </i>"
                     "<code>/โอน 5600 dime</code>")
    lines += [f"  {'─' * 24}",
              f"  <b>รวม {kept:,.0f}฿</b>",
              "",
              f"เป้าเก็บก่อนวันที่ 1: {goal:,.0f}฿",
              bar(kept, goal)]
    gap = goal - kept
    if gap > 0:
        lines.append(f"ขาดอีก {gap:,.0f}฿ · เหลือ {days_left} วัน "
                     f"→ ต้องได้วันละ {gap / max(days_left, 1):,.0f}฿")
    else:
        lines.append(f"ถึงเป้าแล้ว เกิน {-gap:,.0f}฿ 🎉")
    lines.append("<i>ตัวเลขกำไรตัวจริงดูที่</i> <code>/กำไรจริง</code>")

    # เทียบกับที่บอทจดไว้ — ไม่ใช่ตัวตัดสินถูกผิด เพราะเงินอาจค้างใน TrueMoney
    # หรือเป็นค่ามัดจำที่ยังไม่ได้ส่งของ
    ca = db.cash_summary(conn, START_DATE, db.today_th())
    lines += ["", f"<i>บอทจดกำไรเงินสดไว้ {ca['profit_cash']:,.0f}฿ "
                  f"ตั้งแต่ {fmt_date(START_DATE)}</i>",
              "<i>ถ้าต่างจากยอดในบัญชีมาก ให้เช็กเงินค้างใน TrueMoney "
              "หรือค่ามัดจำที่ยังไม่ได้ส่งของ</i>"]

    db.set_state(conn, "ktb_balance", actual)
    db.set_state(conn, "ktb_balance_at", db.now_th().isoformat(timespec="seconds"))
    return send(chat_id, "\n".join(lines))


def handle_balance(conn, chat_id, words):
    """
    /เหลือ 1024 — บอกยอด K-eSavings แล้วบอทคำนวณว่าใช้ได้วันละเท่าไหร่

    และตรวจกับรายจ่ายที่จดไว้ ด้วยหลักเดียวกับ /เช็ค ของ Token
    ถ้าเงินหายมากกว่าที่จด แปลว่ามีที่ลืมจด
    """
    nums = [w for w in words[1:] if _to_float(w) is not None]
    if not nums:
        return send(chat_id,
                    "เปิดแอปธนาคารดูยอด K-eSavings แล้วพิมพ์ <code>/เหลือ 1024</code>\n"
                    "<i>บอทจะบอกว่าใช้ได้วันละเท่าไหร่ถึงสิ้นเดือน</i>")

    actual = _to_float(nums[0])
    today = db.now_th().date()
    _, end = month_bounds()
    days_left = (date.fromisoformat(end) - today).days + 1

    lines = [f"<b>K-eSavings {actual:,.0f}฿</b>",
             f"เหลืออีก {days_left} วัน → ใช้ได้วันละ <b>{actual / max(days_left, 1):,.0f}฿</b>"]

    # เทียบกับครั้งก่อน ว่าเงินที่หายไปตรงกับที่จดไว้มั้ย
    prev = db.get_state(conn, "kes_balance")
    prev_at = db.get_state(conn, "kes_balance_at")
    if prev and prev_at:
        dropped = float(prev) - actual
        logged = db.spend_since(conn, prev_at)
        gap = dropped - logged
        lines.append(f"\nตั้งแต่เช็กครั้งก่อน ({fmt_date(prev_at[:10])})")
        lines.append(f"เงินหายไป {dropped:,.0f}฿ · จดไว้ {logged:,.0f}฿")
        if abs(gap) < 20:
            lines.append("✅ ตรงกัน")
        elif gap > 0:
            lines.append(f"มี {gap:,.0f}฿ ที่ยังไม่ได้จด")
            if int(prev_at[8:10]) <= 2 <= today.day or today.day <= 2:
                lines.append("<i>นับค่าผ่อนมือถือ + YouTube 828฿ ที่ตัดวันที่ 2 ด้วยหรือยัง</i>")
        else:
            lines.append(f"จดเกินไป {-gap:,.0f}฿ · มีเงินเข้าบัญชีเพิ่มหรือเปล่า")

    db.set_state(conn, "kes_balance", actual)
    db.set_state(conn, "kes_balance_at", db.now_th().isoformat(timespec="seconds"))
    lines.append("\n" + text_spend(conn))
    return send(chat_id, "\n".join(lines))


# ---------------------------------------------------------------- กองเที่ยว
#
# กติกาที่เจ้าของตั้งเอง (10 พ.ย. 2026)
#   1) เที่ยวด้วยเงินตัวเองเท่านั้น ห้ามขอพ่อแม่
#   2) ต้องใช้เงินจาก "กองเที่ยว" (K-ePocket) เท่านั้น ห้ามแตะกองอื่น
#   ถ้าไม่ผ่านกติกานี้ ต่อให้น่าไปแค่ไหนก็ไม่ไป
#
# ทำไมต้องมีคำสั่งนี้: ตอนเจอตั๋วถูกจะตื่นเต้นแล้วดูแค่ค่าตั๋ว
# แต่ค่าตั๋วเป็นแค่ครึ่งเดียวของทริป (ยังมีที่พัก กิน เดินทาง)
# และเงินในกองตอนนี้ไม่เท่ากับเงินในกองตอนเดินทาง
# บอทจึงคิดให้ทั้งสองจังหวะ: ตอนจอง (ต้องจ่ายค่าตั๋วได้จากยอดที่มีจริงวันนี้)
# กับตอนไป (ยอดวันนี้ + ที่จะเก็บเพิ่มทุกวันที่ 1 ต้องพองบรวม)
#
# ธนาคารไม่มี API ให้ดึงยอด จึงใช้วิธีเดียวกับ /เหลือ คือเจ้าของเปิดแอปอ่านเลขมาให้

# 3,500 = ช่อง K-ePocket ในแผนการเงิน 20 ต.ค. 2026 · เปลี่ยนได้ด้วย /เที่ยว เดือนละ 5000
TRIP_MONTHLY = float(ENV.get("TRIP_MONTHLY", "3500"))
# เหลือเงินหลังทริปน้อยกว่านี้ (สัดส่วนของงบรวม) = ไปได้แต่เฉียด
# ทริปต่างประเทศมีค่าที่ไม่ได้คิดไว้เสมอ เช่น ค่าแท็กซี่ตอนรถไฟหมด
TRIP_MARGIN = 0.10


def parse_trip_month(word: str, today: date):
    """
    "6/70" "6/2570" "6/27" "6/2027" → date(2027, 6, 1)

    รับได้ทั้ง พ.ศ. และ ค.ศ. เพราะเจ้าของใช้ พ.ศ. ในแผนการเงิน
    แต่แอปจองตั๋วโชว์ ค.ศ. — ปีสองหลัก 60 ขึ้นไปถือเป็น พ.ศ. (2560+)
    ต่ำกว่านั้นเป็น ค.ศ. (2000+) ไม่มีทางชนกันในช่วงชีวิตที่ใช้บอทนี้
    คืน None ถ้าอ่านไม่ออก หรือเป็นเดือนที่ผ่านไปแล้ว
    """
    m = re.fullmatch(r"(\d{1,2})/(\d{2}|\d{4})", word)
    if not m:
        return None
    month, year = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        return None
    if year < 100:
        year = 2500 + year if year >= 60 else 2000 + year
    if year > 2400:
        year -= 543
    d = date(year, month, 1)
    if d < today.replace(day=1):
        return None
    return d


def deposits_until(today: date, trip_month: date) -> int:
    """
    นับว่าจะมีเงินเข้ากองอีกกี่ครั้งก่อนเดินทาง (เข้าทุกวันที่ 1)

    ไม่นับเดือนนี้ เพราะถือว่าวันที่ 1 เดือนนี้โอนไปแล้ว และอยู่ในยอดที่อ่านมาแล้ว
    นับเดือนที่เดินทางด้วย เพราะเงินเข้าวันที่ 1 ก่อนวันบิน
    (ถ้าบินวันที่ 1 พอดีจะนับเกินไปเดือนหนึ่ง — ยอมรับได้ เพราะบอทบอกเดือนที่เงินพอไว้ให้แล้ว)
    """
    months = (trip_month.year - today.year) * 12 + (trip_month.month - today.month)
    return max(0, months)


def _th_month(d: date) -> str:
    return f"{TH_MONTHS[d.month - 1]}{(d.year + 543) % 100:02d}"


def _add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def handle_trip(conn, chat_id, words):
    """
    /เที่ยว                      ดูยอดกองเที่ยว + คาดว่าเดือนไหนจะมีเท่าไหร่
    /เที่ยว 10500                บันทึกยอด K-ePocket ที่อ่านจากแอป
    /เที่ยว 13925 32000 6/70     ตั๋ว 13,925 งบรวม 32,000 ไปเดือน มิ.ย. 70 → ไปได้มั้ย
    /เที่ยว เดือนละ 5000         เปลี่ยนยอดที่เก็บเข้ากองต่อเดือน
    """
    today = db.now_th().date()
    args = words[1:]
    monthly = float(db.get_state(conn, "trip_monthly", TRIP_MONTHLY))
    saved = db.get_state(conn, "trip_balance")
    saved_at = db.get_state(conn, "trip_balance_at") or ""

    def number(w):
        # float() รับ "nan" กับ "inf" ด้วย ถ้าหลุดเข้าไปตัวเลขทั้งข้อความจะเพี้ยน
        v = _to_float(w)
        return v if v is not None and math.isfinite(v) else None

    # ---- เปลี่ยนยอดเก็บต่อเดือน
    if args and args[0] in ("เดือนละ", "ต่อเดือน", "monthly"):
        v = number(args[1]) if len(args) > 1 else None
        if v is None or v < 0:
            return send(chat_id, "ใช้แบบนี้: <code>/เที่ยว เดือนละ 5000</code>")
        db.set_state(conn, "trip_monthly", v)
        return send(chat_id,
                    f"ตั้งเก็บเข้ากองเที่ยว <b>เดือนละ {v:,.0f}฿</b> แล้ว "
                    f"(เดิม {monthly:,.0f}฿)\n"
                    "<i>อย่าลืมแก้ยอดโอนอัตโนมัติในแอปกสิกรด้วย "
                    "และเงินส่วนที่เพิ่มคือเงินที่ลง VOO น้อยลง</i>")

    trip_month = None
    rest = []
    for w in args:
        if "/" in w:
            trip_month = parse_trip_month(w, today)
            if trip_month is None:
                return send(chat_id,
                            f"อ่านเดือน <code>{html.escape(w)}</code> ไม่ออก "
                            "หรือเป็นเดือนที่ผ่านไปแล้ว\n"
                            "เขียนเป็น เดือน/ปี เช่น <code>6/70</code> หรือ <code>6/2027</code>")
        else:
            rest.append(w)
    nums = [number(w) for w in rest]
    if any(v is None for v in nums):
        return send(chat_id, HELP_TRIP)

    # ---- บันทึกยอดกอง
    if len(nums) == 1 and trip_month is None:
        bal = nums[0]
        if bal < 0:
            return send(chat_id, "ยอดในกองติดลบไม่ได้ครับ")
        db.set_state(conn, "trip_balance", bal)
        db.set_state(conn, "trip_balance_at", db.now_th().isoformat(timespec="seconds"))
        msg = f"บันทึกยอดกองเที่ยว <b>{bal:,.0f}฿</b> แล้ว"
        if saved is not None:
            diff = bal - float(saved)
            msg += f"\n<i>ครั้งก่อน {float(saved):,.0f}฿ ({fmt_date(saved_at[:10])}) " \
                   f"→ {diff:+,.0f}฿</i>"
            if diff < 0:
                msg += "\n⚠️ <b>ยอดลดลง</b> — ถ้าไม่ได้จ่ายค่าทริป แปลว่ามีการดึงเงินกองเที่ยวไปใช้"
        return send(chat_id, msg + "\n\n" + text_trip(conn))

    # ---- เช็กทริป
    if len(nums) == 2 and trip_month is not None:
        if saved is None:
            return send(chat_id, "ยังไม่รู้ยอดในกองเที่ยว เปิดแอปกสิกรดู K-ePocket "
                                 "แล้วพิมพ์ <code>/เที่ยว 10500</code> ก่อนครับ")
        ticket, total = nums
        if ticket <= 0 or total <= 0:
            return send(chat_id, "ค่าตั๋วกับงบรวมต้องมากกว่า 0 ครับ")
        if ticket > total:
            # สลับลำดับกันบ่อย — งบรวมต้องรวมค่าตั๋วอยู่แล้ว จึงต้องมากกว่าเสมอ
            ticket, total = total, ticket
        return send(chat_id, trip_verdict(float(saved), saved_at, monthly,
                                          ticket, total, trip_month, today))

    if not args:
        return send(chat_id, text_trip(conn) + "\n\n" + HELP_TRIP)
    return send(chat_id, HELP_TRIP)


HELP_TRIP = """<b>กองเที่ยว</b>
<code>/เที่ยว 10500</code> บอกยอด K-ePocket จากแอป
<code>/เที่ยว 13925 32000 6/70</code> ตั๋วไปกลับ 13,925 · งบทั้งทริป 32,000 · ไป มิ.ย. 70
<code>/เที่ยว เดือนละ 5000</code> เปลี่ยนยอดเก็บต่อเดือน

<i>งบทั้งทริป = ตั๋ว + ที่พัก + กิน + เดินทาง + ค่าเข้า + ประกัน + เสื้อผ้าที่ต้องซื้อเพิ่ม
ปีเขียนเป็น พ.ศ. หรือ ค.ศ. ก็ได้ (6/70 = 6/2027)</i>"""


def text_trip(conn) -> str:
    today = db.now_th().date()
    monthly = float(db.get_state(conn, "trip_monthly", TRIP_MONTHLY))
    saved = db.get_state(conn, "trip_balance")
    if saved is None:
        return ("<b>กองเที่ยว</b> ยังไม่ได้บอกยอด\n"
                "เปิดแอปกสิกรดู K-ePocket แล้วพิมพ์ <code>/เที่ยว 10500</code>")
    bal = float(saved)
    at = db.get_state(conn, "trip_balance_at") or ""
    lines = [f"<b>กองเที่ยว {bal:,.0f}฿</b> ({fmt_date(at[:10])}) · เก็บเดือนละ {monthly:,.0f}฿"]
    stale = stale_note(at, today)
    if stale:
        lines.append(stale)
    lines += ["", "<b>ถ้าเก็บตามนี้ไม่ขาด จะมี</b>"]
    for n in (1, 3, 6, 9, 12, 15):
        d = _add_months(today, n)
        lines.append(f"  ต้น {_th_month(d):<7} {bal + monthly * n:>8,.0f}฿")
    return "\n".join(lines)


def stale_note(at: str, today: date) -> str:
    # ยอดที่อ่านมาก่อนวันที่ 1 เดือนนี้ ยังไม่รวมเงินที่เพิ่งโอนเข้า
    # บอทไม่บวกเพิ่มเองเพราะไม่รู้ว่าโอนจริงหรือเปล่า — ให้คิดต่ำไว้ก่อนดีกว่าคิดเกิน
    if at and at[:7] < today.isoformat()[:7]:
        return ("<i>⚠️ ยอดนี้อ่านมาก่อนวันที่ 1 เดือนนี้ ยังไม่รวมเงินที่โอนเข้าเดือนนี้ "
                "— เปิดแอปแล้วบอกยอดใหม่จะแม่นกว่า</i>")
    return ""


def trip_verdict(bal, saved_at, monthly, ticket, total, trip_month, today) -> str:
    """คำตัดสินว่าทริปนี้ผ่านกติกากองเที่ยวมั้ย — แยกออกมาให้เทสต์เรียกตรงได้"""
    n = deposits_until(today, trip_month)
    at_trip = bal + monthly * n
    left = at_trip - total
    can_book = ticket <= bal
    can_go = total <= at_trip

    lines = [f"<b>ทริป {_th_month(trip_month)}</b> · ตั๋ว {ticket:,.0f}฿ · "
             f"งบทั้งทริป {total:,.0f}฿", ""]

    lines.append(f"{'✅' if can_book else '❌'} <b>ตอนจอง</b> กองมี {bal:,.0f}฿ "
                 f"{'พอ' if can_book else 'ไม่พอ'}จ่ายค่าตั๋ว {ticket:,.0f}฿")
    if not can_book:
        k = math.ceil((ticket - bal) / monthly) if monthly > 0 else None
        if k is not None and k <= n:
            lines.append(f"   → จองได้เร็วสุดต้น {_th_month(_add_months(today, k))} "
                         "<i>(ถ้าตั๋วยังไม่ขึ้นราคา)</i>")
        else:
            lines.append("   → เก็บไม่ทันจองก่อนเดินทาง")

    lines.append(f"{'✅' if can_go else '❌'} <b>ตอนไป</b> กองจะมี {at_trip:,.0f}฿ "
                 f"(ตอนนี้ {bal:,.0f} + {monthly:,.0f} × {n} เดือน)")
    if can_go:
        lines.append(f"   เหลือหลังทริป {left:,.0f}฿")
    else:
        lines.append(f"   ขาด <b>{-left:,.0f}฿</b>")
        if n > 0:
            need = (total - bal) / n
            lines.append(f"   ต้องเก็บเดือนละ {need:,.0f}฿ ถึงจะทัน "
                         f"(ตอนนี้ {monthly:,.0f})")
        if monthly > 0:
            k = math.ceil((total - bal) / monthly)
            lines.append(f"   ถ้าเก็บเท่าเดิม เงินพอตอนต้น {_th_month(_add_months(today, k))}")

    lines.append("")
    # จองตอนนี้ไม่ได้ แต่เก็บทันจองก่อนเดินทาง ≠ ไม่ไป
    # แค่ห้ามจองด้วยเงินกองอื่นไปก่อน ต้องรอให้กองเที่ยวถึงค่าตั๋วเอง
    book_k = math.ceil((ticket - bal) / monthly) if (not can_book and monthly > 0) else None
    wait_ok = book_k is not None and book_k <= n
    tight = left < total * TRIP_MARGIN
    tight_txt = (f"เหลือเผื่อไม่ถึง {TRIP_MARGIN:.0%} ของงบ "
                 "มีค่าที่ไม่ได้คิดไว้นิดเดียวก็ต้องแตะกองอื่น")
    if can_go and can_book and not tight:
        lines.append("<b>✅ ไปได้</b> ผ่านกติกากองเที่ยว")
    elif can_go and can_book:
        lines.append(f"<b>⚠️ ไปได้แต่เฉียด</b> {tight_txt}")
    elif can_go and wait_ok:
        lines.append(f"<b>⏳ ไปได้ แต่ยังจองตอนนี้ไม่ได้</b> รอกองถึงค่าตั๋วต้น "
                     f"{_th_month(_add_months(today, book_k))} แล้วเช็กราคาตั๋วอีกรอบ "
                     "ห้ามยืมกองอื่นมาจองก่อน")
        if tight:
            lines.append(f"⚠️ และ{tight_txt}")
    else:
        lines.append("<b>❌ ไม่ไป</b> — ไม่ผ่านกติกา: เงินกองเที่ยวเท่านั้น ห้ามใช้กองอื่น "
                     "ห้ามขอพ่อแม่")

    stale = stale_note(saved_at, today)
    if stale:
        lines += ["", stale]
    lines.append("<i>นับเฉพาะเงินของคุณ ส่วนของคนที่ไปด้วยให้เช็กกับกองของเขาเอง</i>")
    return "\n".join(lines)


def handle_token_move(conn, chat_id, text, cmd, words):
    """
    /โทเข้า 670 #ขายปืนที่บูธ   Token ที่ได้มาโดยไม่ได้ซื้อจากพ่อค้า
    /โทออก 46 #ของลูกค้าเก่า    Token ที่จ่ายออกโดยไม่ใช่ออเดอร์ที่จดไว้
    /ยกมา 200                  ยอด Token ที่มีอยู่ตอนเริ่มใช้ระบบ
    """
    note = None
    body = text
    if "#" in body:
        body, _, note = body.partition("#")
        note = note.strip() or None

    nums = [w for w in body.split()[1:] if _to_float(w) is not None]
    if not nums or _to_float(nums[0]) <= 0:
        return send(chat_id,
                    "<b>บันทึก Token ที่เข้า-ออก นอกเหนือจากการซื้อขายปกติ</b>\n\n"
                    "<code>/โทเข้า 670 #ขายปืนที่บูธ</code>\n"
                    "ขายของตัวเองที่บูธ ได้ Token เข้ามา\n\n"
                    "<code>/โทออก 46 #ของลูกค้าเก่า</code>\n"
                    "จ่าย Token ออกโดยไม่ได้อยู่ในออเดอร์ที่จด\n\n"
                    "<code>/ยกมา 200</code>\n"
                    "ยอดที่มีอยู่ตอนเริ่มใช้ระบบ")

    n = int(_to_float(nums[0]))
    kind = {"tokenin": "booth_in", "โทเข้า": "booth_in",
            "tokenout": "other_out", "โทออก": "other_out",
            "open": "open", "ยกมา": "open"}[cmd]
    signed = -n if kind == "other_out" else n
    day = ((db.now_th().date() - timedelta(days=1)).isoformat()
           if any(w.lower() in DAY_WORDS for w in words[1:]) else db.today_th())

    db.add_token_move(conn, signed, kind, note, day)
    label = {"booth_in": "ได้ Token เข้ามา", "other_out": "จ่าย Token ออก",
             "open": "ยอดยกมา"}[kind]
    bal = db.token_balance(conn)
    return send(chat_id,
                f"บันทึกแล้ว · {fmt_date(day)} · {label} <b>{n:,}</b> Token"
                + (f"\n<i>{html.escape(note)}</i>" if note else "")
                + f"\n\nตามที่จดไว้ ตอนนี้ควรมี <b>{bal['expected']:,}</b> Token"
                  f"\n<i>เช็กกับในเกมด้วย</i> <code>/เช็ค 735</code>")


def handle_token_check(conn, chat_id, words):
    """
    /เช็ค 735 — นับ Token ในเกมแล้วเทียบกับที่จดไว้

    นี่คือตัวจับว่ามีอะไรหลุดบ้าง เพราะ Token โกหกไม่ได้
    ถ้าตัวเลขไม่ตรง แปลว่าอย่างใดอย่างหนึ่ง
      - ลืมจดการขาย
      - กดซื้อของที่บูธแพงกว่า RAP (ตัวนี้เจอบ่อยสุด)
      - มี Token เข้าออกที่ยังไม่ได้บันทึก
    """
    nums = [w for w in words[1:] if w.isdigit()]
    if not nums:
        bal = db.token_balance(conn)
        return send(chat_id,
                    f"ตามที่จดไว้ ควรมี <b>{bal['expected']:,}</b> Token\n\n"
                    "เปิดเกมดูยอดจริงแล้วพิมพ์ <code>/เช็ค 735</code>\n"
                    "<i>บอทจะบอกว่าหายไปไหนเท่าไหร่</i>")
    bad = _count_sanity(int(nums[0]), [])
    if bad:
        return send(chat_id, bad)
    return send(chat_id, token_check_text(conn, int(nums[0])))


def token_check_text(conn, actual: int) -> str:
    """เทียบ Token จริงกับที่จด แล้วปรับยอด — ใช้ร่วมกันระหว่าง /เช็ค กับ /นับ"""
    bal = db.token_balance(conn)
    expected = bal["expected"]
    diff = actual - expected

    lines = [f"<b>ตรวจยอด Token</b>",
             f"ตามที่จดไว้ ควรมี   <b>{expected:,}</b>",
             f"ในเกมมีจริง        <b>{actual:,}</b>",
             f"ต่างกัน            <b>{diff:+,}</b>"]

    if diff == 0:
        lines.append("\n✅ ตรงเป๊ะ ไม่มีอะไรหลุด")
    elif diff < 0:
        used = bal["used"] or 1
        pct = abs(diff) / used * 100
        lines.append(f"\nหายไป {abs(diff):,} Token = {pct:.1f}% ของที่ส่งให้ลูกค้า")
        lines.append("สาเหตุที่เป็นไปได้ เรียงจากที่เจอบ่อยสุด")
        lines.append("1. กดซื้อของที่บูธแพงกว่า RAP (ปกติแพงกว่าราว 3-4%)")
        lines.append("2. ลืมจดการขายไปบางออเดอร์")
        lines.append("3. มี Token จ่ายออกที่ยังไม่ได้บันทึก → <code>/โทออก</code>")
    else:
        lines.append(f"\nเกินมา {diff:,} Token")
        # สาเหตุที่เจอบ่อยสุดคือของเหมาในบูธขายออก — เรื่องปกติ ไม่ใช่ความผิดพลาด
        # เดิมบอกให้ /โทเข้า ซึ่งไม่ต้องแล้ว เพราะบรรทัดปรับยอดด้านล่างจดให้แล้ว
        lines.append("<i>ปกติคือของในบูธขายออกไปกลายเป็น Token ไม่ต้องทำอะไร</i>")

    db.add_token_move(conn, diff, "adjust", f"ปรับตามยอดจริง {actual:,}")
    lines.append(f"\n<i>ปรับยอดในระบบเป็น {actual:,} แล้ว "
                 "ครั้งหน้าจะนับต่อจากนี้</i>")
    return "\n".join(lines)


def handle_purchase(conn, chat_id, text, cmd):
    """
    /ซื้อ 700 63       ซื้อ Token จากพ่อค้า — ได้ Token ทันที
    /เหมา 2297 130 7   รับของเหมามา — ได้ "ไอเทม" ต้องตั้งบูธย่อยก่อน Token ถึงเข้าตัว

    ทั้งสองแบบใช้รูปเดียวกันคือ  <ได้เท่าไหร่> <จ่ายกี่บาท>
    และทั้งสองแบบจะตั้งเรทที่ใช้อยู่ให้ด้วย รายการขายต่อจากนี้จะใช้เรทนี้เอง
    """
    is_lot = cmd in ("เหมา", "lot")
    parts = [w for w in text.split() if w.lower() not in DAY_WORDS]

    # ซื้อของเมื่อวานแล้วเพิ่งมาจด — ต้องลงวันให้ถูก ไม่งั้นยอดเงินเข้า-ออกคนละวัน
    bought_on = None
    for w in text.split()[1:]:
        if w.lower() in DAY_WORDS:
            bought_on = (db.now_th().date() - timedelta(days=1)).isoformat()
            break

    if len(parts) < 3:
        if is_lot:
            return send(chat_id,
                        "<b>รับของเหมามา</b> — พิมพ์ <code>/เหมา [RAP รวม] [บาทที่จ่าย] "
                        "[กี่ชิ้น]</code>\nเช่น <code>/เหมา 2297 130 7</code>\n\n"
                        "<i>ของเหมาได้มาเป็นไอเทม ยังไม่ใช่ Token — เอาไปตั้งบูธย่อยขายก่อน\n"
                        "ขายที่บูธได้แล้วค่อยพิมพ์</i> <code>/ย่อย 1800</code> "
                        "<i>เพื่อบันทึกว่าได้ Token จริงเท่าไหร่</i>")
        return send(chat_id,
                    "<b>ซื้อ Token</b> — พิมพ์ <code>/ซื้อ [Token ที่ได้] [บาทที่จ่าย]</code>\n"
                    "เช่น <code>/ซื้อ 700 63</code>")

    amount, baht = _to_float(parts[1]), _to_float(parts[2])
    count = int(_to_float(parts[3])) if len(parts) > 3 and _to_float(parts[3]) else None
    if amount is None or baht is None or amount <= 0 or baht <= 0:
        return send(chat_id, "ใส่เป็นตัวเลขบวกทั้งคู่ครับ")

    kind = "lot" if is_lot else "token"
    rate = amount * (1 - BOOTH_FEE) / baht if is_lot else amount / baht
    if not (parser_rate_ok(rate, is_lot)):
        return send(chat_id,
                    f"เรทคิดได้ {rate:.2f} Token/บาท ซึ่งอยู่นอกช่วงที่เป็นไปได้\n"
                    "<i>เช็กว่าสลับเลขกันมั้ย — ต้องเป็น</i> "
                    "<code>[Token/RAP ที่ได้] [บาทที่จ่าย]</code>")

    pid = db.insert_purchase(conn, kind, baht, int(amount),
                             item_count=count, bought_on=bought_on)
    # ตั้งเรทที่ใช้อยู่เฉพาะตอนซื้อ Token เท่านั้น
    # ของเหมายังไม่ใช่ Token ตอนนั้นยังไม่มีอะไรเข้ากระเป๋า ถ้าไปตั้งเรท 47
    # รายการขายที่ใช้ Token ปกติ (เรท 11) จะถูกคิดทุนต่ำกว่าจริงหลายเท่า
    if not is_lot:
        set_rate(conn, rate, f"ซื้อ Token #{pid}")

    when = f" · {fmt_date(bought_on)}" if bought_on else ""
    lines = [f"<b>บันทึกแล้ว #{pid}</b>{when} · จ่าย {baht:,.0f}฿"]
    if is_lot:
        # RAP ดิบคือเลขที่เห็นตอนกดซื้อ แต่บูธกิน 1% เลยได้ไม่เต็ม
        net = amount * (1 - BOOTH_FEE)
        lines.append(f"ได้ของ {count or '?'} ชิ้น RAP รวม {amount:,.0f}")
        lines.append(f"หักค่าธรรมเนียมบูธ {BOOTH_FEE:.0%} เหลือ ~{net:,.0f} Token")
        lines.append(f"เรทที่คาดว่าจะได้ <b>{rate:.2f}</b> Token/บาท")
        # เทียบเป็นเงินกับการซื้อ Token ตรงๆ ที่เรทพ่อค้าล่าสุด
        # ดีลใหญ่เรทดูต่ำ (เช่น 12.8) แต่ประหยัดได้หลายร้อย ถ้าโชว์แค่เรทจะดูเหมือนไม่คุ้ม
        mr = merchant_rate(conn)
        raw_cost = net / mr
        saved = raw_cost - baht
        if saved > 0:
            lines.append(f"ถ้าซื้อ Token เท่านี้จากพ่อค้า (เรท {mr:.2f}) ต้องจ่าย {raw_cost:,.0f}฿\n"
                         f"→ <b>ประหยัด {saved:,.0f}฿</b> ({rate / mr:.2f} เท่าของเรทพ่อค้า)")
        else:
            lines.append(f"⚠️ <b>แพงกว่าซื้อ Token จากพ่อค้าตรงๆ {-saved:,.0f}฿</b> "
                         f"(เรทพ่อค้า {mr:.2f})")
        # เรทเกิน 80 เกิดได้จริง (29 ก.ย. 2026 ได้ RAP 6,048 ในราคา 60฿)
        # แต่บ่อยครั้งเป็นเพราะในล็อตมีของ RAP ปั่น ขายจริงไม่ได้ตามเลข
        # ไม่บล็อก แค่เตือน — กำไรจริงนับจาก /นับ ซึ่งเห็นแต่ของที่ขายได้จริง
        # RAP ปั่นเลยไม่ทำให้กำไรเพี้ยน กระทบแค่เรทที่ "คาดว่าจะได้" บรรทัดนี้
        from parser import RATE_MAX
        if rate > RATE_MAX:
            lines.append(f"\n⚠️ <i>เรทสูงผิดปกติ (เกิน {RATE_MAX:g}) — ถ้าในล็อตมีของ RAP ปั่น\n"
                         "ไม่ต้องแก้ กำไรจริงนับจากของที่ขายออกได้จริงตอน /นับ</i>")
        lines.append("\n<i>ของเหมายังไม่ใช่ Token — เอาไปตั้งบูธได้เลย "
                     "ตั้งราคาเท่าไหร่ถาม</i> <code>/ตั้ง 670</code>\n"
                     "<i>ไม่ต้องจำว่าขายออกเท่าไหร่ ตอน</i> <code>/นับ</code> "
                     "<i>บอทนับเจอเองทั้งในบูธและในไอดี</i>")
    else:
        lines.append(f"ได้ {amount:,.0f} Token · เรท <b>{rate:.2f}</b> Token/บาท")

    if is_lot:
        # เรทที่ใช้อยู่ไม่เปลี่ยน เพราะยังไม่มี Token เข้ากระเป๋า
        lines.append(f"\n<i>เรทที่ใช้กับรายการขายยังเป็น "
                     f"{db.current_rate(conn, DEFAULT_RATE):.2f} เหมือนเดิม</i>\n"
                     f"<i>ถ้าขายของจากล็อตนี้ให้ลูกค้าตรงๆ ใส่เรทในบรรทัดเป็น</i> "
                     f"<code>{int(amount)}/{baht:.0f}</code>")
    else:
        lines.append(f"\nรายการขายต่อจากนี้จะคิดที่เรท <b>{rate:.2f}</b> "
                     f"ถ้าไม่ได้ระบุเรทในบรรทัด")
    return send(chat_id, "\n".join(lines))


def handle_callback(conn, cb):
    data = cb.get("data", "")
    chat_id = cb["message"]["chat"]["id"]
    api("answerCallbackQuery", callback_query_id=cb["id"])

    if data.startswith("r|"):
        _, date_str, reason = data.split("|", 2)
        db.mark_day(conn, date_str,
                    shop_open=0 if reason == "not_open" else 1,
                    no_sale_reason=reason)
        label = REASON_LABELS.get(reason, reason)
        send(chat_id, f"บันทึกแล้ว · {fmt_date(date_str)}: {label}")


# ---------------------------------------------------------------- งานตามเวลา

def text_month_close(conn) -> str:
    """ข้อความวันที่ 1 — ขั้นตอนโอนเงิน + ตรวจว่ายอดที่จดตรงกับยอดในบัญชีมั้ย"""
    start, end = month_bounds(-1)
    s = db.range_summary(conn, start, end)
    c = db.cash_summary(conn, start, end)

    p = c["profit_cash"]
    moved = db.transfer_total(conn, start, end)
    fixed = MONTHLY_TRANSFER + MONTHLY_DCA + KTB_FLOAT

    # เดิมทายยอดกรุงไทยว่า "ควรอยู่ราว ค้าง 1,000 + กำไร" แล้วบอกให้โอน "กำไร − 4,328" เข้าเป้า
    # พังตั้งแต่เดือนแรก (ก.ย. 2026) เพราะ
    #   1) ไม่ได้หักเงินที่ /โอน ออกไประหว่างเดือน (ก.ย. ย้ายออก 10,230)
    #   2) ต้นเดือนกรุงไทยไม่ได้มี 1,000 พอดี (ก.ย. เริ่มที่ 697 + เงินนอกร้านที่เข้ามา)
    # บอทเลยทายว่าควรมี ~16,500 ทั้งที่จริงมี ~9,000 — ดูเหมือนเงินหาย ทั้งที่ไม่ได้หาย
    #
    # บอทไม่รู้ยอดต้นเดือนจริง จึงไม่ทายยอดอีกแล้ว ให้เจ้าของเปิดแอปดูเลขจริง
    # แล้วแบ่งจากเลขนั้นตามสูตรในชีตหน้าเดียว — ตรงกับที่ต้องโอนจริงเสมอ
    lines = [
        f"<b>วันที่ 1 แล้ว · ปิดเดือน {TH_MONTHS[int(start[5:7]) - 1]}</b>",
        "",
        f"ลูกค้าโอนเข้า {c['cash_in']:,.0f}฿ · จ่ายซื้อของ {c['cash_out']:,.0f}฿ "
        f"(Token {c['cash_out_token']:,.0f} + เหมา {c['cash_out_lot']:,.0f})",
        f"<b>กำไรเงินสดจริง = {p:,.0f}฿</b> "
        f"(ขาย {s['orders']} ครั้ง · เปิดร้าน {s['open_days']} วัน)",
    ]
    if moved:
        lines.append(f"<i>ระหว่างเดือนย้ายออกไปแล้ว {moved:,.0f}฿ "
                     f"— กำไรส่วนนั้นไม่ได้อยู่ในกรุงไทยแล้ว</i>")
    lines += [
        "",
        "<b>1. เปิดแอปกรุงไทย ดูยอดจริง</b>",
        "เช็กก่อนว่ากวาดเงินจาก TrueMoney เข้ามาหมดแล้ว",
    ]

    # กำไรที่คิดรายออเดอร์ มักสูงกว่ากำไรเงินสด เพราะของเหมาที่ซื้อมายังย่อยขายไม่หมด
    # gap = รายออเดอร์ − เงินสด · สองทิศมีสาเหตุคนละแบบ อธิบายสลับกันจะชวนเข้าใจผิด
    if abs(c["gap"]) >= 50:
        why = ("ของที่ซื้อมาแล้วยังขายไม่ออก" if c["gap"] > 0 else
               "ขายของจาก Token ที่มีอยู่ก่อนเดือนนี้ หรือที่เจอเพิ่มตอน /เช็ค "
               "(ไม่ได้จ่ายเงินซื้อในเดือนนี้)")
        lines += [
            "",
            f"<i>หมายเหตุ: กำไรที่คิดรายออเดอร์ได้ {c['profit_attributed']:,.0f}฿ "
            f"ต่างจากเงินสดจริง {c['gap']:+,.0f}฿</i>",
            f"<i>ส่วนต่างนี้มาจาก{why} ไม่ใช่การจดผิด</i>",
        ]

    return "\n".join(lines + [
        "",
        "<b>2. โอนตามชีต</b>",
        f"· {MONTHLY_TRANSFER:,.0f}฿ → K-eSavings",
        f"· {MONTHLY_DCA:,.0f}฿ → DCA",
        f"· ค้างกรุงไทยไว้ {KTB_FLOAT:,.0f}฿ เสมอ",
        f"· ที่เหลือ = <b>ยอดจริง − {fixed:,.0f}</b> → เป้าที่ทำอยู่",
        f"  <i>เช่น ยอดจริง 9,500 → เข้าเป้า {max(9500 - fixed, 0):,.0f}฿</i>",
        "<i>ยอดจริงไม่ถึง "
        f"{fixed:,.0f} = เดือนที่ขายน้อย โอน K-eSavings ก่อน ที่เหลือค่อยเติมทีหลัง</i>",
        "",
        "<b>3. ห้ามลืม</b>",
        "ขายดีแค่ไหนก็โอนเท่าเดิม ห้ามขึ้นเงินใช้ส่วนตัว",
    ])


def nightly_target(now) -> date:
    """
    วันที่ที่ข้อความสรุปตอนกลางคืนพูดถึง
    ตั้งเวลาไว้ก่อนตี 5 = พูดถึงวันที่เพิ่งผ่านไป (เช่น สรุปตอนเที่ยงคืนวันที่ 17 = ยอดของวันที่ 16)
    """
    d = now.date()
    return d - timedelta(days=1) if NIGHTLY_HOUR < 5 else d


def run_scheduled_jobs(conn):
    now = db.now_th()

    # สรุปประจำคืน — ยิงในช่วง 5 ชั่วโมงหลังเวลาที่ตั้งไว้
    # (ไม่ใช่ "หลังจากเวลานั้นตลอดไป" ไม่งั้นเปิดบอทตอนเย็นแล้วเด้งทันที)
    target = nightly_target(now).isoformat()
    key = f"nightly:{target}"
    if NIGHTLY_HOUR <= now.hour < NIGHTLY_HOUR + 5 and not db.job_already_ran(conn, key):
        s = db.day_summary(conn, target)
        if s["orders"] == 0 and not s["no_sale_reason"]:
            push(f"{fmt_date(target)} ยังไม่มีการขาย · เพราะอะไรครับ?\n"
                 "<i>กดตอบ 1 ที — ข้อมูลนี้คือคำตอบของโจทย์หลักเลย</i>\n"
                 f"<i>ถ้าเพิ่งขายดึกไป พิมพ์</i> <code>เมื่อวาน 55 192</code>",
                 reason_buttons(target))
        else:
            msg = text_today(conn, target)
            if now.weekday() == (6 if NIGHTLY_HOUR >= 5 else 0):  # สรุปสัปดาห์ที่เพิ่งจบ
                msg += "\n\n" + text_week(conn, target)

            # ถามจำนวนคนทักทุกคืน
            #
            # ทำไมต้องถามตรงนี้ ไม่ปล่อยให้จดเอง
            # เก็บข้อมูลมา 13 วัน ไม่เคยมีใครใส่เลขคนทักเลยสักวัน (0/13)
            # ทั้งที่ close_rate_pct มีอยู่ในสคีมาตั้งแต่แรก
            # ช่องที่ต้องนึกได้เองว่าต้องกรอก จะไม่มีใครกรอก — ต้องถาม
            #
            # ตัวเลขนี้สำคัญเพราะเป็นตัวเดียวที่แยกได้ว่าวันแย่เกิดจาก
            # "ไม่มีคนทัก" หรือ "ทักแล้วปิดการขายไม่ได้" ซึ่งแก้คนละวิธีสิ้นเชิง
            if db.day_summary(conn, target)["inquiries"] is None:
                msg += (f"\n\n<b>วันนี้มีคนทักกี่คน</b> "
                        f"(นับคร่าวๆ ก็ได้)\n"
                        f"<i>พิมพ์</i> <code>/ทัก 12</code>\n"
                        f"<i>ตัวเลขนี้จะบอกได้ว่าวันที่ได้น้อย "
                        f"เพราะคนทักน้อย หรือทักแล้วปิดไม่ได้</i>")

            msg += "\n\n<i>ขายดึกหลังเที่ยงคืน พิมพ์</i> <code>เมื่อวาน 55 192</code>"
            push(msg)
        db.mark_job_ran(conn, key)

    # ตามเก็บวันที่บอทไม่ได้เปิด เลยไม่ได้ถามสาเหตุไว้
    key = f"catchup:{now.strftime('%Y-%m-%d')}"
    if now.hour >= 10 and not db.job_already_ran(conn, key):
        start = (now.date() - timedelta(days=7)).isoformat()
        gaps = [d for d in db.days_missing_reason(conn, start, target) if d != target]
        if gaps:
            push(f"ค้างอยู่ {len(gaps)} วันที่ยังไม่ได้ระบุสาเหตุ · "
                 f"เริ่มจาก <b>{fmt_date(gaps[0])}</b>", reason_buttons(gaps[0]))
        db.mark_job_ran(conn, key)

    # วันที่ 1 ของเดือน
    key = f"monthly:{now.strftime('%Y-%m')}"
    if now.day == 1 and now.hour >= MONTHLY_HOUR and not db.job_already_ran(conn, key):
        push(text_month_close(conn))
        db.mark_job_ran(conn, key)


# ---------------------------------------------------------------- ลูปหลัก

def handle_update(conn, update):
    """
    จัดการข้อความ 1 อันจาก Telegram — แยกออกมาเพื่อให้กัน error ได้ทีละข้อความ

    ทำไมต้องกันตรงนี้: เดิม error ในคำสั่งไหนก็ตาม จะเด้งไปถึง except ตัวนอกสุด
    ซึ่งแค่พิมพ์ลง log แล้ววนต่อ แต่ offset ขยับไปแล้ว = ข้อความนั้นหายเงียบ
    เจ้าของเห็นแค่ว่าบอทไม่ตอบ ไม่รู้เลยว่ายังไม่ได้บันทึก (28 ก.ย. 2026 เจอจริง)
    """
    if "callback_query" in update:
        cb = update["callback_query"]
        try:
            handle_callback(conn, cb)
        except Exception:
            traceback.print_exc()
            _tell_error(cb.get("message", {}).get("chat", {}).get("id"), "กดปุ่ม")
        return

    # แก้ข้อความใน Telegram = Telegram ส่งข้อความเดิมมาใหม่ทั้งก้อน
    # เดิมบอทบันทึกซ้ำอีกรอบ: จด "55 192" แล้วแก้เป็น "55 195" = ได้ 2 ออเดอร์
    # ของที่บันทึกไปแล้วแก้ย้อนจากตรงนี้ไม่ได้อย่างปลอดภัย จึงไม่ทำอะไร แค่บอกวิธี
    if "edited_message" in update:
        msg = update["edited_message"]
        if _is_owner(msg.get("chat", {}).get("id")):
            send(msg["chat"]["id"],
                 "✏️ แก้ข้อความใน Telegram <b>ไม่มีผลกับที่บันทึกไปแล้ว</b>\n"
                 "<i>ถ้าจดผิด ใช้</i> <code>/undo</code> <i>แล้วจดใหม่ "
                 "หรือ</i> <code>/รายการ</code> <i>แล้ว</i> <code>/แก้</code>")
        return

    msg = update.get("message")
    if not msg or "text" not in msg:
        return
    chat_id = msg["chat"]["id"]
    if not CHAT_ID:
        print(f"➡️  CHAT_ID ของคุณคือ: {chat_id}")
    elif not _is_owner(chat_id):
        return  # ไม่รับข้อความจากคนอื่น

    try:
        handle_text(conn, chat_id, msg["text"])
    except Exception:
        traceback.print_exc()
        _tell_error(chat_id, msg["text"])


def _is_owner(chat_id) -> bool:
    return not CHAT_ID or str(chat_id) == CHAT_ID


def _tell_error(chat_id, what):
    """บอกเจ้าของว่าข้อความนี้ไม่ได้บันทึก — ส่งไม่ได้ก็ช่างมัน อย่าให้ล้มซ้อน"""
    if not chat_id:
        return
    try:
        send(chat_id,
             "❌ <b>บอทเจอข้อผิดพลาดระหว่างทำข้อความนี้ — อาจบันทึกไม่ครบ</b>\n"
             f"<code>{html.escape(str(what)[:200])}</code>\n"
             # ข้อความหลายบรรทัดอาจบันทึกไปแล้วบางบรรทัด พิมพ์ซ้ำทั้งก้อน = ได้ของซ้ำ
             "<i>เช็ก</i> <code>/รายการ</code> <i>ก่อนว่าอันไหนเข้าไปแล้ว "
             "แล้วค่อยพิมพ์เฉพาะที่ขาด · ถ้ายังพังอีก จดไว้ในโน้ตก่อน</i>")
    except Exception:
        traceback.print_exc()


def main():
    conn = db.connect()

    # ถ้ามีตัวแปร PORT แปลว่ากำลังรันบนเครื่องเช่า (Render ตั้งให้เอง)
    # ต้องเปิดพอร์ตรอ ไม่งั้น Render ถือว่าสตาร์ทไม่สำเร็จแล้วปิดทิ้ง
    # รันในคอมตัวเองจะไม่มีตัวแปรนี้ เลยไม่เปิดพอร์ตอะไรเลย
    port = os.environ.get("PORT")
    if port:
        import health
        health.start(int(port))
        print(f"เปิดพอร์ต {port} รอให้เครื่องเช่าตรวจแล้ว")

    me = api("getMe")
    if not me.get("ok"):
        sys.exit("ต่อ Telegram ไม่ได้ — เช็ก BOT_TOKEN ใน .env")
    print(f"บอททำงานแล้ว: @{me['result']['username']}")
    print(f"ฐานข้อมูล: {db.describe_backend()}")
    if not CHAT_ID:
        print("⚠️  ยังไม่ได้ตั้ง CHAT_ID — ทักบอทใน Telegram 1 ครั้ง "
              "แล้วเอาเลขที่ขึ้นตรงนี้ไปใส่ .env")

    offset = None
    warned_conflict = False
    conflict_seen = 0          # นับจำนวนรอบที่ชนติดกัน ดูเหตุผลตรงที่เช็ก 409
    while True:
        try:
            resp = requests.get(f"{API}/getUpdates",
                                params={"offset": offset, "timeout": 25},
                                timeout=40).json()

            # Telegram ส่งข้อความให้ผู้ดึงได้ทีละเครื่องเท่านั้น
            # ถ้ามีบอทตัวที่สองมาดึงพร้อมกัน จะได้ error 409 กลับมา
            #
            # เดิมโค้ดอ่านแต่ resp["result"] ซึ่งตอน 409 จะเป็นค่าว่าง
            # บอทเลยวนรอเงียบๆ เหมือนไม่มีใครทัก ทั้งที่ข้อความถูกอีกตัวรับไปแล้ว
            # เกิดขึ้นจริง 27 ก.ย. 2026 — บอทเก่าจาก 25 ก.ย. ยังรันค้างอยู่
            # แล้วมาแย่งข้อความ ทำให้คำสั่งใหม่ถูกตอบว่า "ไม่รู้จักคำสั่ง"
            # อาการแบบนี้หลอกกว่าบอทเงียบ เพราะดูเหมือนบอททำงานอยู่
            if not resp.get("ok"):
                code = resp.get("error_code")
                desc = resp.get("description", "")
                if code == 409:
                    # นับก่อนเตือน อย่าเตือนตั้งแต่ครั้งแรก
                    #
                    # ทุกครั้งที่ push โค้ดขึ้น GitHub เครื่องเช่าจะ deploy ใหม่
                    # แล้วตัวใหม่กับตัวเก่าจะทำงานทับกันราว 10-30 วินาที
                    # ซึ่งเป็นเรื่องปกติและหายเอง ไม่ใช่ปัญหาที่เจ้าของต้องทำอะไร
                    # 28 ก.ย. 2026 เจอจริง — deploy เสร็จแล้ว push อีกคอมมิต
                    # เจ้าของได้ข้อความเตือน 2 อันทั้งที่ไม่มีอะไรผิด
                    #
                    # เตือนทุกครั้งที่ชน = เจ้าของจะชินแล้วเลิกอ่าน
                    # ซึ่งอันตรายกว่าไม่เตือนเลย เพราะวันที่ชนกันจริงจะถูกมองข้าม
                    # รอให้ชนติดกัน 30 วินาทีก่อน (6 รอบ รอบละ 5 วินาที)
                    # deploy ทับกันจะหายก่อนถึงตรงนั้น ส่วนบอทซ้อนจริงจะชนไปเรื่อยๆ
                    conflict_seen += 1
                    if conflict_seen >= CONFLICT_BEFORE_WARN and not warned_conflict:
                        warned_conflict = True
                        print("\n" + "=" * 55)
                        print("⚠️  มีบอทตัวอื่นกำลังดึงข้อความด้วย token เดียวกัน")
                        print("    ข้อความที่พิมพ์จะสลับกันหาย ต้องเหลือตัวเดียว")
                        print("    ปิดหน้าต่าง run.bat อันอื่น หรือบอทที่รันบนคลาวด์")
                        print("=" * 55 + "\n")
                        push("⚠️ <b>มีบอทรันซ้อนกันอยู่</b>\n"
                             "ข้อความที่พิมพ์จะสลับกันหาย จดไปแล้วอาจไม่ถูกบันทึก\n"
                             "<i>ต้องเหลือบอททำงานตัวเดียวเท่านั้น</i>")
                    time.sleep(5)
                    continue
                if code == 401:
                    sys.exit("BOT_TOKEN ใช้ไม่ได้ — เช็กค่าใน .env")
                print(f"[Telegram ตอบกลับว่าไม่สำเร็จ] {code} {desc}")
                time.sleep(5)
                continue

            if warned_conflict:
                print("✅ ไม่มีตัวแย่งข้อความแล้ว บอททำงานต่อตามปกติ")
                push("✅ <b>ไม่มีบอทซ้อนกันแล้ว</b> ทำงานต่อตามปกติ")
            warned_conflict = False
            conflict_seen = 0

            for update in resp.get("result", []):
                offset = update["update_id"] + 1

                handle_update(conn, update)

            run_scheduled_jobs(conn)

        except requests.exceptions.RequestException as e:
            print(f"[เน็ตมีปัญหา] {e} — รอ 5 วินาทีแล้วลองใหม่")
            time.sleep(5)
        except KeyboardInterrupt:
            print("\nปิดบอทแล้ว")
            break
        except Exception:
            traceback.print_exc()
            time.sleep(3)


if __name__ == "__main__":
    main()
