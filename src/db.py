"""
ชั้นติดต่อฐานข้อมูล — ทุกคำสั่ง SQL อยู่ที่นี่ที่เดียว

ตั้งแต่ 26 ก.ย. 2026 ของจริงรันบน Postgres (Supabase) แล้ว
ส่วน SQLite ยังใช้อยู่ตอนรันเทสต์ เพราะเร็วและไม่ต้องต่อเน็ต
คนที่เลือกว่าจะต่ออันไหนคือ src/store.py ดูจากตัวแปร DATABASE_URL

SQL ในไฟล์นี้เป็น SQL มาตรฐานที่ทั้งสองฝั่งอ่านได้เหมือนกัน
จุดที่ต้องระวังตอนแก้ต่อ (เขียนไว้เพราะเคยเกือบพลาด):
  - ห้ามใช้ INSERT OR REPLACE / INSERT OR IGNORE ซึ่งมีแต่ใน SQLite
    ให้ใช้ ON CONFLICT ... DO UPDATE / DO NOTHING ที่ใช้ได้ทั้งสองฝั่ง
  - ห้ามใช้ cur.lastrowid ซึ่ง Postgres ไม่มี
    ให้ต่อท้ายคำสั่งด้วย RETURNING id แล้ว fetchone()[0]
  - ห้ามใช้ strftime / julianday ซึ่งมีแต่ใน SQLite
"""

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import store

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "ledger.db"   # ใช้เฉพาะตอนรันบน SQLite (เทสต์เขียนทับค่านี้)

# ไทยไม่มี daylight saving เลยใช้ค่าคงที่ UTC+7 ได้เลย
# (ดีกว่าใช้ zoneinfo เพราะบน Windows ต้องลงแพ็กเกจ tzdata เพิ่ม)
TH = timezone(timedelta(hours=7))


def now_th() -> datetime:
    """เวลาปัจจุบันตามเวลาไทย"""
    return datetime.now(TH)


def today_th() -> str:
    """วันที่วันนี้ตามเวลาไทย เป็น YYYY-MM-DD"""
    return now_th().strftime("%Y-%m-%d")


def connect():
    """เปิดการเชื่อมต่อ และสร้างตารางให้ถ้ายังไม่มี"""
    return store.connect(DB_PATH)


def describe_backend() -> str:
    """บอกว่าตอนนี้ต่ออยู่กับอะไร — ใช้พิมพ์ตอนบอทเริ่มทำงาน"""
    if store.backend() == "postgres":
        # ห้ามพิมพ์ DATABASE_URL ออกมา เพราะมีรหัสผ่านฐานข้อมูลอยู่ในนั้น
        return "Postgres (Supabase)"
    return f"SQLite {DB_PATH}"


# ---------------------------------------------------------------- การขาย

def insert_sale(conn, sale: dict) -> int:
    """บันทึกการขาย 1 ออเดอร์ คืนค่า id ที่เพิ่งสร้าง"""
    cur = conn.execute(
        """
        INSERT INTO sale (sold_on, logged_at, price_baht, tokens_spent,
                          token_rate, source, item_count, account, note)
        VALUES (:sold_on, :logged_at, :price_baht, :tokens_spent,
                :token_rate, :source, :item_count, :account, :note)
        RETURNING id
        """,
        {
            "sold_on": sale.get("sold_on") or today_th(),
            "logged_at": now_th().isoformat(timespec="seconds"),
            "price_baht": sale["price_baht"],
            "tokens_spent": sale["tokens_spent"],
            "token_rate": sale["token_rate"],
            "source": sale.get("source", "seller"),
            "item_count": sale.get("item_count", 1),
            "account": sale.get("account") or "ktb",
            "note": sale.get("note"),
        },
    )
    # ต้องอ่าน id ตรงนี้เลย ก่อนจะไปเรียก mark_day ซึ่งรันคำสั่งอื่นทับ
    new_id = cur.fetchone()[0]
    # ขายได้แปลว่าวันนั้นเปิดร้านแน่นอน — เซ็ตให้อัตโนมัติ
    mark_day(conn, sale.get("sold_on") or today_th(), shop_open=1, no_sale_reason=None)
    remember_for_undo(conn, "sale", new_id)
    conn.commit()
    recost_sales(conn)
    return new_id


def delete_sale(conn, sale_id: int) -> bool:
    cur = conn.execute("DELETE FROM sale WHERE id = ?", (sale_id,))
    conn.commit()
    recost_sales(conn)
    return cur.rowcount > 0


# ---------------------------------------------------------------- ต้นทุน Token (LIFO)

def _layer_events(conn):
    """
    รวบรวมทุกอย่างที่ทำให้ Token เข้า/ออก เรียงตามเวลา

    คืน list ของ (วันที่, เวลาที่จด, ลำดับ, id, ชนิด, ข้อมูล)
    ลำดับใช้ตัดสินตอนวันและเวลาเท่ากัน — ของเข้าก่อนของออก
    """
    ev = []
    for p in conn.execute(
        "SELECT id, bought_on, logged_at, kind, baht, tokens, rap_total, tokens_realised "
        "FROM purchase"
    ).fetchall():
        baht = float(p["baht"] or 0)
        if p["kind"] == "token":
            tokens = float(p["tokens"] or 0)
        else:
            # ของเหมา: ถ้า /ย่อย แล้วใช้ยอดจริง ไม่งั้นใช้ RAP หักค่าบูธ 1%
            # (เจ้าของไม่ /ย่อย แล้วตั้งแต่ 30 ก.ย. — ตรวจ 16 พ.ย. 2026 ยอดนี้
            #  รวมกับ Token ที่ซื้อ ตรงกับ Token ที่ใช้จริงทั้งหมดต่างกันไม่ถึง 0.5%)
            tokens = (float(p["tokens_realised"]) if p["tokens_realised"] is not None
                      else float(p["rap_total"] or 0) * 0.99)
        if tokens > 0 and baht > 0:
            ev.append((str(p["bought_on"]), str(p["logged_at"]), 0, p["id"], "in",
                       {"tokens": tokens, "rate": tokens / baht, "kind": p["kind"]}))
    for m in conn.execute(
        "SELECT id, happened_on, logged_at, tokens, kind FROM token_move "
        "WHERE kind IN ('open', 'booth_in', 'other_out')"
    ).fetchall():
        # adjust ไม่นับ: ส่วนใหญ่คือ Token จากของเหมาที่ขายออกจากบูธ
        # ซึ่งนับไปแล้วตอนซื้อเหมา นับอีกรอบจะกลายเป็นได้ Token ฟรีซ้ำสอง
        t = float(m["tokens"])
        if t > 0:
            ev.append((str(m["happened_on"]), str(m["logged_at"]), 0, m["id"], "free", {"tokens": t}))
        elif t < 0:
            ev.append((str(m["happened_on"]), str(m["logged_at"]), 1, m["id"], "out", {"tokens": -t}))
    for s in conn.execute(
        "SELECT id, sold_on, logged_at, tokens_spent, token_rate, source FROM sale"
    ).fetchall():
        ev.append((str(s["sold_on"]), str(s["logged_at"]), 1, s["id"], "sale", dict(s)))
    # id เป็นตัวตัดสินสุดท้าย — ไม่มีตัวนี้ รายการที่จดเวลาเดียวกันจะสลับลำดับ
    # ทุกครั้งที่ query (ฐานข้อมูลไม่รับประกันลำดับ) ต้นทุนเลยแกว่งไปมา (เจอ 16 พ.ย. 2026)
    ev.sort(key=lambda e: (e[0], e[1], e[2], e[3]))
    return ev


