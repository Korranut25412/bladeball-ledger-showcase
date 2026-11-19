#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
autopost.py — คิวโพสต์ "โพสเลย" แบบออโต้ (ผู้ใช้สั่ง 18 พ.ย. 2569)

ทำไมต้องมี
  - ผู้ใช้อยากพิมพ์แค่ "โพสเลย" แล้วไม่ต้องคุยอะไรอีก ยกเว้นเจอบั๊กจริง
  - เดิม Claude ต้องคิดเองทุกโพสต์ (หาปุ่ม หา file input เช็กแฮช) ใช้ ~8 รอบเครื่องมือ/โพสต์
    → สคริปต์นี้พิมพ์คำสั่งเบราว์เซอร์สำเร็จรูปให้ก๊อปไปใช้ได้เลย เหลือ 3 รอบ/โพสต์
  - คิวเก็บในไฟล์ → แชทหลุด/ถูกเคลียร์กลางทาง แชทใหม่พิมพ์ "โพสเลย" ก็ลงต่อจากที่ค้างได้ทันที

กลุ่ม: ทุกกลุ่ม 15 กลุ่ม เรียงสมาชิกมาก→น้อย (18 พ.ย. เฉพาะ ≥3 หมื่น · 19 พ.ย. ผู้ใช้สั่งเพิ่มกลุ่มเล็ก)
  รอบใหม่ = เฉพาะกลุ่มที่ล็อกบอกว่าลงไปแล้ว ≥ MIN_GAP_HOURS (หรือไม่เคยลง) → กลุ่มที่เพิ่งลงข้ามเอง

ใช้งาน (สั่งต่อกันได้ในบรรทัดเดียว ทำทีละคำจากซ้ายไปขวา):
  python posting/autopost.py tab <tabId> next   ตั้งแท็บ Chrome แล้วขอโพสต์ถัดไป
  python posting/autopost.py done next          โพสต์เมื่อกี้ขึ้นแล้ว → ขอโพสต์ถัดไป
  python posting/autopost.py fail <เหตุผล>       โพสต์เมื่อกี้พัง (ครบ 2 ครั้งติด = STOP)
  python posting/autopost.py undo               ย้อน done ล่าสุด (ใช้เมื่อสั่ง done พร้อม BATCH2 แล้ว BATCH2 ไม่ผ่าน)
  python posting/autopost.py status             ดูคิว
  python posting/autopost.py force next         เริ่มรอบใหม่ทั้งที่รอบก่อนเพิ่งจบ (ผู้ใช้ยืนยันเองเท่านั้น)
คิวหมด → next จะรัน prep.py ทำรูป/ข้อความชุดใหม่ แล้วเริ่มรอบใหม่เอง
  แต่ถ้าทุกกลุ่มลงไปไม่ถึง MIN_GAP_HOURS → พิมพ์ TOO_SOON แล้วหยุด (กันลงซ้ำ ดูบั๊ก 19 พ.ย. ด้านล่าง)

บั๊ก 19 พ.ย. 2569: รอบจบ 12:50 แล้วแชทใหม่พิมพ์ "โพสเลย" อีกที (ไฟล์สถานะเก่ายังเขียนว่าค้าง 3/24)
  → next เห็นคิวหมด เลยเริ่มรอบใหม่เงียบๆ 12:53 แล้วลงกลุ่ม 2 ซ้ำทันที (ผู้ใช้ต้องตามลบเอง)
  ต้นเหตุ: "คิวหมด" มีได้ 2 ความหมาย (ยังไม่เคยเริ่ม / เพิ่งลงครบ) แต่โค้ดเดิมตีความเป็นอย่างแรกเสมอ
  แก้: ก่อนเริ่มรอบใหม่ อ่านเวลาลงล่าสุดของแต่ละกลุ่มจากล็อก (last_posted) แล้วเอาเฉพาะกลุ่มที่ถึงคิว
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import clip  # noqa: E402  ใช้ฟังก์ชัน put() ตัวเดียวกับ clip.py เพื่อให้แฮชตรงกันแน่นอน

QUEUE = ROOT / "ready" / "queue.json"
LOG = ROOT / "โพสต์บอล.md"

