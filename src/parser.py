"""
ตัวแปลข้อความสั้นให้เป็นรายการขาย

เป้าหมายคือ "จดให้เร็วที่สุด" — พิมพ์บรรทัดเดียวจบ และพิมพ์รวดเดียวหลายบรรทัดได้
เพราะเจ้าของจดทีเดียวตอนก่อนนอน ไม่ได้จดทีละออเดอร์

รูปแบบ:  [วันที่] <ราคาขาย> <Token ที่จ่าย> [ตัวเลือกอื่นๆ สลับลำดับได้]

ตัวอย่าง
    55 192                 ได้เงิน 55 บาท กดของจากบูธไป 192 Token
                           (ราคาที่จ่ายจริง ไม่ใช่ Your Value ซึ่งเป็น RAP)
    55 192 10.5            ระบุเรทเองในบรรทัด
    150 565 x3             ออเดอร์นี้มี 3 ชิ้น
    80 900 2297/130 x3     ของที่รับเหมามา จ่าย 130 บาท ได้ RAP รวม 2,297
    เมื่อวาน 55 192         ขายเมื่อวาน (เช่น ขายดึกหลังเที่ยงคืนไปแล้ว)
    55 192 #Dual Hacker Scythe   เติมหมายเหตุ เช่น ชื่อไอเทม

เรื่องเรท — จุดที่สำคัญที่สุด
    ไม่ต้องหารเองเลย พิมพ์เรทเป็น "ได้กี่ Token / จ่ายกี่บาท" ตรงๆ ได้
        700/63     ซื้อ Token จากพ่อค้า 63 บาท ได้ 700 Token  -> 11.1
        2297/130   รับเหมาของมา 130 บาท RAP รวม 2,297         -> 17.7
    หรือจะพิมพ์เป็นตัวเลขเรทตรงๆ ก็ได้ เช่น 11 / 10.5 / 10 / 20
"""

import re
from datetime import date, timedelta

DEFAULT_RATE = 11.0     # เรทที่ซื้อบ่อยที่สุด ใช้เมื่อไม่ได้ระบุ
RATE_MIN, RATE_MAX = 5.0, 80.0

# ของเหมาได้เรทสูงกว่า 80 ได้จริง — 29 ก.ย. 2026 ได้ RAP 6,048 ในราคา 60฿ (เรท ~100)
# แต่บอทเดิมตีกลับว่า "นอกช่วงที่เป็นไปได้" จนจดไม่ได้
# เพดานนี้มีไว้จับแค่พิมพ์เลขศูนย์เกินเท่านั้น (60480 แทน 6048 → เรท 1,000)
# ส่วนพิมพ์สลับเลข เรทจะต่ำกว่า 1 ซึ่ง RATE_MIN จับได้อยู่แล้ว
LOT_RATE_MAX = 500.0

PRICE_MAX = 50_000          # บาทต่อออเดอร์
TOKENS_MAX = 5_000_000      # Token ต่อออเดอร์

# คั่นหลักพันด้วยลูกน้ำ: 8,340 หรือ 1,234,567 — ต้องเป็นกลุ่มละ 3 หลักพอดี
# "1,5" หรือ "12,34" ไม่ตรงรูปแบบ จะไม่ถูกแตะ แล้วไปฟ้องว่าอ่านตัวเลขไม่ออกตามเดิม
# ดีกว่าเดาว่าหมายถึง 1.5 หรือ 15 แล้วบันทึกผิดเงียบๆ
_THOUSANDS = re.compile(r"(?<![\d,])\d{1,3}(?:,\d{3})+(?![\d,])")


def strip_thousands(text: str) -> str:
    """ "/ซื้อ 8,340 758" → "/ซื้อ 8340 758" """
    return _THOUSANDS.sub(lambda m: m.group(0).replace(",", ""), text)

# พ่อค้า Token ให้เรทได้สูงสุดราว 11.1 (700 Token / 63 บาท)
# ถ้าเรทสูงกว่านี้มาก แปลว่าไม่ได้ซื้อ Token แต่รับของเหมามาย่อยขายเอง
HOT_RATE_THRESHOLD = 13.0

