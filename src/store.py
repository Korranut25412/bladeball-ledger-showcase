"""
ชั้นสลับฐานข้อมูล — Postgres (Supabase) หรือ SQLite

ทำไมต้องมีไฟล์นี้
-----------------
ย้ายจาก SQLite ไป Postgres แล้ว SQL ที่เขียนไว้ 40 กว่าคำสั่งใน db.py
แทบไม่ต้องแก้เลย เพราะเป็น SQL มาตรฐานอยู่แล้ว สิ่งที่ต่างกันจริงมีแค่ 3 อย่าง
และไฟล์นี้จัดการให้ทั้งสามอย่างที่เดียว

  1) ที่ใส่ค่าลงไปในคำสั่ง SQLite เขียน ?  Postgres เขียน %s
  2) Postgres คืนเงินมาเป็น Decimal และคืนวันที่มาเป็นชนิด date
     ซึ่งบอทคาดว่าจะได้ float กับข้อความ 'YYYY-MM-DD'
     จุดนี้สำคัญมาก เพราะ days_missing_reason() เอา log_date ไปเทียบ
     กับข้อความตรงๆ ถ้าคืนเป็นชนิด date มันจะไม่ตรงและ "เงียบ" ไม่ฟ้อง error
     บอทจะถามหาสาเหตุวันที่ตอบไปแล้วซ้ำๆ โดยไม่มีอะไรเตือน
  3) การเข้าถึงแถว โค้ดเดิมใช้ทั้ง row["ชื่อคอลัมน์"] และ row[0]
     ต้องได้ทั้งสองแบบ

เลือกฐานข้อมูลด้วยตัวแปรสภาพแวดล้อม DATABASE_URL
  มีค่า   -> Postgres (ของจริงบน Supabase)
  ไม่มี   -> SQLite ไฟล์ data/ledger.db (ใช้ตอนรันเทสต์ ไม่ต้องต่อเน็ต)
"""

import os
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SQLITE_PATH = ROOT / "data" / "ledger.db"
SCHEMA_SQLITE = ROOT / "schema.sql"
SCHEMA_PG = ROOT / "schema_pg.sql"

TH = timezone(timedelta(hours=7))


def database_url() -> str:
    """
    ที่อยู่ฐานข้อมูล Postgres — ดูจากตัวแปรสภาพแวดล้อมก่อน แล้วค่อยดูไฟล์ .env

    ต้องอ่าน .env เองที่นี่ด้วย เพราะไฟล์นี้ถูกเรียกใช้โดยตรงจาก
    tools/migrate_to_supabase.py ซึ่งไม่ได้ผ่าน bot.py ที่เป็นคนอ่าน .env
    ถ้าไม่อ่าน จะกลายเป็น "ตั้ง DATABASE_URL ใน .env แล้วแต่ยังต่อ SQLite อยู่"
    ซึ่งไม่มีอะไรฟ้องเลย — จดของจริงลงไฟล์ในเครื่องต่อไปโดยไม่รู้ตัว
    """
    value = (os.environ.get("DATABASE_URL") or "").strip()
    if value:
        return value

    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                return line.partition("=")[2].strip()
    return ""


def backend() -> str:
    """
    'postgres' ถ้าตั้ง DATABASE_URL ไว้ ไม่งั้น 'sqlite'

    LEDGER_FORCE_SQLITE บังคับใช้ SQLite เสมอ ไม่ว่าจะตั้ง DATABASE_URL ไว้ยังไง
    ใช้ในเทสต์เท่านั้น และจำเป็นมาก
    28 ก.ย. 2026 เกือบพัง — พอตั้ง DATABASE_URL เทสต์วิ่งไปที่ Supabase ทันที
    ทั้งที่ตั้ง db.DB_PATH ชี้ไฟล์ทดสอบไว้แล้ว (ค่านั้นมีผลเฉพาะตอนเป็น SQLite)
    เทสต์มี reset() ที่สั่ง DELETE FROM ทุกตาราง = ล้างข้อมูลจริงทิ้งทั้งหมด
    โชคดีที่ตอนนั้น Supabase ยังว่างอยู่
    """
    if os.environ.get("LEDGER_FORCE_SQLITE"):
        return "sqlite"
    return "postgres" if database_url() else "sqlite"


# ---------------------------------------------------------------- แถวข้อมูล

class Row(dict):
    """
    แถวข้อมูลที่เรียกได้ทั้ง row["profit_baht"] และ row[0]

    sqlite3.Row ทำได้สองแบบอยู่แล้ว แต่ Postgres ไม่มีของแบบนี้ให้
    ถ้าใช้ dict เฉยๆ row[0] จะกลายเป็นการหาคีย์ชื่อ 0 แล้วพัง
    """

    def __init__(self, columns, values):
        super().__init__(zip(columns, values))
        self._values = list(values)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