# v = เลข versions ของกลุ่มนั้น (ดู "เลขกลุ่ม → versions" ใน โพสต์บอล.md) ห้ามเปลี่ยน
# ไม่งั้นสองกลุ่มอาจได้ข้อความซ้ำกันวันเดียวกัน
# เรียงสมาชิกมาก→น้อย (เช็ก 18 พ.ย. 2569 13:15) = ลำดับลง · ลงกลุ่มใหญ่ก่อนเพราะคนเห็นเยอะสุด
# ถ้าโดนบล็อกกลางรอบ กลุ่มที่สำคัญสุดจะได้ลงไปแล้ว
# "name" ของ 4 กลุ่มแรกห้ามแก้ — เป็นตัวจับคู่กับแถวในล็อก (ใช้หาว่ากลุ่มไหนเพิ่งลง)
# กลุ่ม 5 ไม่มี: ถูกพักตั้งแต่ 23 ก.ย. 2569 · กลุ่มเล็ก 11 กลุ่มเพิ่ม 19 พ.ย. 2569 (ผู้ใช้สั่ง)
GROUPS = [
    {"name": "2 Blade Ball ซื้อขาย-แลกเปลี่ยน (1.6แสน)", "url": "https://www.facebook.com/groups/673038523576145", "v": 1},
    {"name": "1 Blade ball Community th (1.2แสน)", "url": "https://www.facebook.com/groups/197321643036799", "v": 0},
    {"name": "ใหม่1 ใบมีดบอล (3.3หมื่น)", "url": "https://www.facebook.com/groups/swordsoflegendsm", "v": 8},
    {"name": "7 แอดช้าง (3.1หมื่น)", "url": "https://www.facebook.com/groups/327183536241985", "v": 5},
    {"name": "8 Blade ball /ซื้อ ขาย (2.3หมื่น)", "url": "https://www.facebook.com/groups/889541752442083", "v": 6},
    {"name": "6 ดาบ/ไอดีในเบลดบอล (1.4หมื่น)", "url": "https://www.facebook.com/groups/1280214692640059", "v": 4},
    {"name": "3 Blade Ball Thailand (3.5พัน)", "url": "https://www.facebook.com/groups/840436550980540", "v": 2},
    {"name": "4 Blade ball ซื้อขาย แลกเปลี่ยน TH (3.5พัน)", "url": "https://www.facebook.com/groups/8912930528829931", "v": 3},
    {"name": "ใหม่5 ซื้อ-ขาย แลกเปลี่ยน พูดคุย (2.2พัน)", "url": "https://www.facebook.com/groups/489826209529557", "v": 12},
    {"name": "ใหม่2 ซื้อขาย-แลกเปลี่ยน Bladeball (1.2พัน)", "url": "https://www.facebook.com/groups/1364464690843467", "v": 9},
    {"name": "ใหม่3 Blade Ball / ซื้อ-ขาย Thai (1พัน)", "url": "https://www.facebook.com/groups/525423443442689", "v": 10},
    {"name": "ใหม่6 Blade Ball ซื้อขาย-แลกเปลี่ยน 705 (361)", "url": "https://www.facebook.com/groups/705200611422342", "v": 13},
    {"name": "ใหม่4 Blade Ball ซื้อขาย 303 (345)", "url": "https://www.facebook.com/groups/303276035720987", "v": 11},
    {"name": "ใหม่8 ซื้อ-ขาย-แลก-เปลี่ยน Thailand (341)", "url": "https://www.facebook.com/groups/549161780706973", "v": 15},
    {"name": "ใหม่7 (Roblox)-Blade Ball (56)", "url": "https://www.facebook.com/groups/1079737141606599", "v": 14},
]
BY_NAME = {g["name"]: i for i, g in enumerate(GROUPS)}
# ช่องว่างขั้นต่ำระหว่างรอบ — ผู้ใช้เลิกกฎ 24 ชม. แล้ว (สั่งเมื่อไหร่ลงเมื่อนั้น)
# ค่านี้มีไว้จับ "สั่งซ้ำโดยไม่ตั้งใจ" เท่านั้น ไม่ใช่กฎความถี่ · ตั้งใจลงถี่กว่านี้ใช้ force
MIN_GAP_HOURS = 3
POSTS = ["รับซื้อ", "ระเบิด", "emote", "ดาบ", "ดาบติดตูด", "เซ็ตดาบ"]
TH_MONTH = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]