# เคยมี CATEGORY_WORDS (ดาบ/ระเบิด/ท่า) กับ GROUP_WORDS (กลุ่ม a/b) ตรงนี้
# ถอดออก 27 ก.ย. 2026 เพราะจดมา 89 ออเดอร์ ไม่เคยมีใครใส่เลยสักครั้ง (0%)
#
# สาเหตุไม่ใช่ขี้เกียจ แต่เป็นเพราะข้อกำหนดข้อแรกคือ "จดให้เร็วที่สุด"
# พิมพ์ 55 192 ใช้ 2 วินาที · พิมพ์ 55 192 ดาบ a ใช้ 5 วินาที
# คูณ 89 ครั้ง ความเร็วชนะทุกครั้ง และมันควรชนะ
# เพราะถ้าจดช้าจนเลิกจด ข้อมูลจะเป็นศูนย์
#
# ช่องที่ไม่มีใครกรอก แย่กว่าไม่มีช่อง เพราะทำให้เข้าใจผิดว่าวิเคราะห์ได้
# ถ้าวันไหนอยากรู้จริงๆ ค่อยเพิ่มกลับ ตอนนั้นจะมีเหตุผลรองรับ

# บัญชีที่เงินเข้า — ไม่ต้องพิมพ์ถ้าเข้ากรุงไทยตามปกติ
#
# ต่างจาก category/fb_group ที่ถอดออกไป ตรงที่อันนี้ "มีค่าปริยายที่ถูกเกือบทุกครั้ง"
# เงินเกือบทั้งหมดเข้ากรุงไทย จึงพิมพ์เฉพาะตอนเป็นข้อยกเว้น = ไม่เพิ่มเวลาจดเลย
# ส่วน category ไม่มีค่าปริยายที่ถูก ต้องพิมพ์ทุกครั้ง จึงไม่มีใครพิมพ์
#
# ที่ต้องมี: 27 ก.ย. 2026 ใช้เวลาเป็นชั่วโมงไล่ยอดว่าเงินก้อนไหนเข้าบัญชีไหน
# และไล่ผิด 3 รอบ เพราะไม่มีใครจดไว้
ACCOUNT_WORDS = {
    "ktb": "ktb", "กรุงไทย": "ktb", "กท": "ktb",
    "true": "truemoney", "ทรู": "truemoney", "ทรูมันนี่": "truemoney",
    "kbank": "kbank", "kb": "kbank", "กสิกร": "kbank",
    "dime": "dime", "ดายม์": "dime",
    "cash": "cash", "สด": "cash", "เงินสด": "cash",
}

# ของที่รับเหมามาเป็นชุด แล้วเอามาย่อยขาย — ได้เรทดีกว่าซื้อ Token ปกติมาก
HOT_WORDS = {"ร้อน", "ของร้อน", "เหมา", "รับเหมา", "hot", "hotlot"}

YESTERDAY_WORDS = {"เมื่อวาน", "มว", "y", "ytd"}

class ParseError(ValueError):
    pass


def _to_number(text):
    """แปลงเป็นตัวเลข คืน None ถ้าไม่ใช่ตัวเลข"""
    try:
        return float(text)
    except ValueError:
        return None


def parse_rate(word: str):
    """
    อ่านเรท Token คืน (เรท, ข้อความต้นทาง) หรือ None ถ้าไม่ใช่เรท

    รับได้ 2 แบบ
        "10.5"      เรทตรงๆ
        "2297/130"  ได้ 2,297 Token จ่าย 130 บาท -> 17.67
    """
    if "/" in word:
        left, _, right = word.partition("/")
        tokens, baht = _to_number(left), _to_number(right)
        if tokens is None or baht is None:
            return None
        if baht <= 0 or tokens <= 0:
            raise ParseError(f"เรท '{word}' ต้องเป็นตัวเลขบวกทั้งคู่")
        return tokens / baht, word

    n = _to_number(word)
    return (n, None) if n is not None else None