def lifo_costs(conn):
    """
    คิดต้นทุนทุกออเดอร์แบบ "ใช้ Token ชุดที่ซื้อล่าสุดก่อน" (LIFO)

    กติกาจากเจ้าของ 16 พ.ย. 2026
    ------------------------------
    ซื้อ 4,200 Token เรท 21 → ออเดอร์ต่อไปใช้เรท 21 จนกว่า 4,200 ตัวจะหมด
    หมดแล้วย้อนไปใช้ชุดที่ซื้อก่อนหน้า (เช่น 10.5) หมดอีกก็ย้อนไปชุดก่อนนั้น (เช่น 10)

    ทำไมต้องเปลี่ยนจากแบบเดิม
    แบบเดิมใช้ "เรทของการซื้อครั้งล่าสุด" ไปตลอดจนกว่าจะซื้อใหม่
    14–16 พ.ย. 2026 ซื้อ Token ถูก 4,200 ตัว แต่ออเดอร์ใช้เรทนั้นไป 8,222 ตัว
    ส่วนเกินถูกคิดทุนครึ่งเดียว กำไรเลยสูงเกินจริง

    ของเหมานับเป็นชุดหนึ่งด้วย เรท = Token ที่คาดว่าจะได้ ÷ บาทที่จ่าย
    ไม่งั้นต้นทุนรวมของทุกออเดอร์จะสูงกว่าเงินที่จ่ายจริง ~5,400฿ (ตรวจ 16 พ.ย.)

    ออเดอร์ที่จดก่อนจดการซื้อ (Token ในระบบยังไม่พอ)
    → ส่วนที่ขาดไปเอาจาก Token ชุดถัดไปที่เข้ามา
    → ถ้าไม่มีชุดไหนเข้ามาอีกเลย ใช้เรทซื้อ Token ครั้งล่าสุด

    คืน dict: id ออเดอร์ → เรทใหม่ (Token ต่อบาท)  และเรทของชุดบนสุดที่เหลือ
    """
    stack = []        # [[Token ที่เหลือ, เรท], ...] ตัวท้ายสุด = ชุดล่าสุด
    owed = []         # [[id ออเดอร์, Token ที่ยังขาด], ...] รอชุดถัดไปมาเติม
    cost = {}         # id → [บาทรวม, Token ที่คิดทุนแล้ว]
    orig = {}         # id → (เรทเดิม, Token ทั้งหมด)
    last_rate = None

    for _, _, _, _, kind, d in _layer_events(conn):
        if kind in ("in", "free"):
            if kind == "free":
                # Token ยกมา/ขายของตัวเอง ไม่มีเงินจ่ายออก แต่คิดเท่าเรทล่าสุด
                # เพื่อไม่ให้ออเดอร์ที่ใช้ Token ชุดนี้ดูกำไรเว่อร์
                rate = last_rate or None
            else:
                rate = d["rate"]
                if d["kind"] == "token":
                    last_rate = rate
            left = d["tokens"]
            if rate is None:
                continue
            # จ่ายหนี้ออเดอร์ที่จดไว้ก่อนก่อน (ตามลำดับที่ค้าง)
            while owed and left > 0:
                sid, need = owed[0]
                take = min(need, left)
                cost[sid][0] += take / rate
                cost[sid][1] += take
                left -= take
                owed[0][1] -= take
                if owed[0][1] <= 0:
                    owed.pop(0)
            if left > 0:
                stack.append([left, rate])
            continue

        need = float(d["tokens_spent"]) if kind == "sale" else d["tokens"]
        if kind == "sale":
            sid = d["id"]
            cost[sid] = [0.0, 0.0]
            orig[sid] = (float(d["token_rate"]), need)
        while need > 0 and stack:
            top = stack[-1]
            take = min(need, top[0])
            if kind == "sale":
                cost[sid][0] += take / top[1]
                cost[sid][1] += take
            top[0] -= take
            need -= take
            if top[0] <= 1e-9:
                stack.pop()
        if need > 0 and kind == "sale":
            owed.append([sid, need])

    # ที่ยังค้างจนจบ = ไม่มี Token ชุดไหนมาเติมแล้ว
    # ใช้เรทซื้อ Token ครั้งล่าสุด (ถ้าวันนี้ต้องซื้อมาแทน ต้องจ่ายเท่านี้)
    # ห้ามใช้เรทที่เก็บในออเดอร์นั้นเอง — มันถูกเขียนทับทุกรอบที่คิดใหม่
    # ถ้าเอามาคิดต่อ ตัวเลขจะไหลไปเรื่อยๆ ทุกครั้งที่มีออเดอร์ใหม่
    # (เรทในออเดอร์ใช้ได้เฉพาะตอนไม่เคยซื้อ Token เลย ซึ่งไม่มีอะไรเปลี่ยนมันอยู่แล้ว)
    for sid, need in owed:
        cost[sid][0] += need / (last_rate or orig[sid][0])
        cost[sid][1] += need

    rates = {}
    for sid, (baht, tokens) in cost.items():
        if tokens > 0 and baht > 0:
            rates[sid] = tokens / baht
        else:
            rates[sid] = orig[sid][0]      # ออเดอร์ 0 Token คงเรทเดิม
    top_rate = stack[-1][1] if stack else last_rate
    return rates, top_rate