def esc(js):
    """แปลงตัวอักษรไทยใน JS เป็น \\uXXXX — Claude พิมพ์ไทยแล้วเคยเพี้ยน (บั๊ก 17 พ.ย.)
    เป็น ASCII ล้วนแล้วก๊อปไปวางยังไงก็ไม่เพี้ยน"""
    return "".join(c if ord(c) < 128 else "\\u%04x" % ord(c) for c in js)


# ขึ้นต้น await เพราะ javascript_tool ไม่รอ Promise เอง (ได้ {} กลับมา เจอ 18 พ.ย.)
# เปิดกล่องเขียนโพสต์ของกลุ่ม แล้วโฟกัสช่องพิมพ์ (รอปุ่ม/กล่องขึ้นสูงสุด ~12 วิ เพราะหน้ากลุ่มใหญ่โหลดช้า)
JS_OPEN = esc(r"""await (async()=>{const w=ms=>new Promise(r=>setTimeout(r,ms));let b;for(let i=0;i<20&&!b;i++){b=[...document.querySelectorAll('[role=button]')].find(x=>x.innerText.trim().startsWith('เขียนอะไรสักหน่อย'));if(!b)await w(400);}if(!b)return 'NO_COMPOSER';b.click();for(let i=0;i<20;i++){await w(300);const t=[...document.querySelectorAll('[role=dialog] [contenteditable=true][role=textbox]')].pop();if(t){t.focus();return 'OPEN';}}return 'NO_DIALOG';})()""")

# เช็กแฮชข้อความที่วาง (ตรรกะเดียวกับ fb_check.js) แล้วป้าย file input ของกล่องนี้ว่า UPLOADHERE ให้ find เจอ
JS_CHECK = esc(r"""((W)=>{const box=[...document.querySelectorAll('[role=dialog] [contenteditable=true][role=textbox]')].pop();if(!box)return 'NO_DIALOG';const s=box.innerText.replace(/[​-‍﻿]/g,'').replace(/\s+/g,' ').trim();if(/https?:\/\//.test(s))return 'HAS_LINK';let h=0x811c9dc5;for(const c of s)h=Math.imul((h^c.codePointAt(0))>>>0,0x01000193)>>>0;const got=h.toString(16).padStart(8,'0');if(got!==W)return 'MISMATCH '+got;const el=[...document.querySelectorAll('input[type=file]')].find(e=>e.accept.includes('image')&&e.closest('[role=dialog]')&&e.closest('[role=dialog]').contains(box));if(!el)return 'NO_FILE_INPUT';el.setAttribute('aria-label','UPLOADHERE');el.style.cssText='display:block;position:fixed;top:60px;left:10px;width:80px;height:30px;opacity:1;z-index:99999';return 'OK';})('HASH')""")

# เช็กแฮชซ้ำ + รูปอัปเสร็จ (ไม่มีแถบโหลด) แล้วค่อยกดโพสต์
# ไม่นับจำนวนรูปเป๊ะ เพราะ FB ทำ collage แสดงแค่ ~5 รูป + "+5" (เจอ 18 พ.ย.)
JS_POST = esc(r"""await (async(W)=>{const w=ms=>new Promise(r=>setTimeout(r,ms));for(let i=0;i<40;i++){const box=[...document.querySelectorAll('[role=dialog] [contenteditable=true][role=textbox]')].pop();if(!box)return 'NO_DIALOG';const s=box.innerText.replace(/[​-‍﻿]/g,'').replace(/\s+/g,' ').trim();let h=0x811c9dc5;for(const c of s)h=Math.imul((h^c.codePointAt(0))>>>0,0x01000193)>>>0;if(h.toString(16).padStart(8,'0')!==W)return 'MISMATCH';const d=box.closest('[role=dialog]');const imgs=d.querySelectorAll('img[src^="blob:"]').length;const b=[...d.querySelectorAll('[role=button]')].find(x=>x.innerText.trim()==='โพสต์');if(imgs&&!d.querySelector('[role=progressbar]')&&b&&b.getAttribute('aria-disabled')!=='true'){b.click();return 'CLICKED imgs='+imgs;}await w(1000);}return 'UPLOAD_TIMEOUT';})('HASH')""")