def _clean(value):
    """
    แปลงค่าที่ Postgres คืนมา ให้เป็นชนิดเดียวกับที่ SQLite เคยคืน
    บอททั้งตัวจึงไม่ต้องแก้แม้แต่บรรทัดเดียว

    ลำดับการเช็คสำคัญ: datetime เป็นลูกของ date ต้องเช็ค datetime ก่อน
    ไม่งั้นเวลาจะถูกตัดเหลือแค่วันที่
    """
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        # เขียนลงไปเป็น '...+07:00' ก็ต้องอ่านกลับมาเป็น '...+07:00' เป๊ะ
        return value.astimezone(TH).isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    return value


# ---------------------------------------------------------------- แปลง SQL

_NAMED = re.compile(r"(?<![:\w]):([a-zA-Z_][a-zA-Z0-9_]*)")


def to_postgres(sql: str) -> str:
    """
    แปลงที่ใส่ค่าแบบ SQLite เป็นแบบ Postgres

        ?        ->  %s
        :ชื่อ     ->  %(ชื่อ)s

    ต้องหนี % ที่มีอยู่เดิมก่อน (เช่นใน LIKE '%ดาบ%') ไม่งั้น psycopg
    จะอ่านมันเป็นที่ใส่ค่าแล้วฟ้องว่าจำนวนค่าไม่ครบ
    ส่วน (?<![:\\w]) กันไม่ให้ไปโดน :: ที่เป็นการแปลงชนิดของ Postgres

    ⚠️ เรียกฟังก์ชันนี้เฉพาะคำสั่งที่มีค่าใส่เข้าไปเท่านั้น
    คำสั่งที่ไม่มีค่าใส่ psycopg จะส่ง SQL ไปตรงๆ โดยไม่ตีความ %
    ถ้าเผลอหนี % ให้ด้วย จะกลายเป็น %% หลุดไปอยู่ในคำสั่งจริง
    """
    sql = sql.replace("%", "%%")
    sql = _NAMED.sub(r"%(\1)s", sql)
    return sql.replace("?", "%s")


# ---------------------------------------------------------------- Postgres

class _PgCursor:
    def __init__(self, cur):
        self._cur = cur
        self._columns = ([d.name for d in cur.description]
                         if cur.description else None)

    def _row(self, raw):
        if raw is None:
            return None
        return Row(self._columns, [_clean(v) for v in raw])

    def fetchone(self):
        return self._row(self._cur.fetchone())

    def fetchall(self):
        return [self._row(r) for r in self._cur.fetchall()]

    def __iter__(self):
        for raw in self._cur:
            yield self._row(raw)

    @property
    def rowcount(self):
        return self._cur.rowcount


