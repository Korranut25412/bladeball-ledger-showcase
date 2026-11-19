# เทสต์ autopost.py — กันลงซ้ำ (บั๊ก 19 พ.ย. 2569) + เลือกกลุ่มที่ถึงคิวจากล็อก + เรียงกลุ่มใหญ่ก่อน
# รัน: python posting/test_autopost.py   (ไม่แตะคิว/ล็อกจริง ไม่รัน prep.py ไม่เปิดเบราว์เซอร์)
import contextlib
import io
import pathlib
import sys
import tempfile
from datetime import datetime, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import autopost as A  # noqa: E402

tmp = pathlib.Path(tempfile.mkdtemp())
A.QUEUE = tmp / "queue.json"   # ชี้ไปไฟล์ชั่วคราว — ห้ามให้เทสต์เขียนทับคิว/ล็อกจริง
A.LOG = tmp / "log.md"
rounds = []


def fake_round(q_old, due):
    # แทน prep.py จริง (ช้า + ล้างโฟลเดอร์ ready/) — แค่จดว่าจะเริ่มรอบกับกลุ่มไหน
    rounds.append(list(due))
    sys.exit("NEW_ROUND")


A.new_round = fake_round
N = len(A.GROUPS)


def th(hours_ago):
    t = datetime.now() - timedelta(hours=hours_ago)
    return f"{t.day} {A.TH_MONTH[t.month]} {t.year + 543} {t:%H:%M}"


def write_log(rows, note=True):
    body = "# ล็อก\n\n## ล็อกออโต้ (x)\n| เวลา | กลุ่ม | โพสต์ |\n|---|---|---|\n"
    body += "".join(f"| {th(h)} | {A.GROUPS[g]['name']} | 1 รับซื้อ |\n" for g, h in rows)
    if note:
        body += "- 19 พ.ย. 12:54 หมายเหตุ ต้องไม่ถูกอ่านเป็นแถว\n"
    A.LOG.write_text(body, encoding="utf-8")


def run(*args):
    sys.argv = ["autopost.py", *args]
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            A.main()
    except SystemExit as e:
        return out.getvalue() + str(e.code)
    return out.getvalue()


def fresh_queue_done():
    A.save({"tab": 1, "fails": 0, "items": [{"g": 0, "p": 1, "status": "done", "at": "x"}]})


cases = 0


def check(cond, msg):
    global cases
    assert cond, msg
    cases += 1


# 1 ตั้งค่ากลุ่ม: 15 กลุ่ม · versions/url ไม่ซ้ำ (ซ้ำ = สองกลุ่มได้ข้อความเดียวกัน บั๊ก 17 พ.ย.) · เรียงตามชื่อเดิม 4 กลุ่มแรก
check(N == 15 and len({g["v"] for g in A.GROUPS}) == N and len({g["url"] for g in A.GROUPS}) == N, "GROUPS ซ้ำ")
check(A.GROUPS[0]["name"].startswith("2 ") and A.GROUPS[3]["name"].startswith("7 "), "ชื่อ 4 กลุ่มแรกถูกแก้ = จับคู่ล็อกเก่าไม่ได้")

# 2 ทุกกลุ่มเพิ่งลง → TOO_SOON ไม่เริ่มรอบ
write_log([(g, 0.5) for g in range(N)]); fresh_queue_done(); rounds.clear()
r = run("next"); check("TOO_SOON" in r and not rounds, r)

# 3 กลุ่มใหญ่ 4 กลุ่มเพิ่งลง (เคสวันนี้) → รอบใหม่ได้เฉพาะ 11 กลุ่มเล็ก เรียงมาก→น้อย
write_log([(g, 0.5) for g in range(4)]); fresh_queue_done(); rounds.clear()
r = run("next"); check(rounds == [list(range(4, N))], f"{r} {rounds}")

# 4 ลงไปนานพอแล้ว → ได้ครบทุกกลุ่ม
write_log([(g, 4) for g in range(N)]); fresh_queue_done(); rounds.clear()
run("next"); check(rounds == [list(range(N))], rounds)

# 5 force → ลงทุกกลุ่มแม้เพิ่งลง (ผู้ใช้ยืนยันเองเท่านั้น)
write_log([(g, 0.5) for g in range(N)]); fresh_queue_done(); rounds.clear()
run("force", "next"); check(rounds == [list(range(N))], rounds)

# 6 ไม่มีล็อกออโต้เลย → ทุกกลุ่มถึงคิว
A.LOG.write_text("# ว่าง\n", encoding="utf-8"); A.QUEUE.unlink(); rounds.clear()
run("next"); check(rounds == [list(range(N))], rounds)

# 7 เวลาลงล่าสุดใช้ค่ามากสุด (ล็อกไม่ได้เรียงเวลาเสมอ) · แถวหมายเหตุไม่นับ
write_log([(0, 10), (0, 0.5), (1, 10)])
last = A.last_posted()
check(set(last) == {0, 1} and datetime.now() - last[0] < timedelta(hours=1), last)

# 8 done ตัวสุดท้าย → ล็อกได้แถวใหม่ทันที → next รอบหน้าข้ามกลุ่มนั้น (เคส done next ส่งพร้อม BATCH2)
write_log([]); rounds.clear()
A.save({"tab": 1, "fails": 0, "items": [{"g": 2, "p": 6, "status": "pending"}]})
r = run("done", "next"); check("ROUND_COMPLETE" in r and not rounds, r)
run("next"); check(rounds and 2 not in rounds[-1] and 0 in rounds[-1], rounds)

# 9 undo ลบแถวล็อก → กลุ่มนั้นกลับมาถึงคิว
run("undo"); check(2 not in A.last_posted(), A.last_posted())

print(f"ผ่านหมด {cases} เคส")