# รอกล่องปิด (= โพสต์ขึ้น) · ดูข้อความเตือนเฉพาะใน dialog/alert ไม่ดูทั้งหน้า (ฟีดอาจมีคำว่า "บล็อก" ในโพสต์คนอื่น)
JS_RESULT = esc(r"""await (async()=>{for(let i=0;i<20;i++){const t=[...document.querySelectorAll('[role=dialog],[role=alert]')].map(x=>x.innerText).join(' ');if(/Action Blocked|ถูกบล็อก|เร็วเกินไป|ถูกจำกัด|จำกัดการใช้งาน/.test(t))return 'BLOCKED';if(/เกิดข้อผิดพลาด/.test(t))return 'FB_ERROR';const open=[...document.querySelectorAll('[role=dialog]')].some(x=>x.querySelector('[contenteditable=true][role=textbox]'));if(!open)return /ผู้ดูแล/.test(t)?'POSTED_PENDING_ADMIN':'POSTED';await new Promise(r=>setTimeout(r,1000));}return 'STILL_OPEN';})()""")


def load():
    return json.loads(QUEUE.read_text(encoding="utf-8")) if QUEUE.exists() else None


def save(q):
    QUEUE.write_text(json.dumps(q, ensure_ascii=False, indent=1), encoding="utf-8")


def now_th():
    n = datetime.now()
    return f"{n.day} {TH_MONTH[n.month]} {n.year + 543} {n:%H:%M}"


def new_round(q_old, due):
    # รูป/หัวข้อความสุ่มใหม่ทุกรอบ ช่วยไม่ให้ FB มองว่าโพสต์ซ้ำ
    r = subprocess.run([sys.executable, str(ROOT / "prep.py")], capture_output=True, encoding="utf-8")
    if r.returncode:
        sys.exit("STOP prep.py พัง:\n" + (r.stderr or r.stdout)[-800:])
    # ลงทีละกลุ่มให้ครบ 1–6 ก่อนย้ายกลุ่ม (ไม่สลับ) — บล็อกกลางทางจะเหลือกลุ่มที่ลงครบ ไม่ใช่ลงครึ่งๆ ทุกกลุ่ม
    q = {"started": now_th(), "tab": (q_old or {}).get("tab"), "fails": 0,
         "items": [{"g": gi, "p": p, "status": "pending"} for gi in due for p in range(1, 7)]}
    save(q)
    return q


def pending(q):
    return next((it for it in q["items"] if it["status"] == "pending"), None) if q else None


def count(q):
    return sum(it["status"] == "done" for it in q["items"]), len(q["items"])


def log_row(it):
    text = LOG.read_text(encoding="utf-8")
    if "## ล็อกออโต้" not in text:
        text = text.rstrip("\n") + "\n\n## ล็อกออโต้ (autopost.py · ลิงก์ดูที่ my_posted_content ของแต่ละกลุ่ม)\n| เวลา | กลุ่ม | โพสต์ |\n|---|---|---|\n"
    g = GROUPS[it["g"]]
    text = text.rstrip("\n") + f"\n| {it['at']} | {g['name']} | {it['p']} {POSTS[it['p'] - 1]} |\n"
    LOG.write_text(text, encoding="utf-8")


def last_posted():
    """{เลขกลุ่ม: datetime ที่ลงล่าสุด} อ่านจากตาราง "ล็อกออโต้" ในโพสต์บอล.md
    ทำไมอ่านจากล็อก ไม่ใช่จากคิว: บั๊ก 19 พ.ย. เกิดเพราะเชื่อไฟล์สถานะ/คิวที่ไม่ตรงความจริง
    ล็อกคือสิ่งที่ตรงกับ FB ที่สุด (ลบโพสต์ = ลบแถว) และไม่หายแม้ prep.py ล้างโฟลเดอร์ ready/
    กลุ่มที่ไม่มีแถวในล็อกออโต้ = ไม่เคยลงผ่านระบบนี้ (ลงมือครั้งล่าสุด 17 พ.ย.) → ถือว่าถึงคิว"""
    text = LOG.read_text(encoding="utf-8") if LOG.exists() else ""
    if "## ล็อกออโต้" not in text:
        return {}
    out = {}
    for line in text.split("## ล็อกออโต้", 1)[1].split("\n"):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[1] not in BY_NAME:
            continue
        try:
            d, mon, y, hm = cells[0].split()
            t = datetime.strptime(f"{int(y) - 543}-{TH_MONTH.index(mon)}-{d} {hm}", "%Y-%m-%d %H:%M")
        except ValueError:
            continue  # แถวรูปแบบอื่น (หมายเหตุ) ข้าม
        gi = BY_NAME[cells[1]]
        out[gi] = max(out.get(gi, t), t)
    return out