class PgConnection:
    """
    ห่อ psycopg ให้หน้าตาเหมือน sqlite3.Connection ที่ db.py เคยใช้

    มีการต่อใหม่อัตโนมัติด้วย เพราะบอทต้องรันค้างไว้เป็นเดือนบนเครื่องฟรี
    เน็ตสะดุดทีเดียวแล้วไม่ต่อใหม่ บอทจะเงียบไปเลยจนกว่าจะมีคนไปรีสตาร์ท
    ซึ่งจะไม่มีใครรู้ว่าต้องรีสตาร์ท
    """

    def __init__(self, url: str):
        self._url = url
        self._raw = None
        self._connect()

    def _connect(self):
        import psycopg

        # autocommit=True — แต่ละคำสั่งเป็น transaction ของตัวเอง
        #
        # เดิมตั้งเป็น False แล้วเจอบั๊กซ้อนกัน 2 ตัว (28 ก.ย. 2026)
        #
        #   1) ใน Postgres ทุก SELECT เปิด transaction ให้อัตโนมัติ
        #      ฟังก์ชันที่อ่านอย่างเดียว (job_already_ran, get_state ฯลฯ) ไม่เคย commit
        #      บอทเลยค้างสถานะ "idle in transaction" ถือล็อกตารางไว้ตลอด
        #      สคริปต์อื่นที่จะแก้ VIEW ต้องรอจนหมดเวลา
        #
        #   2) อันตรายกว่า — ถ้ามีคำสั่งไหน error ใน transaction ที่เปิดอยู่
        #      Postgres จะปฏิเสธทุกคำสั่งหลังจากนั้น (InFailedSqlTransaction)
        #      จนกว่าจะ rollback ซึ่งไม่มีใครสั่ง
        #      = เจ้าของพิมพ์อะไรผิดครั้งเดียว บอทใช้ไม่ได้ทั้งตัวจนกว่าจะรีสตาร์ท
        #      พิสูจน์แล้วกับ Supabase จริง: SELECT 1/0 แล้ว SELECT 2 ก็พังตาม
        #
        # SQLite ไม่มีพฤติกรรมข้อ 2 เทสต์เลยจับไม่ได้ ต้องไปเจอบนของจริง
        #
        # ที่ไหนต้องการให้หลายคำสั่งสำเร็จหรือล้มเหลวพร้อมกัน ใช้ transaction() ข้างล่าง
        #
        # prepare_threshold=None ปิดการเตรียมคำสั่งล่วงหน้า ไว้เผื่อวันหลัง
        # เปลี่ยนไปใช้ Transaction pooler ซึ่งไม่รองรับ (Session pooler รองรับ)
        self._raw = psycopg.connect(
            self._url,
            autocommit=True,
            prepare_threshold=None,
            connect_timeout=15,
        )
        # ให้เวลาที่แสดงใน Supabase เป็นเวลาไทย อ่านง่ายกว่าตอนไปนั่งดูเอง
        self._raw.execute("SET TIME ZONE 'Asia/Bangkok'")

    def execute(self, sql: str, params=()):
        import psycopg

        # แปลงเฉพาะตอนมีค่าใส่เข้าไป — ดูเหตุผลใน to_postgres()
        args = params if params else None
        pg_sql = to_postgres(sql) if args is not None else sql
        try:
            cur = self._raw.cursor()
            cur.execute(pg_sql, args)
            return _PgCursor(cur)
        except (psycopg.OperationalError, psycopg.InterfaceError):
            # ต่อหลุด — ต่อใหม่แล้วลองอีกครั้งเดียว
            # ถ้าครั้งที่สองยังพัง ปล่อยให้ error ขึ้นไป อย่าวนซ้ำเงียบๆ
            try:
                self._raw.close()
            except Exception:
                pass
            self._connect()
            cur = self._raw.cursor()
            cur.execute(pg_sql, args)
            return _PgCursor(cur)

    def executescript(self, sql: str):
        """รันหลายคำสั่งรวดเดียว — ใช้ตอนสร้างตารางจาก schema_pg.sql"""
        self._raw.execute(sql)

    def commit(self):
        # autocommit อยู่แล้ว แต่ละคำสั่ง commit ตัวเองไปแล้ว
        # เก็บไว้ให้ db.py เรียกได้เหมือนเดิม ไม่ต้องแก้โค้ด 40 กว่าจุด
        pass

    def rollback(self):
        # autocommit ไม่มีอะไรให้ย้อน ถ้าต้องการย้อนได้ ใช้ transaction()
        pass

    def transaction(self):
        """
        ครอบหลายคำสั่งให้สำเร็จหรือล้มเหลวพร้อมกัน

            with conn.transaction():
                conn.execute(...)
                conn.execute(...)
            # พังตรงไหน ทุกคำสั่งในก้อนนี้ย้อนกลับหมด

        ใช้กับงานที่ครึ่งๆ กลางๆ ไม่ได้ เช่นตัวย้ายข้อมูล
        """
        return self._raw.transaction()

    def close(self):
        self._raw.close()


# ---------------------------------------------------------------- SQLite

class LiteConnection:
    """
    ห่อ sqlite3 ด้วย เพื่อให้คืนแถวเป็น Row ชนิดเดียวกับฝั่ง Postgres

    ถ้าไม่ห่อ เทสต์จะรันบน sqlite3.Row แต่ของจริงรันบน Row ของเรา
    เทสต์ผ่านแต่ของจริงพังก็เกิดขึ้นได้ — ต้องให้เหมือนกันทั้งสองฝั่ง
    """

    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._raw = sqlite3.connect(path)
        self._raw.execute("PRAGMA foreign_keys = ON")

    def execute(self, sql: str, params=()):
        return _LiteCursor(self._raw.execute(sql, params))

    def executescript(self, sql: str):
        self._raw.executescript(sql)
        self._raw.commit()

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def transaction(self):
        """ให้หน้าตาเหมือนฝั่ง Postgres — ดู PgConnection.transaction()"""
        return _LiteTransaction(self._raw)

    def close(self):
        self._raw.close()