def recost_sales(conn):
    """
    คิดต้นทุนทุกออเดอร์ใหม่ตามกติกา LIFO แล้วเขียนเรทกลับลงตาราง sale
    เรียกทุกครั้งที่มีการเพิ่ม/ลบ/แก้ การขายหรือการซื้อ

    เขียนลง token_rate ตรงๆ (ไม่เพิ่มคอลัมน์ใหม่) เพราะ VIEW v_sale
    และรายงานทุกตัวคิดต้นทุนจากช่องนี้อยู่แล้ว
    แก้เฉพาะแถวที่เรทเปลี่ยนจริง — ปกติเพิ่มออเดอร์ใหม่จะเปลี่ยนแค่แถวเดียว

    คืน list ของ (id, เรทเดิม, เรทใหม่) ที่เปลี่ยน
    """
    from parser import HOT_RATE_THRESHOLD
    rates, _ = lifo_costs(conn)
    current = {r["id"]: (float(r["token_rate"]), r["source"]) for r in conn.execute(
        "SELECT id, token_rate, source FROM sale").fetchall()}
    changed = []
    for sid, rate in rates.items():
        # คอลัมน์ฝั่ง Postgres เก็บทศนิยม 3 ตำแหน่ง ปัดให้ตรงกันทั้งสองฝั่ง
        new = round(rate, 3)
        old, old_src = current[sid]
        src = "hot_lot" if new >= HOT_RATE_THRESHOLD else "seller"
        if abs(new - old) >= 0.0005 or src != old_src:
            conn.execute("UPDATE sale SET token_rate = ?, source = ? WHERE id = ?",
                         (new, src, sid))
            changed.append((sid, old, new))
    if changed:
        conn.commit()
    return changed


def last_sale(conn):
    return conn.execute(
        "SELECT * FROM v_sale ORDER BY id DESC LIMIT 1"
    ).fetchone()


