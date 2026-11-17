"""Export a privacy-safe snapshot for the Looker Studio dashboard.

Usage (from repo root):  python tools/export_dashboard.py
Writes data/dashboard/daily.csv and data/dashboard/orders.csv (data/ is gitignored),
then upload both to the Google Sheet behind the dashboard.

Only analysis columns leave the DB: no account names, notes or bank figures.
Snapshot ends at SNAPSHOT_END so the dashboard matches the numbers quoted in the resume.
Labels are plain English (no locale-dependent dates) so the dashboard reads the same for every viewer.
"""
import csv
import os
from datetime import date
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "dashboard"
SNAPSHOT_END = date(2026, 11, 17)

BAND = {  # token_band -> (English label, sort rank) for the dashboard
    "1. ต่ำกว่า 100": ("Under 100", 1),
    "2. 100-299": ("100–299", 2),
    "3. 300-599": ("300–599", 3),
    "4. 600-1499": ("600–1,499", 4),
    "5. 1500 ขึ้นไป": ("1,500+", 5),
}
SOURCE = {"seller": "Bought Token", "hot_lot": "Bought item lot"}
REASON = {"no_inquiry": "Open, no inquiries", "not_open": "Shop closed",
          "no_close": "Inquiries, no sale", "forgot": "Sold, not recorded"}

DAILY_SQL = """
SELECT log_date, shop_open, no_sale_reason, inquiries, orders,
       revenue_baht, cost_baht, profit_baht, close_rate_pct
FROM v_day WHERE log_date <= %(end)s ORDER BY log_date
"""
ORDERS_SQL = """
SELECT id, sold_on, EXTRACT(HOUR FROM logged_at AT TIME ZONE 'Asia/Bangkok')::int,
       item_count, price_baht, cost_baht, profit_baht, margin_pct, token_band, source
FROM v_sale WHERE sold_on <= %(end)s ORDER BY sold_on, id
"""


def db_url() -> str:
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("DATABASE_URL not found")


def num(v):
    return "" if v is None else float(v)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(db_url()) as conn:
        daily = conn.execute(DAILY_SQL, {"end": SNAPSHOT_END}).fetchall()
        orders = conn.execute(ORDERS_SQL, {"end": SNAPSHOT_END}).fetchall()

    with open(OUT / "daily.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "day_label", "shop_open", "no_sale_reason", "inquiries", "orders",
                    "orders_ma7", "revenue_thb", "cost_thb", "profit_thb", "close_rate_pct"])
        window = []
        for d, op, reason, inq, n, rev, cost, prof, cr in daily:
            window = (window + [n or 0])[-7:]
            ma7 = round(sum(window) / len(window), 2)
            if n:
                reason_txt = "Had sales"
            else:
                reason_txt = REASON.get(reason, "Not specified")
            w.writerow([d.isoformat(), d.strftime("%b ") + str(d.day), "Yes" if op else "No", reason_txt,
                        "" if inq is None else inq, n, ma7, num(rev), num(cost), num(prof), num(cr)])

    with open(OUT / "orders.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["order_id", "date", "hour_logged", "items", "price_thb", "cost_thb",
                    "profit_thb", "margin_pct", "token_band", "band_rank", "stock_source"])
        for oid, d, hr, items, price, cost, prof, m, band, src in orders:
            label, rank = BAND.get(band, (band, 0))
            w.writerow([oid, d.isoformat(), hr, items, num(price), num(cost), num(prof),
                        num(m), label, rank, SOURCE.get(src, src)])

    print(f"daily: {len(daily)} rows · orders: {len(orders)} rows -> {OUT}")


if __name__ == "__main__":
    main()