class _LiteTransaction:
    """สำเร็จทั้งก้อน = commit · พังตรงไหน = rollback ทั้งก้อน"""

    def __init__(self, raw):
        self._raw = raw

    def __enter__(self):
        self._raw.commit()          # ปิดของค้างก่อน จะได้เริ่มก้อนใหม่สะอาดๆ
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._raw.commit()
        else:
            self._raw.rollback()
        return False                # ปล่อย error ขึ้นไปให้คนเรียกเห็น ไม่กลืนเงียบ


class _LiteCursor:
    def __init__(self, cur):
        self._cur = cur
        self._columns = ([d[0] for d in cur.description]
                         if cur.description else None)

    def _row(self, raw):
        if raw is None:
            return None
        return Row(self._columns, [_clean(v) for v in raw])

    def fetchone(self):
        return self._row(self._cur.fetchone())

    def fetchall(self):
        return [self._row(r) for r in self._cur.fetchall()]

    def __iter__(self):
        for raw in self._cur:
            yield self._row(raw)

    @property
    def rowcount(self):
        return self._cur.rowcount


# ---------------------------------------------------------------- ทางเข้าหลัก

def _expected_columns(schema_sql: str) -> dict:
    """
    อ่านว่าสคีมากำหนดให้แต่ละตารางมีคอลัมน์อะไรบ้าง

    ใช้วิธีสร้างตารางจริงในหน่วยความจำแล้วถาม SQLite เอง
    แทนการแกะข้อความ SQL ด้วยมือ ซึ่งพลาดง่ายมากเวลาเจอ CHECK หลายบรรทัด
    """
    mem = sqlite3.connect(":memory:")
    mem.executescript(schema_sql)
    out = {}
    for (table,) in mem.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name NOT LIKE 'sqlite_%'"):
        out[table] = [
            {"name": r[1], "type": r[2], "notnull": r[3], "default": r[4]}
            for r in mem.execute(f"PRAGMA table_info({table})")
        ]
    mem.close()
    return out


def sync_columns(conn, schema_sql: str, backend_name: str) -> list:
    """
    เติมคอลัมน์ที่สคีมามีแต่ฐานข้อมูลจริงยังไม่มี

    ทำไมต้องมี
    ----------
    CREATE TABLE IF NOT EXISTS ไม่แตะตารางที่มีอยู่แล้ว
    เพิ่มคอลัมน์ใน schema.sql อย่างเดียวจึงไม่พอ ฐานข้อมูลจริงจะยังไม่มี
    แล้วพังตอน INSERT ว่า "table sale has no column named ..."

    เกิดขึ้นจริง 27 ก.ย. 2026 — เพิ่มคอลัมน์ account แล้วบอทจดของไม่ได้เลย
    เทสต์ไม่จับ เพราะเทสต์สร้างฐานข้อมูลใหม่ทุกครั้ง ซึ่งมีคอลัมน์ครบอยู่แล้ว
    ความต่างระหว่าง "ฐานใหม่" กับ "ฐานเก่าที่ใช้มาแล้ว" คือช่องโหว่ที่ต้องปิด

    ทำเฉพาะการเติมคอลัมน์ ไม่ลบและไม่แก้ชนิดข้อมูล
    เพราะสองอย่างนั้นทำข้อมูลหายได้ ต้องให้คนตัดสินใจเอง (ดู tools/)
    """
    expected = _expected_columns(schema_sql)
    added = []
    for table, columns in expected.items():
        if backend_name == "postgres":
            have = {r["column_name"] for r in conn.execute(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_schema = 'public' AND table_name = ?",
                (table,)).fetchall()}
        else:
            have = {r[1] for r in conn.execute(
                f"PRAGMA table_info({table})").fetchall()}
        if not have:
            continue                       # ตารางเพิ่งถูกสร้าง ครบอยู่แล้ว

        for col in columns:
            if col["name"] in have:
                continue
            piece = f"{col['name']} {col['type']}"
            if col["default"] is not None:
                piece += f" DEFAULT {col['default']}"
                if col["notnull"]:
                    piece = (f"{col['name']} {col['type']} NOT NULL"
                             f" DEFAULT {col['default']}")
            elif col["notnull"]:
                # เพิ่มคอลัมน์ NOT NULL ที่ไม่มีค่าปริยายลงตารางที่มีข้อมูลอยู่ไม่ได้
                # ต้องให้คนไปเขียนสคริปต์ย้ายข้อมูลเอง
                raise RuntimeError(
                    f"คอลัมน์ {table}.{col['name']} เป็น NOT NULL แต่ไม่มีค่าปริยาย "
                    f"เติมเข้าตารางที่มีข้อมูลอยู่แล้วไม่ได้ "
                    f"— ต้องเขียนสคริปต์ย้ายข้อมูลใน tools/")
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {piece}")
            added.append(f"{table}.{col['name']}")
    if added:
        conn.commit()
    return added