def _parse_date_prefix(word: str, today: date):
    """
    อ่านวันที่ที่อยู่หน้าสุดของบรรทัด คืน date หรือ None ถ้าไม่ใช่วันที่

        เมื่อวาน / มว / y   = เมื่อวาน
        d15 / วันที่15       = วันที่ 15 (เดือนนี้ หรือเดือนก่อนถ้าเลยมาแล้ว)
    """
    low = word.lower()
    if low in YESTERDAY_WORDS:
        return today - timedelta(days=1)

    m = re.fullmatch(r"(?:d|วันที่)(\d{1,2})", low)
    if m:
        day = int(m.group(1))
        if not 1 <= day <= 31:
            raise ParseError(f"วันที่ {day} ไม่มีอยู่จริง")
        if day <= today.day:
            return today.replace(day=day)
        # วันที่มากกว่าวันนี้ = ต้องเป็นเดือนที่แล้ว
        last_month_end = today.replace(day=1) - timedelta(days=1)
        if day > last_month_end.day:
            raise ParseError(f"เดือนที่แล้วไม่มีวันที่ {day}")
        return last_month_end.replace(day=day)

    return None


def parse_line(line: str, today: date = None, default_rate: float = None) -> dict:
    """
    แปลงข้อความ 1 บรรทัดเป็น dict ของการขาย 1 ออเดอร์

    default_rate = เรทที่ใช้เมื่อบรรทัดนั้นไม่ได้ระบุเรท
    (บอทจะส่งเรทจากคำสั่ง /ซื้อ หรือ /เหมา ล่าสุดเข้ามา)
    """
    today = today or date.today()
    default_rate = DEFAULT_RATE if default_rate is None else default_rate
    line = strip_thousands(line).strip()
    if not line:
        raise ParseError("บรรทัดว่าง")

    # ตัดหมายเหตุที่ขึ้นต้นด้วย # ออกก่อน เพราะข้างในมีช่องว่างได้
    note = None
    if "#" in line:
        line, _, note = line.partition("#")
        note = note.strip() or None
        line = line.strip()

    parts = line.split()
    if not parts:
        raise ParseError("ไม่มีอะไรให้อ่าน")

    # วันที่ (ถ้ามี) ต้องอยู่หน้าสุด — เอาออกก่อนแล้วค่อยอ่านตัวเลขที่เหลือ
    sold_on = _parse_date_prefix(parts[0], today)
    if sold_on is not None:
        parts = parts[1:]
    else:
        sold_on = today

    if len(parts) < 2:
        raise ParseError("ต้องมีอย่างน้อย 2 ตัวเลข: ราคาขาย กับ Token ของไอเทม")

    price = _to_number(parts[0])
    tokens = _to_number(parts[1])
    if price is None:
        raise ParseError(f"อ่านราคาขายไม่ออก: '{parts[0]}'")
    if tokens is None:
        raise ParseError(f"อ่านจำนวน Token ไม่ออก: '{parts[1]}'")
    if price <= 0:
        raise ParseError("ราคาขายต้องมากกว่า 0")
    if tokens <= 0:
        raise ParseError("Token ต้องมากกว่า 0")
    # เพดานกันพิมพ์ผิด ไม่ใช่กฎธุรกิจ — ออเดอร์ใหญ่สุดที่เคยมีคือ 2,700฿ / 17,659 Token
    # ที่ต้องมีเพราะลูกน้ำ: "100,200 500" (ตั้งใจเว้นวรรค) ถูกอ่านเป็นขาย 100,200฿
    # และ Token เกิน 2,147,483,647 ทำให้ Postgres ปฏิเสธ (SQLite ในเทสต์ไม่ฟ้อง)
    if price > PRICE_MAX:
        raise ParseError(f"ราคา {price:,.0f}฿ สูงผิดปกติ (เกิน {PRICE_MAX:,}) "
                         f"— ถ้าพิมพ์ลูกน้ำแทนเว้นวรรค ให้ใช้เว้นวรรค")
    if tokens > TOKENS_MAX:
        raise ParseError(f"Token {tokens:,.0f} สูงผิดปกติ (เกิน {TOKENS_MAX:,})")

    sale = {
        "sold_on": sold_on.isoformat(),
        "price_baht": price,
        "tokens_spent": int(tokens),
        "token_rate": None,
        "source": "seller",
        "item_count": 1,
        "account": None,        # None = ใช้ค่าปริยาย (กรุงไทย)
        "note": note,
        "rate_from_default": False,
    }
    rate_expr = None
    extras = []

    for raw in parts[2:]:
        word = raw.lower()

        # x3 = มี 3 ชิ้นในออเดอร์นี้
        if re.fullmatch(r"x\d+", word):
            count = int(word[1:])
            # x0 ไม่มีความหมาย · x เกินพันคือพิมพ์ผิด และเกิน 2 พันล้าน Postgres ปฏิเสธ
            if not 1 <= count <= 1000:
                raise ParseError(f"จำนวนชิ้น {raw} ดูผิดปกติ (ควรอยู่ระหว่าง x1–x1000)")
            sale["item_count"] = count
            continue

        if word in HOT_WORDS:
            sale["source"] = "hot_lot"
            continue

        if word in ACCOUNT_WORDS:
            sale["account"] = ACCOUNT_WORDS[word]
            continue

        parsed = parse_rate(word)
        if parsed is not None:
            rate, expr = parsed
            # เขียนเป็น "6048/60" = ขายของจากล็อตเหมา ใช้เพดานเดียวกับ /เหมา
            # ส่วนเลขเรทเดี่ยวๆ อย่าง "120" น่าจะพิมพ์ผิดมากกว่า คงเพดาน 80 ไว้
            top = LOT_RATE_MAX if expr else RATE_MAX
            if not (RATE_MIN <= rate <= top):
                raise ParseError(
                    f"เรท {raw} คิดได้ {rate:.1f} Token/บาท ซึ่งดูผิดปกติ "
                    f"(ควรอยู่ระหว่าง {RATE_MIN:g}–{top:g})"
                )
            sale["token_rate"] = rate
            rate_expr = expr
            continue

        extras.append(raw)

    if sale["token_rate"] is None:
        sale["token_rate"] = default_rate
        sale["rate_from_default"] = True

    # เรทสูงกว่าที่พ่อค้า Token ให้ได้ = ต้องมาจากของที่รับเหมามา ติดป้ายให้เอง
    if sale["token_rate"] >= HOT_RATE_THRESHOLD:
        sale["source"] = "hot_lot"

    # เก็บที่มาของเรทไว้ในหมายเหตุ เพื่อให้ย้อนตรวจได้ว่าเรท 17.7 มาจากไหน
    bits = [b for b in (note, f"เรทจาก {rate_expr}" if rate_expr else None, *extras) if b]
    sale["note"] = " · ".join(bits) if bits else None

    return sale