def recent_sales(conn, limit=10):
    return conn.execute(
        "SELECT * FROM v_sale ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()


def update_sale(conn, sale_id: int, sale: dict) -> bool:
    """แก้รายการขายที่จดไว้แล้ว — ใช้ตอนพิมพ์ผิดแล้วเพิ่งมารู้ทีหลัง"""
    cur = conn.execute(
        """
        UPDATE sale SET price_baht = :price_baht, tokens_spent = :tokens_spent,
               token_rate = :token_rate, source = :source, item_count = :item_count,
               note = :note
        WHERE id = :id
        """,
        {"id": sale_id, "price_baht": sale["price_baht"],
         "tokens_spent": sale["tokens_spent"], "token_rate": sale["token_rate"],
         "source": sale.get("source", "seller"),
         "item_count": sale.get("item_count", 1), "note": sale.get("note")},
    )
    conn.commit()
    recost_sales(conn)
    return cur.rowcount > 0


def find_duplicate(conn, sale: dict, minutes=15):
    """
    หารายการที่เหมือนกันเป๊ะและเพิ่งจดไปไม่นาน

    ตอนจดรวดเดียวตอนดึก การเผลอกดส่งซ้ำเกิดง่ายมาก
    และถ้าไม่มีอะไรเตือน กำไรจะเด้งขึ้นทั้งที่ไม่มีอะไรเกิดขึ้นจริง
    """
    cutoff = (now_th() - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    return conn.execute(
        """
        SELECT id, logged_at FROM sale
        WHERE sold_on = ? AND price_baht = ? AND tokens_spent = ? AND logged_at >= ?
        ORDER BY id DESC LIMIT 1
        """,
        (sale.get("sold_on") or today_th(), sale["price_baht"],
         sale["tokens_spent"], cutoff),
    ).fetchone()


def data_health(conn, start_date: str, end_date: str) -> dict:
    """
    ตัวชี้วัดคุณภาพข้อมูล — ระบบที่ซ่อนความผิดพลาดของตัวเองแย่กว่าไม่มีระบบ
    """
    adj = conn.execute(
        """
        SELECT COUNT(*) n, COALESCE(SUM(tokens),0) total,
               COALESCE(SUM(ABS(tokens)),0) size
        FROM token_move
        WHERE kind = 'adjust' AND happened_on BETWEEN ? AND ?
        """,
        (start_date, end_date),
    ).fetchone()
    s = conn.execute(
        """
        SELECT COUNT(*) orders,
               SUM(CASE WHEN note IS NULL OR note = '' THEN 1 ELSE 0 END) no_note,
               COALESCE(SUM(tokens_spent),0) tokens
        FROM sale WHERE sold_on BETWEEN ? AND ?
        """,
        (start_date, end_date),
    ).fetchone()
    days = conn.execute(
        """
        SELECT SUM(CASE WHEN orders = 0 AND no_sale_reason IS NULL THEN 1 ELSE 0 END)
        FROM v_day WHERE log_date BETWEEN ? AND ?
        """,
        (start_date, end_date),
    ).fetchone()[0] or 0
    return {"adjust_times": adj["n"], "adjust_net": adj["total"],
            "adjust_size": adj["size"], "orders": s["orders"] or 0,
            "no_note": s["no_note"] or 0,
            "tokens": s["tokens"], "days_unexplained": days}


def sale_by_id(conn, sale_id: int):
    return conn.execute("SELECT * FROM v_sale WHERE id = ?", (sale_id,)).fetchone()


# ---------------------------------------------------------------- การซื้อของเข้าร้าน

def insert_purchase(conn, kind: str, baht: float, amount: int,
                    item_count=None, note=None, bought_on=None,
                    account=None) -> int:
    """
    บันทึกเงินที่จ่ายออกไปเพื่อเอาของมาขาย

    kind='token' : amount = Token ที่ได้มาเลย
    kind='lot'   : amount = RAP รวมของชุดที่รับเหมามา (ยังไม่ใช่ Token จนกว่าจะย่อยขาย)
    """
    cur = conn.execute(
        """
        INSERT INTO purchase (bought_on, logged_at, kind, baht, tokens, rap_total,
                              item_count, account, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (bought_on or today_th(), now_th().isoformat(timespec="seconds"), kind, baht,
         amount if kind == "token" else None,
         amount if kind == "lot" else None,
         item_count, account or "ktb", note),
    )
    new_id = cur.fetchone()[0]
    remember_for_undo(conn, "purchase", new_id)
    conn.commit()
    recost_sales(conn)
    return new_id


def latest_lot(conn):
    """ล็อตเหมาล่าสุดที่ยังไม่ได้บันทึกว่าย่อยขายได้เท่าไหร่"""
    return conn.execute(
        "SELECT * FROM v_purchase WHERE kind = 'lot' ORDER BY id DESC LIMIT 1"
    ).fetchone()


def set_lot_realised(conn, purchase_id: int, tokens: int):
    """บันทึกว่าล็อตนั้นย่อยขายที่บูธได้ Token จริงเท่าไหร่"""
    conn.execute(
        "UPDATE purchase SET tokens_realised = ? WHERE id = ? AND kind = 'lot'",
        (tokens, purchase_id),
    )
    conn.commit()
    recost_sales(conn)


def purchase_by_id(conn, purchase_id: int):
    return conn.execute(
        "SELECT * FROM v_purchase WHERE id = ?", (purchase_id,)
    ).fetchone()


def last_purchase(conn):
    return conn.execute(
        "SELECT * FROM v_purchase ORDER BY id DESC LIMIT 1"
    ).fetchone()


def delete_purchase(conn, purchase_id: int) -> bool:
    cur = conn.execute("DELETE FROM purchase WHERE id = ?", (purchase_id,))
    conn.commit()
    recost_sales(conn)
    return cur.rowcount > 0


# ---------------------------------------------------------------- ยอด Token

def add_token_move(conn, tokens: int, kind: str, note=None, happened_on=None) -> int:
    cur = conn.execute(
        """
        INSERT INTO token_move (happened_on, logged_at, tokens, kind, note)
        VALUES (?, ?, ?, ?, ?)
        RETURNING id
        """,
        (happened_on or today_th(), now_th().isoformat(timespec="seconds"),
         int(tokens), kind, note),
    )
    new_id = cur.fetchone()[0]
    conn.commit()
    # adjust ไม่กระทบต้นทุน (ดู _layer_events) ไม่ต้องคิดใหม่ ประหยัดรอบต่อฐานข้อมูล
    if kind != "adjust":
        recost_sales(conn)
    return new_id


def token_balance(conn, until_date=None) -> dict:
    """
    ยอด Token ที่ควรเหลือ ตามทุกอย่างที่บันทึกไว้

    เข้า  = ยอดยกมา + ซื้อจากพ่อค้า + ที่ย่อยขายล็อตเหมาได้ + ขายของเองที่บูธ
    ออก  = ที่ส่งให้ลูกค้า + รายการออกอื่นๆ
    """
    # จำกัดช่วงวันแบบเดียวกันทุกตาราง แค่ชื่อคอลัมน์วันที่ต่างกัน
    def total(table, column, date_column, extra=""):
        sql = f"SELECT COALESCE(SUM({column}),0) FROM {table} WHERE 1=1 {extra}"
        args = ()
        if until_date:
            sql += f" AND {date_column} <= ?"
            args = (until_date,)
        return conn.execute(sql, args).fetchone()[0]

    bought = total("purchase", "tokens", "bought_on", "AND kind='token'")
    realised = total("purchase", "tokens_realised", "bought_on", "AND kind='lot'")
    moves = total("token_move", "tokens", "happened_on")
    used = total("sale", "tokens_spent", "sold_on")

    return {"bought": bought, "realised": realised, "moves": moves,
            "used": used, "expected": bought + realised + moves - used}


def recent_token_moves(conn, limit=5):
    return conn.execute(
        "SELECT * FROM token_move ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()


# ---------------------------------------------------------------- รายจ่ายส่วนตัว
#
# ทุกฟังก์ชันในหมวดนี้แตะเฉพาะตาราง spend เท่านั้น
# ห้ามเอาผลลัพธ์ไปรวมกับกำไรธุรกิจ

def add_spend(conn, baht: float, category=None, note=None, spent_on=None) -> int:
    cur = conn.execute(
        "INSERT INTO spend (spent_on, logged_at, baht, category, note)"
        " VALUES (?,?,?,?,?) RETURNING id",
        (spent_on or today_th(), now_th().isoformat(timespec="seconds"),
         baht, category, note),
    )
    new_id = cur.fetchone()[0]
    remember_for_undo(conn, "spend", new_id)
    conn.commit()
    return new_id


def last_spend(conn):
    return conn.execute("SELECT * FROM spend ORDER BY id DESC LIMIT 1").fetchone()


def delete_spend(conn, spend_id: int) -> bool:
    cur = conn.execute("DELETE FROM spend WHERE id = ?", (spend_id,))
    conn.commit()
    return cur.rowcount > 0


def spend_total(conn, start_date: str, end_date: str) -> float:
    return conn.execute(
        "SELECT COALESCE(SUM(baht),0) FROM spend WHERE spent_on BETWEEN ? AND ?",
        (start_date, end_date),
    ).fetchone()[0]


def spend_by_category(conn, start_date: str, end_date: str):
    return conn.execute(
        """
        SELECT COALESCE(category, 'ไม่ได้ระบุ') AS category,
               COUNT(*)        AS times,
               ROUND(SUM(baht), 0) AS total
        FROM spend
        WHERE spent_on BETWEEN ? AND ?
        GROUP BY 1
        ORDER BY total DESC
        """,
        (start_date, end_date),
    ).fetchall()


def spend_since(conn, iso_timestamp: str) -> float:
    """รายจ่ายที่จดไว้หลังจากเวลาที่กำหนด — ใช้ตรวจกับยอดคงเหลือในบัญชี"""
    return conn.execute(
        "SELECT COALESCE(SUM(baht),0) FROM spend WHERE logged_at > ?",
        (iso_timestamp,),
    ).fetchone()[0]


# ---------------------------------------------------------------- เงินที่ย้ายกระเป๋า
#
# ⚠️ เหมือนตาราง spend — ห้ามเอาไป join กับการคิดกำไร
# การย้ายเงินไม่ทำให้กำไรเปลี่ยน มีหน้าที่อธิบายว่าเงินไปอยู่ไหนเท่านั้น

def add_transfer(conn, baht: float, destination=None, note=None,
                 moved_on=None) -> int:
    """
    จดเงินที่ย้ายออกจากบัญชีร้าน
    baht เป็นบวก = ออกจากร้าน · เป็นลบ = ควักเงินตัวเองใส่เข้าร้าน
    """
    cur = conn.execute(
        "INSERT INTO transfer (moved_on, logged_at, baht, destination, note)"
        " VALUES (?,?,?,?,?) RETURNING id",
        (moved_on or today_th(), now_th().isoformat(timespec="seconds"),
         baht, destination, note),
    )
    new_id = cur.fetchone()[0]
    conn.commit()
    return new_id


def last_transfer(conn):
    return conn.execute(
        "SELECT * FROM transfer ORDER BY id DESC LIMIT 1").fetchone()


def delete_transfer(conn, transfer_id: int) -> bool:
    cur = conn.execute("DELETE FROM transfer WHERE id = ?", (transfer_id,))
    conn.commit()
    return cur.rowcount > 0


def transfer_total(conn, start_date: str, end_date: str) -> float:
    return conn.execute(
        "SELECT COALESCE(SUM(baht),0) FROM transfer WHERE moved_on BETWEEN ? AND ?",
        (start_date, end_date),
    ).fetchone()[0]


def transfer_by_destination(conn, start_date: str, end_date: str):
    return conn.execute(
        """
        SELECT COALESCE(destination, 'ไม่ได้ระบุ') AS destination,
               COUNT(*)            AS times,
               ROUND(SUM(baht), 0) AS total
        FROM transfer
        WHERE moved_on BETWEEN ? AND ?
        GROUP BY 1
        ORDER BY total DESC
        """,
        (start_date, end_date),
    ).fetchall()


# ---------------------------------------------------------------- ต้นทุนธุรกิจอื่น
#
# ต่างจาก spend (ส่วนตัว) และ transfer (ย้ายกระเป๋า) ตรงที่อันนี้
# เป็นต้นทุนจริงของธุรกิจ ต้องถูกหักออกจากกำไร

def add_expense(conn, baht: float, category=None, note=None,
                spent_on=None) -> int:
    cur = conn.execute(
        "INSERT INTO expense (spent_on, logged_at, baht, category, note)"
        " VALUES (?,?,?,?,?) RETURNING id",
        (spent_on or today_th(), now_th().isoformat(timespec="seconds"),
         baht, category, note),
    )
    new_id = cur.fetchone()[0]
    conn.commit()
    return new_id


def expense_total(conn, start_date: str, end_date: str) -> float:
    return conn.execute(
        "SELECT COALESCE(SUM(baht),0) FROM expense WHERE spent_on BETWEEN ? AND ?",
        (start_date, end_date),
    ).fetchone()[0]


def expense_by_category(conn, start_date: str, end_date: str):
    return conn.execute(
        """
        SELECT COALESCE(category, 'ไม่ได้ระบุ') AS category,
               COUNT(*)            AS times,
               ROUND(SUM(baht), 0) AS total
        FROM expense
        WHERE spent_on BETWEEN ? AND ?
        GROUP BY 1
        ORDER BY total DESC
        """, (start_date, end_date)).fetchall()


def last_expense(conn):
    return conn.execute(
        "SELECT * FROM expense ORDER BY id DESC LIMIT 1").fetchone()


def delete_expense(conn, expense_id: int) -> bool:
    cur = conn.execute("DELETE FROM expense WHERE id = ?", (expense_id,))
    conn.commit()
    return cur.rowcount > 0


# ---------------------------------------------------------------- ออเดอร์ค้างส่ง
#
# ⚠️ ห้าม join เข้ากับการคิดกำไร เหมือน spend กับ transfer
# เงินที่รับมาแล้วแต่ยังไม่ได้ส่งของ ยังไม่ใช่กำไร

def add_pending(conn, baht: float, note=None, received_on=None) -> int:
    cur = conn.execute(
        "INSERT INTO pending_order (received_on, logged_at, baht, note)"
        " VALUES (?,?,?,?) RETURNING id",
        (received_on or today_th(), now_th().isoformat(timespec="seconds"),
         baht, note),
    )
    new_id = cur.fetchone()[0]
    conn.commit()
    return new_id


def open_pendings(conn):
    """ออเดอร์ที่ยังค้างส่งอยู่ เรียงจากเก่าสุดก่อน — ของเก่าคือของที่น่าห่วง"""
    return conn.execute(
        "SELECT * FROM pending_order WHERE outcome IS NULL"
        " ORDER BY received_on, id").fetchall()


def pending_total(conn) -> float:
    return conn.execute(
        "SELECT COALESCE(SUM(baht),0) FROM pending_order"
        " WHERE outcome IS NULL").fetchone()[0]


def close_pending(conn, pending_id: int, outcome: str) -> bool:
    cur = conn.execute(
        "UPDATE pending_order SET outcome = ?, closed_on = ?"
        " WHERE id = ? AND outcome IS NULL",
        (outcome, today_th(), pending_id))
    conn.commit()
    return cur.rowcount > 0


def pending_by_outcome(conn, start_date: str, end_date: str):
    return conn.execute(
        """
        SELECT COALESCE(outcome, 'ยังค้างอยู่') AS outcome,
               COUNT(*)            AS times,
               ROUND(SUM(baht), 0) AS total
        FROM pending_order
        WHERE received_on BETWEEN ? AND ?
        GROUP BY 1
        ORDER BY total DESC
        """, (start_date, end_date)).fetchall()


# ---------------------------------------------------------------- ยอดเงินตั้งต้น

def add_snapshot(conn, cash_baht: float, note=None, taken_on=None) -> int:
    """จดยอดเงินทุกบัญชีรวมกัน ณ วันหนึ่ง — ใช้เป็นเส้นเริ่มของเดือน"""
    cur = conn.execute(
        "INSERT INTO balance_snapshot (taken_on, logged_at, cash_baht, note)"
        " VALUES (?,?,?,?) RETURNING id",
        (taken_on or today_th(), now_th().isoformat(timespec="seconds"),
         cash_baht, note),
    )
    new_id = cur.fetchone()[0]
    conn.commit()
    return new_id


def snapshot_on_or_before(conn, on_date: str):
    """ยอดที่จดไว้ล่าสุดก่อนหรือตรงวันที่กำหนด — ใช้หาเส้นเริ่มของช่วง"""
    return conn.execute(
        "SELECT * FROM balance_snapshot WHERE taken_on <= ?"
        " ORDER BY taken_on DESC, id DESC LIMIT 1", (on_date,),
    ).fetchone()


def last_snapshot(conn):
    return conn.execute(
        "SELECT * FROM balance_snapshot ORDER BY taken_on DESC, id DESC LIMIT 1"
    ).fetchone()


# ---------------------------------------------------------------- ต้นทุน Token เฉลี่ย

def blended_rate(conn, fallback: float):
    """
    ต้นทุน Token เฉลี่ยถ่วงน้ำหนัก = เงินที่จ่ายไปทั้งหมด ÷ Token ที่ได้มาทั้งหมด

    ทำไมต้องใช้ตัวนี้ ไม่ใช่ token_rate ที่จดไว้ในแต่ละออเดอร์
    -----------------------------------------------------------
    Token ทุกตัวหน้าตาเหมือนกันหมด เอาไปส่งลูกค้าแล้วแยกไม่ออกเลยว่า
    ตัวไหนมาจากพ่อค้า (เรท ~11) ตัวไหนมาจากของเหมา (เรท 20-50)
    ของที่แยกกันไม่ออกแบบนี้ ต้องคิดต้นทุนเฉลี่ยถ่วงน้ำหนัก
    ไม่ใช่คิดด้วยเรทของการซื้อครั้งล่าสุด

    ก.ย. 2026 วัดได้ว่าเรื่องนี้ทำให้กำไรที่รายงานต่ำกว่าจริง 709 บาท
    เพราะของเหมาคิดเป็น 9% ของเงินที่จ่าย แต่ได้ Token มาถึง 17%

    คืนค่าเป็น (เรท, จำนวนล็อตที่ยังไม่ได้กรอกว่าย่อยได้เท่าไหร่)

    Token ที่ได้มา ต้องนับ token_move ด้วย (แก้ 16 พ.ย. 2026)
    -----------------------------------------------------------
    30 ก.ย. เจ้าของเลิก /ย่อย แล้ว (ของเหมาปนกันในบูธ จำไม่ได้ว่าชิ้นไหนจากล็อตไหน)
    Token จากของเหมาจึงเข้ามาทาง /นับ ในรูป kind='adjust' แทน
    สูตรเดิมนับแต่ purchase → ล็อตที่ไม่ได้ /ย่อย นับว่าได้ Token 0 ทั้งที่จ่ายเงินไปแล้ว
    ข้อมูลจริง 16 พ.ย.: 47 ล็อต 5,402฿ ได้ Token 0 → เรทออกมา 9.82
    ซึ่งต่ำกว่าเรทของทุกแหล่ง (พ่อค้า 10.2–12.5 · เหมา 15–80) = เป็นไปไม่ได้
    นับ token_move ทุกชนิดรวมด้วย: adjust ติดลบ (กดบูธแพงกว่า RAP)
    และ other_out (ของที่ให้ไปฟรี) ก็เป็นต้นทุนจริง ต้องหักออกด้วย
    """
    row = conn.execute(
        """
        SELECT COALESCE(SUM(baht), 0) AS baht,
               COALESCE(SUM(CASE WHEN kind = 'token' THEN tokens
                                 ELSE COALESCE(tokens_realised, 0) END), 0) AS tokens,
               SUM(CASE WHEN kind = 'lot' AND tokens_realised IS NULL
                        THEN 1 ELSE 0 END) AS pending
        FROM purchase
        """
    ).fetchone()
    moves = conn.execute(
        "SELECT COALESCE(SUM(tokens), 0) FROM token_move"
    ).fetchone()[0]
    tokens = (row["tokens"] or 0) + (moves or 0)
    if not row["baht"] or tokens <= 0:
        return fallback, (row["pending"] or 0)
    return tokens / float(row["baht"]), (row["pending"] or 0)


def true_profit(conn, start_date: str, end_date: str, rate: float,
                tokens_on_hand: int, tokens_at_start: int = 0) -> dict:
    """
    กำไรจริง = กำไรเงินสด + มูลค่าของที่ตุนเพิ่มขึ้น

    ทำไมต้องคิดสองส่วนบวกกัน
    ---------------------------
    กำไรเงินสดอย่างเดียวจะดูเหมือนขาดทุนในวันที่เอาเงินไปตุนของเยอะ
    ทั้งที่ของยังอยู่ครบและขายได้  ส่วนการตีมูลค่าของอย่างเดียว
    ก็เชื่อไม่ได้ เพราะต้องเดาเรท  เอามาบวกกันจึงได้ภาพที่ถูก

    ตีราคาของที่ตุนไว้ด้วย "ต้นทุนที่จ่ายมา" ไม่ใช่ราคาที่คาดว่าจะขายได้
    เพราะยังไม่มีใครมาซื้อ การตีราคาด้วยกำไรที่ยังไม่เกิดคือการโกงตัวเอง
    """
    cash = cash_summary(conn, start_date, end_date)
    stock_end = tokens_on_hand / rate if rate else 0.0
    stock_start = tokens_at_start / rate if rate else 0.0
    return {
        **cash,
        "rate": rate,
        "tokens_on_hand": tokens_on_hand,
        "stock_end": stock_end,
        "stock_start": stock_start,
        "stock_change": stock_end - stock_start,
        "profit_true": cash["profit_cash"] + stock_end - stock_start,
    }


# ---------------------------------------------------------------- ค่าที่บอทจำไว้

def get_state(conn, key: str, default=None):
    row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_state(conn, key: str, value):
    conn.execute(
        "INSERT INTO app_state (key, value, updated_at) VALUES (?, ?, ?)"
        " ON CONFLICT (key) DO UPDATE"
        " SET value = excluded.value, updated_at = excluded.updated_at",
        (key, str(value), now_th().isoformat(timespec="seconds")),
    )
    conn.commit()


# ---------------------------------------------------------------- /undo
#
# เดิม /undo หา "อันล่าสุด" จาก logged_at ของ 3 ตาราง แต่ logged_at ละเอียดแค่วินาที
# ข้อความหลายบรรทัดบันทึกหลายอย่างในวินาทีเดียวกัน แล้ว /undo ลบผิดตัว
#   "/จ่าย 50 ข้าว" + "55 192" ส่งพร้อมกัน → /undo ลบรายจ่าย แทนที่จะลบออเดอร์
#   "55 192" + "/ซื้อ 700 63" ส่งพร้อมกัน → /undo ลบออเดอร์ แทนที่จะลบการซื้อ
# (เจอจากเทสต์สุ่มยิง 30 ก.ย. 2026)
#
# แก้ด้วยการจำลำดับที่บันทึกจริงไว้เป็นกอง แล้ว /undo หยิบจากบนสุด

UNDO_KEY = "undo_stack"
UNDO_TABLES = {"sale": "sale", "purchase": "purchase", "spend": "spend"}


def remember_for_undo(conn, kind: str, row_id: int):
    stack = [x for x in (get_state(conn, UNDO_KEY) or "").split(",") if x]
    stack.append(f"{kind}:{row_id}")
    set_state(conn, UNDO_KEY, ",".join(stack[-30:]))


def pop_undo(conn):
    """
    คืน (ชนิด, id) ของสิ่งที่บันทึกล่าสุดที่ยังมีอยู่จริง แล้วเอาออกจากกอง
    ข้ามตัวที่ถูกลบไปแล้วด้วยทางอื่น · คืน None ถ้ากองว่าง (ข้อมูลก่อนมีระบบนี้)
    """
    stack = [x for x in (get_state(conn, UNDO_KEY) or "").split(",") if x]
    found = None
    while stack:
        kind, _, rid = stack.pop().partition(":")
        table = UNDO_TABLES.get(kind)
        if table and rid.isdigit() and conn.execute(
                f"SELECT 1 FROM {table} WHERE id = ?", (int(rid),)).fetchone():
            found = (kind, int(rid))
            break
    set_state(conn, UNDO_KEY, ",".join(stack))
    return found


def state_updated_at(conn, key: str):
    """ค่านี้ถูกตั้งไว้เมื่อไหร่ — ใช้ตรวจว่าเลขที่จดมือไว้เก่าเกินไปหรือยัง"""
    row = conn.execute(
        "SELECT updated_at FROM app_state WHERE key = ?", (key,)).fetchone()
    return row["updated_at"] if row else None


def last_token_check_id(conn) -> int:
    """
    เลขลำดับของการนับ Token ครั้งล่าสุด (คำสั่ง /เช็ค)

    ใช้เลขลำดับแทนเวลา เพราะเวลาที่เก็บละเอียดแค่ระดับวินาที
    ถ้าสั่ง /บูธ แล้ว /เช็ค ติดกันในวินาทีเดียว เทียบเวลาจะแยกไม่ออก
    เลขลำดับเพิ่มขึ้นเสมอ จึงบอกลำดับก่อนหลังได้แน่นอน
    """
    row = conn.execute(
        "SELECT id FROM token_move WHERE kind = 'adjust'"
        " ORDER BY id DESC LIMIT 1").fetchone()
    return row["id"] if row else 0


def last_token_check_at(conn):
    """วันเวลาที่นับ Token ครั้งล่าสุด — ใช้กับข้อมูลเก่าที่ยังไม่มีเลขลำดับจดไว้"""
    row = conn.execute(
        "SELECT logged_at FROM token_move WHERE kind = 'adjust'"
        " ORDER BY id DESC LIMIT 1").fetchone()
    return row["logged_at"] if row else None


def current_rate(conn, fallback: float) -> float:
    """เรทที่ใช้อยู่ตอนนี้ — ตั้งโดยคำสั่ง /ซื้อ หรือ /เหมา ล่าสุด"""
    value = get_state(conn, "current_rate")
    try:
        return float(value) if value else fallback
    except ValueError:
        return fallback


# ---------------------------------------------------------------- บันทึกรายวัน

def mark_day(conn, log_date: str, shop_open=None, no_sale_reason=None,
             inquiries=None, note=None):
    """
    สร้าง/อัปเดตแถวของวันนั้น
    ค่าที่ส่งมาเป็น None จะไม่ไปทับของเดิม (ยกเว้น no_sale_reason ที่ตั้งใจล้าง)
    """
    conn.execute(
        "INSERT INTO day_log (log_date) VALUES (?)"
        " ON CONFLICT (log_date) DO NOTHING", (log_date,)
    )
    if shop_open is not None:
        conn.execute("UPDATE day_log SET shop_open = ? WHERE log_date = ?",
                     (shop_open, log_date))
    # ตั้ง no_sale_reason ทุกครั้งที่ถูกเรียกจากการจัดหมวดวัน (รวมกรณีล้างเป็น NULL)
    conn.execute("UPDATE day_log SET no_sale_reason = ? WHERE log_date = ?",
                 (no_sale_reason, log_date))
    if inquiries is not None:
        conn.execute("UPDATE day_log SET inquiries = ? WHERE log_date = ?",
                     (inquiries, log_date))
    if note is not None:
        conn.execute("UPDATE day_log SET note = ? WHERE log_date = ?",
                     (note, log_date))
    conn.commit()


def set_inquiries(conn, log_date: str, n: int):
    conn.execute("INSERT INTO day_log (log_date) VALUES (?)"
        " ON CONFLICT (log_date) DO NOTHING", (log_date,))
    # จดเองแล้ว = ไม่ใช่ค่าที่บอทเติมให้อีกต่อไป ลบป้ายออกจากหมายเหตุ
    conn.execute(
        "UPDATE day_log SET inquiries = ?, note = NULLIF(REPLACE(REPLACE("
        "COALESCE(note, ''), ?, ''), ?, ''), '') WHERE log_date = ?",
        (n, " · " + AUTO_INQ_NOTE, AUTO_INQ_NOTE, log_date))
    conn.commit()


# ป้ายในหมายเหตุของวัน — แยกให้ออกว่าเลขคนทักวันไหนจดจริง วันไหนบอทเติมให้
AUTO_INQ_NOTE = "ไม่ได้จด /ทัก ถือว่าปิดได้ 100%"


def fill_default_inquiries(conn, until_date: str) -> int:
    """
    วันที่ไม่ได้จดจำนวนคนทัก → ถือว่าคนทัก = จำนวนออเดอร์ (ปิดการขายได้ 100%)

    กติกาจากเจ้าของ 16 พ.ย. 2026: "วันไหนไม่ได้เขียนคนทัก ให้ตีว่าปิดได้ 100%"
    เจ้าของปิดการขายได้เกือบทุกคนอยู่แล้ว ค่านี้จึงเป็นค่าปริยายที่ถูกเกือบทุกครั้ง
    (ตรงกับกฎข้อ 8 ใน CLAUDE.md — ช่องที่ต้องพิมพ์ทุกวันจะไม่มีใครพิมพ์)
    พ.ย. 2026 จด /ทัก แค่ 6 จาก 16 วัน ที่เหลือว่างจนคิดอัตราปิดการขายไม่ได้

    วันที่ขายไม่ได้เพราะ "ไม่มีคนทัก" → คนทัก 0
    วันที่ไม่ได้เปิดร้าน / ลืมจด / มีคนทักแต่ปิดไม่ได้ → ไม่เดา ปล่อยว่าง

    ใส่ป้ายไว้ในหมายเหตุของวันเสมอ วิเคราะห์ทีหลังจะได้แยกออกว่าเลขไหนบอทเติม
    เติมเฉพาะวันที่จบไปแล้ว (≤ until_date) วันนี้ยังขายไม่จบ ห้ามเติม
    คืนจำนวนวันที่เติม
    """
    tag = (" · " + AUTO_INQ_NOTE, AUTO_INQ_NOTE)
    cur = conn.execute(
        """
        UPDATE day_log
        SET inquiries = (SELECT COUNT(*) FROM sale s WHERE s.sold_on = day_log.log_date),
            note = CASE WHEN note IS NULL OR note = '' THEN ? ELSE note || ? END
        WHERE inquiries IS NULL AND log_date <= ?
          AND EXISTS (SELECT 1 FROM sale s WHERE s.sold_on = day_log.log_date)
        """,
        (tag[1], tag[0], until_date),
    )
    n = cur.rowcount or 0
    cur = conn.execute(
        """
        UPDATE day_log
        SET inquiries = 0,
            note = CASE WHEN note IS NULL OR note = '' THEN ? ELSE note || ? END
        WHERE inquiries IS NULL AND log_date <= ? AND no_sale_reason = 'no_inquiry'
          AND NOT EXISTS (SELECT 1 FROM sale s WHERE s.sold_on = day_log.log_date)
        """,
        (tag[1], tag[0], until_date),
    )
    n += cur.rowcount or 0
    conn.commit()
    return n


# ---------------------------------------------------------------- สรุปยอด

def day_summary(conn, log_date: str):
    row = conn.execute("SELECT * FROM v_day WHERE log_date = ?", (log_date,)).fetchone()
    if row is None:
        # วันที่ยังไม่มีแถวเลย — คืนค่าศูนย์ให้บอทแสดงผลได้
        return {"log_date": log_date, "orders": 0, "revenue_baht": 0,
                "profit_baht": 0, "tokens_spent": 0, "cost_baht": 0,
                "shop_open": None, "no_sale_reason": None,
                "inquiries": None, "close_rate_pct": None}
    return dict(row)


def range_summary(conn, start_date: str, end_date: str) -> dict:
    """สรุปยอดรวมในช่วงวันที่ (รวมปลายทั้งสองข้าง)"""
    row = conn.execute(
        """
        SELECT COUNT(*)                  AS orders,
               COALESCE(SUM(price_baht),0)   AS revenue_baht,
               COALESCE(SUM(cost_baht),0)    AS cost_baht,
               COALESCE(SUM(profit_baht),0)  AS profit_baht,
               COALESCE(SUM(tokens_spent),0) AS tokens_spent
        FROM v_sale
        WHERE sold_on BETWEEN ? AND ?
        """,
        (start_date, end_date),
    ).fetchone()
    out = dict(row)

    # นับวันที่เปิดร้าน / วันที่ขายได้ ในช่วงเดียวกัน
    d = conn.execute(
        """
        SELECT SUM(CASE WHEN shop_open = 1 THEN 1 ELSE 0 END) AS open_days,
               SUM(CASE WHEN orders  > 0 THEN 1 ELSE 0 END)   AS selling_days,
               COUNT(*)                                       AS logged_days
        FROM v_day
        WHERE log_date BETWEEN ? AND ?
        """,
        (start_date, end_date),
    ).fetchone()
    out.update({k: (d[k] or 0) for k in ("open_days", "selling_days", "logged_days")})
    return out


def zero_day_breakdown(conn, start_date: str, end_date: str):
    """นับว่าวันที่ไม่มียอดขาย เกิดจากสาเหตุไหนบ้าง — คำตอบของโจทย์หลัก"""
    return conn.execute(
        """
        SELECT COALESCE(no_sale_reason, 'ยังไม่ได้ระบุ') AS reason,
               COUNT(*) AS days
        FROM v_day
        WHERE log_date BETWEEN ? AND ?
          AND orders = 0
        GROUP BY 1
        ORDER BY days DESC
        """,
        (start_date, end_date),
    ).fetchall()


def cash_summary(conn, start_date: str, end_date: str) -> dict:
    """
    กำไรจากกระแสเงินสดจริง = เงินที่ลูกค้าโอนเข้า − เงินที่จ่ายซื้อของ

    ตัวเลขนี้คือตัวที่ต้องตรงกับยอดในบัญชีกรุงไทย
    ต่างจาก SUM(profit_baht) ที่เป็นการ "ประมาณต้นทุนต่อออเดอร์"
    ผลต่างของสองอันนี้ = มูลค่าที่ยังค้างอยู่ในของเหมาที่ยังย่อยขายไม่หมด
    """
    cash_in = conn.execute(
        "SELECT COALESCE(SUM(price_baht),0) FROM sale WHERE sold_on BETWEEN ? AND ?",
        (start_date, end_date),
    ).fetchone()[0]
    row = conn.execute(
        """
        SELECT COALESCE(SUM(baht),0)                                    AS total,
               COALESCE(SUM(CASE WHEN kind='token' THEN baht END),0)    AS on_token,
               COALESCE(SUM(CASE WHEN kind='lot'   THEN baht END),0)    AS on_lot
        FROM purchase WHERE bought_on BETWEEN ? AND ?
        """,
        (start_date, end_date),
    ).fetchone()
    attributed = conn.execute(
        "SELECT COALESCE(SUM(profit_baht),0) FROM v_sale WHERE sold_on BETWEEN ? AND ?",
        (start_date, end_date),
    ).fetchone()[0]

    # ต้นทุนธุรกิจอื่น เช่นค่าธรรมเนียมโอนเงิน — ไม่ใช่ของเข้าร้านแต่เป็นต้นทุนจริง
    fees = expense_total(conn, start_date, end_date)

    return {
        "cash_in": cash_in,
        "cash_out": row["total"],
        "cash_out_token": row["on_token"],
        "cash_out_lot": row["on_lot"],
        "expenses": fees,
        "profit_cash": cash_in - row["total"] - fees,
        "profit_attributed": attributed - fees,
        "profit_per_order": attributed,
        "gap": attributed - (cash_in - row["total"]),
    }


def days_missing_reason(conn, start_date: str, end_date: str):
    """
    วันที่ไม่มียอดขายและยังไม่ได้ระบุสาเหตุ — ใช้ตามเก็บตอนบอทไม่ได้เปิด
    นับเฉพาะวันที่อยู่หลังวันแรกที่เริ่มเก็บข้อมูล จะได้ไม่ไปถามถึงวันที่ยังไม่มีระบบ
    """
    first = conn.execute("SELECT MIN(log_date) FROM day_log").fetchone()[0]
    if first is None:
        return []
    start = date.fromisoformat(max(start_date, first))
    end = date.fromisoformat(end_date)

    # วันที่ยังไม่มีแถวใน day_log เลย ก็คือวันที่ขาดสาเหตุเหมือนกัน
    # จึงไล่วันเองแทนการ query เฉพาะแถวที่มีอยู่
    have = {r["log_date"]: r for r in conn.execute(
        "SELECT log_date, orders, no_sale_reason FROM v_day WHERE log_date BETWEEN ? AND ?",
        (start.isoformat(), end.isoformat()),
    ).fetchall()}

    missing = []
    d = start
    while d <= end:
        row = have.get(d.isoformat())
        if row is None or (row["orders"] == 0 and row["no_sale_reason"] is None):
            missing.append(d.isoformat())
        d += timedelta(days=1)
    return missing


def band_breakdown(conn, start_date: str, end_date: str):
    """กำไรแยกตามช่วงราคา Token — ใช้ตอบว่าของถูกหรือของแพงคุ้มกว่า"""
    return conn.execute(
        """
        SELECT token_band,
               COUNT(*)                        AS orders,
               ROUND(AVG(price_baht),1)        AS avg_price,
               ROUND(AVG(profit_baht),1)       AS avg_profit,
               ROUND(SUM(profit_baht),0)       AS total_profit,
               ROUND(AVG(profit_per_token),4)  AS avg_profit_per_token,
               ROUND(AVG(markup_x),2)          AS avg_markup_x
        FROM v_sale
        WHERE sold_on BETWEEN ? AND ?
        GROUP BY token_band
        ORDER BY token_band
        """,
        (start_date, end_date),
    ).fetchall()


# ---------------------------------------------------------------- งานตามเวลา

def job_already_ran(conn, job_key: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM job_log WHERE job_key = ?", (job_key,)
    ).fetchone() is not None


def mark_job_ran(conn, job_key: str):
    conn.execute(
        "INSERT INTO job_log (job_key, ran_at) VALUES (?, ?)"
        " ON CONFLICT (job_key) DO UPDATE SET ran_at = excluded.ran_at",
        (job_key, now_th().isoformat(timespec="seconds")),
    )
    conn.commit()