def split_schema(sql: str):
    """
    แยกสคีมาเป็น (ส่วนตาราง, ส่วน VIEW)

    ส่วนตาราง (CREATE TABLE IF NOT EXISTS) รันได้เสมอ ไม่ชนใคร
    ส่วน VIEW ต้อง DROP แล้วสร้างใหม่ ซึ่งต้องล็อก VIEW นั้นแบบห้ามใครแตะ
    ถ้ามีการเชื่อมต่ออื่นกำลังอ่าน VIEW อยู่ จะต้องรอ
    """
    i = sql.find("DROP VIEW IF EXISTS")
    if i == -1:
        return sql, ""
    return sql[:i], sql[i:]


def _refresh_views(conn, views_sql: str) -> bool:
    """
    สร้าง VIEW ใหม่ แต่ยอมแพ้ถ้ารอล็อกเกิน 5 วินาที — คืน True ถ้าสำเร็จ

    ทำไมต้องยอมแพ้ได้
    ----------------
    28 ก.ย. 2026 deploy ล้มติดกัน 2 รอบ แล้วบอทติดอยู่กับโค้ดที่มีบั๊ก
      บอทตัวเก่าค้าง transaction ถือล็อก VIEW ไว้ไม่ปล่อย (บั๊ก autocommit)
      บอทตัวใหม่เริ่ม → จะสร้าง VIEW ใหม่ → รอล็อกของตัวเก่า
      Supabase ตัดคำสั่งที่รอเกิน 2 นาที (statement_timeout) → ตัวใหม่ crash
      Render ถือว่า deploy ล้ม เลยเก็บตัวเก่าที่มีบั๊กไว้ต่อ
      = บั๊กขวางไม่ให้ตัวแก้บั๊กขึ้นมาได้ ทุกครั้งที่ push แก้ก็ล้มแบบเดิม

    ถ้ารอไม่ไหว ข้ามไปใช้ VIEW ที่มีอยู่แล้ว บอทเริ่มทำงานได้
    Render จะเห็นว่าตัวใหม่พร้อม แล้วค่อยปิดตัวเก่าให้เอง
    รีสตาร์ทครั้งถัดไปไม่มีใครถือล็อกแล้ว VIEW จะถูกสร้างใหม่ตามปกติ

    ⚠️ ข้อจำกัด: ถ้า deploy ไหนแก้หน้าตา VIEW แล้วดันข้าม
    โค้ดใหม่จะเจอ VIEW หน้าตาเก่าจนกว่าจะรีสตาร์ท — มีข้อความเตือนให้เห็น
    """
    import psycopg
    try:
        conn.execute("SET lock_timeout = '5s'")
        conn.executescript(views_sql)
        return True
    except (psycopg.errors.LockNotAvailable, psycopg.errors.QueryCanceled):
        return False
    finally:
        conn.execute("SET lock_timeout = 0")


def connect(sqlite_path=None):
    """
    เปิดการเชื่อมต่อ สร้างตารางที่ยังไม่มี และเติมคอลัมน์ที่ยังขาด

    sqlite_path ใส่ไว้ให้เทสต์ชี้ไปไฟล์ของตัวเอง ไม่ไปแตะข้อมูลจริง
    """
    if backend() == "postgres":
        conn = PgConnection(database_url())
        tables_sql, views_sql = split_schema(SCHEMA_PG.read_text(encoding="utf-8"))
        conn.executescript(tables_sql)
        if views_sql and not _refresh_views(conn, views_sql):
            print("⚠️  มีการเชื่อมต่ออื่นถือ VIEW อยู่ ข้ามการสร้าง VIEW ใหม่ "
                  "ใช้ของเดิมไปก่อน (ปกติเกิดตอน deploy ที่ตัวเก่ายังไม่ปิด)")
        # ฝั่ง Postgres เทียบกับสคีมา SQLite เพราะชื่อคอลัมน์ต้องตรงกันอยู่แล้ว
        # (มีเทสต์คุมไว้ใน tests/smoke.py)
        added = sync_columns(conn, SCHEMA_SQLITE.read_text(encoding="utf-8"),
                             "postgres")
    else:
        conn = LiteConnection(sqlite_path or SQLITE_PATH)
        schema = SCHEMA_SQLITE.read_text(encoding="utf-8")
        conn.executescript(schema)
        added = sync_columns(conn, schema, "sqlite")

    if added:
        print(f"อัปเดตโครงฐานข้อมูล เติมคอลัมน์: {', '.join(added)}")
    return conn