def parse_message(text: str, today: date = None, default_rate: float = None):
    """
    แปลงข้อความทั้งก้อน (หลายบรรทัดได้)
    คืนค่า (รายการที่แปลสำเร็จ, รายการข้อผิดพลาด)
    บรรทัดไหนพัง ก็พังเฉพาะบรรทัดนั้น บรรทัดอื่นยังบันทึกได้ตามปกติ
    """
    sales, errors = [], []
    for i, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            sales.append(parse_line(line, today, default_rate))
        except ParseError as e:
            errors.append((i, line.strip(), str(e)))
    return sales, errors


def describe(sale: dict, today: date = None) -> str:
    """สรุปการขาย 1 รายการเป็นข้อความสั้นๆ พร้อมตัวเลขกำไร"""
    cost = sale["tokens_spent"] / sale["token_rate"]
    profit = sale["price_baht"] - cost

    bits = [f"{sale['price_baht']:,.0f}฿"]
    if sale["item_count"] > 1:
        bits.append(f"({sale['item_count']} ชิ้น)")
    bits.append(f"· {sale['tokens_spent']:,} Token @ {sale['token_rate']:.4g}")
    if sale["source"] == "hot_lot":
        bits.append("· รับเหมา")
    # บอกบัญชีเฉพาะตอนไม่ใช่กรุงไทย จะได้สังเกตเห็นว่าก้อนนี้เข้าที่อื่น
    if sale.get("account"):
        bits.append(f"· เข้า {sale['account']}")

    # บอกวันที่เฉพาะตอนที่ไม่ใช่วันนี้ จะได้เห็นชัดว่าลงย้อนหลังถูกวัน
    today = today or date.today()
    if sale.get("sold_on") and sale["sold_on"] != today.isoformat():
        d = date.fromisoformat(sale["sold_on"])
        bits.insert(0, f"[{d.day}/{d.month}]")

    head = " ".join(bits)
    # "กี่เท่า" ใช้ ราคาขาย ÷ ทุน ให้ตรงกับคอลัมน์ markup_x ใน v_sale
    return (f"{head}\n   ทุน {cost:,.1f}฿ → กำไร {profit:,.1f}฿ "
            f"(ขายได้ {sale['price_baht'] / cost:,.1f} เท่าของทุน)")