def due_groups(force=False):
    """กลุ่มที่ถึงคิวลง เรียงตาม GROUPS (มาก→น้อย) · กลุ่มที่ลงไปไม่ถึง MIN_GAP_HOURS ข้าม"""
    if force:
        return list(range(len(GROUPS))), {}
    last, now = last_posted(), datetime.now()
    due = [i for i in range(len(GROUPS)) if i not in last or now - last[i] >= timedelta(hours=MIN_GAP_HOURS)]
    return due, last


def cmd_next(q, force=False):
    if not pending(q):
        due, last = due_groups(force)
        if not due:
            # ทุกกลุ่มเพิ่งลง → ไม่เริ่มรอบ (กันลงซ้ำ บั๊ก 19 พ.ย.)
            # print ลง stdout (ตั้ง utf-8 แล้ว) — sys.exit("ข้อความ") ออก stderr ที่ยังเป็น cp1252 ไทยเพี้ยน
            soon = min(last.values()) + timedelta(hours=MIN_GAP_HOURS)
            print(f"TOO_SOON ทุกกลุ่มลงไปไม่ถึง {MIN_GAP_HOURS} ชม. → ไม่เริ่มรอบใหม่ · "
                  f"กลุ่มแรกถึงคิว {soon:%d/%m %H:%M} · ผู้ใช้ยืนยันจะลงซ้ำ: python posting/autopost.py force next")
            sys.exit(1)
        q = new_round(q, due)
        skipped = [GROUPS[i]["name"] for i in range(len(GROUPS)) if i not in due]
        print(f"ROUND {len(due)} กลุ่ม × 6 = {len(due) * 6} โพสต์" + (f" | ข้าม (เพิ่งลง): {', '.join(skipped)}" if skipped else ""))
    if not q.get("tab"):
        sys.exit("STOP ยังไม่ได้ตั้งแท็บ → python posting/autopost.py tab <tabId> next")
    it = pending(q)
    g = GROUPS[it["g"]]
    key, h, ok, _ = clip.put(g["v"], it["p"])
    if not ok:
        sys.exit("STOP คลิปบอร์ดโดนทับ (clip.put ไม่ตรง) ลองสั่ง next ใหม่ 1 ครั้ง")
    batches = json.loads((ROOT / "ready" / "today.json").read_text(encoding="utf-8"))["posts"][it["p"] - 1]["batches"]
    if len(batches) != 1:
        # file_upload รับได้ ≤10MB/ครั้ง prep.py จึงอาจแบ่งเป็นหลายชุด แต่ flow นี้อัปครั้งเดียว → รูปชุดหลังจะหายเงียบๆ
        sys.exit(f"STOP โพสต์ {it['p']} มีรูป {len(batches)} ชุด (flow อัปได้ชุดเดียว) ต้องย่อรูปก่อน")
    files = batches[0]
    t = q["tab"]
    js = lambda code: {"name": "javascript_tool", "input": {"action": "javascript_exec", "tabId": t, "text": code}}
    wait = lambda s: {"name": "computer", "input": {"action": "wait", "duration": s, "tabId": t}}
    key_ = lambda k, why: {"name": "computer", "input": {"action": "key", "text": k, "tabId": t, "action_summary": why}}
    b1 = [{"name": "navigate", "input": {"url": g["url"], "tabId": t}}, js(JS_OPEN),
          key_("ctrl+a", "Selects any leftover draft text in the composer"),
          key_("Delete", "Clears leftover draft text"),
          key_("ctrl+v", "Pastes the post text into the composer"), wait(2),
          js(JS_CHECK.replace("HASH", h)),
          {"name": "find", "input": {"query": "UPLOADHERE file input", "tabId": t}}]
    # JS_POST รอรูปอัปเสร็จเองสูงสุด ~40 วิ จึงไม่ต้องมีชุด RETRY แยก (ลด token ที่ต้องอ่าน/ก๊อปทุกโพสต์)
    b2 = [wait(10), js(JS_POST.replace("HASH", h)), wait(3), js(JS_RESULT)]
    done, total = count(q)
    # JSON แบบไม่มีช่องว่าง = สั้นลง ~10% ทั้งตอนอ่านและตอนก๊อปไปใส่เครื่องมือ
    J = lambda x: json.dumps(x, ensure_ascii=False, separators=(",", ":"))
    print(f"NEXT {done + 1}/{total} | {g['name']} | โพสต์ {it['p']} {POSTS[it['p'] - 1]} | รูป {len(files)} | hash={h}")
    print("BATCH1=" + J(b1))
    print("UPLOAD_PATHS=" + J(files))
    print("BATCH2=" + J(b2))
    return q


def main():
    args = sys.argv[1:] or ["status"]
    q = load()
    force = False
    while args:
        a = args.pop(0)
        if a == "force":
            force = True  # มีผลกับ next ตัวถัดไปในบรรทัดเดียวกันเท่านั้น
        elif a == "tab":
            q = q or {"items": [], "fails": 0}
            q["tab"] = int(args.pop(0))
            save(q)
        elif a == "next":
            q = cmd_next(q, force)
            force = False
        elif a == "done":
            it = pending(q)
            if not it:
                sys.exit("STOP ไม่มีโพสต์ค้างให้ done")
            it["status"], it["at"], q["fails"] = "done", now_th(), 0
            d, tot = count(q)
            if d == tot:
                q["finished"] = datetime.now().isoformat(timespec="minutes")  # ให้ next รอบหน้าเช็ก TOO_SOON ได้
            save(q)
            log_row(it)
            if d == tot:
                print(f"ROUND_COMPLETE {d}/{tot}")
                return  # จบรอบ ไม่เริ่มรอบใหม่ต่อเองแม้มี next ตามมา
            print(f"DONE {d}/{tot}")
        elif a == "undo":
            # ใช้เมื่อสั่ง "done next" พร้อม BATCH2 ไปแล้ว แต่ BATCH2 ไม่ได้ POSTED → ย้อนตัวล่าสุดกลับเป็นค้าง
            dones = [x for x in (q or {}).get("items", []) if x["status"] == "done"]
            if not dones:
                sys.exit("STOP ไม่มีอะไรให้ undo")
            last = max(dones, key=lambda x: q["items"].index(x))
            last["status"] = "pending"
            last.pop("at", None)
            q.pop("finished", None)  # ย้อนตัวสุดท้ายของรอบ = รอบยังไม่จบ
            save(q)
            lines = LOG.read_text(encoding="utf-8").rstrip("\n").split("\n")
            if lines[-1].startswith("| ") and GROUPS[last["g"]]["name"] in lines[-1]:
                LOG.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
            print(f"UNDO {GROUPS[last['g']]['name']} โพสต์ {last['p']}")
        elif a == "fail":
            reason = " ".join(args)
            args = []
            q["fails"] = q.get("fails", 0) + 1
            save(q)
            it = pending(q)
            where = f"{GROUPS[it['g']]['name']} โพสต์ {it['p']}" if it else "-"
            print(("STOP" if q["fails"] >= 2 else "RETRY") + f" fails={q['fails']} | {where} | {reason}")
        elif a == "status":
            if not q or not q.get("items"):
                print("ยังไม่มีคิว (next จะเริ่มรอบใหม่)")
                continue
            d, tot = count(q)
            it = pending(q)
            if it:
                nxt = f"{GROUPS[it['g']]['name']} โพสต์ {it['p']}"
            else:
                due, _ = due_groups()
                nxt = f"รอบใหม่ได้ {len(due)} กลุ่ม" if due else "ไม่มี (ทุกกลุ่มเพิ่งลง → next ได้ TOO_SOON)"
            print(f"รอบเริ่ม {q.get('started')} | เสร็จ {d}/{tot} | ถัดไป: {nxt} | tab={q.get('tab')}")
        else:
            sys.exit(f"ไม่รู้จักคำสั่ง {a}")


if __name__ == "__main__":
    main()
