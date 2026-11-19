---
name: fb-autopost
description: ลงโพสต์ขายของร้าน Blade Ball ลงกลุ่ม Facebook แบบออโต้เงียบจนจบรอบ ผ่าน Claude in Chrome + คิว posting/autopost.py (เลือกเฉพาะกลุ่มที่ยังไม่ได้ลง เรียงกลุ่มใหญ่ก่อน กันลงซ้ำ) ใช้เมื่อผู้ใช้พิมพ์ "โพสเลย" หรือสั่งลงโพสต์ขายในกลุ่ม FB
---

# fb-autopost — "โพสเลย" ทำตามนี้ทีละข้อ ห้ามคิดเอง (Haiku effort low พอ)

ผู้ใช้พิมพ์ **"โพสเลย"** = ลงคิวให้จบรอบ **เงียบ** ไม่ถาม ไม่รายงานระหว่างทาง ไม่สรุป
- **สคริปต์เป็นคนเลือกกลุ่ม ห้ามเลือกเอง:** `next` อ่านล็อก (`posting/โพสต์บอล.md` หัวข้อ "ล็อกออโต้") แล้วเอาเฉพาะกลุ่มที่ลงไปแล้ว ≥ 3 ชม. หรือยังไม่เคยลง เรียงสมาชิกมาก→น้อย (15 กลุ่มใน `GROUPS`) × โพสต์ 1–6 · กลุ่มไหนถูกข้ามจะบอกในบรรทัด `ROUND`
- ไม่ลงโพสต์ 7 · ไม่ดันโพสต์ · ไม่ใช้ update_plan / wrap_up / ข้อความอธิบาย · ไม่แทรกศัพท์อังกฤษ
- รันทุกคำสั่งในโฟลเดอร์ worktree `bladeball-ledger\.claude\worktrees\telegram-posting-system-6a3de9` (คิว `posting/ready/` อยู่ที่นั่นที่เดียว · โค้ด merge เข้า main แล้ว 19 พ.ย. แต่ห้ามรันจากรากรีโป ไม่งั้นคิว/ล็อกแยกสองที่)

## เริ่ม (ครั้งเดียวต่อแชท)
1. ToolSearch `select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__browser_batch,mcp__claude-in-chrome__file_upload,mcp__claude-in-chrome__get_page_text,mcp__ccd_session_mgmt__clear_session`
2. `tabs_context_mcp` createIfEmpty=true → จด **เลข tabId จริง** จากผล
3. Bash: `python posting/autopost.py tab <เลข tabId จริง> next`
   - `TOO_SOON` = ทุกกลุ่มเพิ่งลง → ข้อ "แจ้งผู้ใช้" ทันที **ห้ามสั่ง `force` เอง**
   - ห้ามเชื่อเลขคิวใน `_สถานะล่าสุด.md` หรือในความจำ — ความจริงคือ `autopost.py status` + ล็อก

## วนทีละโพสต์ (3 รอบเครื่องมือ)
ผลจาก `next` มี `BATCH1=` `UPLOAD_PATHS=` `BATCH2=` (JSON สำเร็จรูป ก๊อปไปใส่ตรงๆ ห้ามแก้ ห้ามอธิบาย)
1. `browser_batch` actions = BATCH1 → JS ตัวแรกต้องได้ `OPEN` · ตัวที่สอง `OK` · find มี `file-input "UPLOADHERE"` → จด ref (ref เปลี่ยนทุกโพสต์ ห้ามใช้ ref เก่า) · ไม่ผ่าน → ข้อ "พัง"
2. `file_upload` ref = ref ที่จด · paths = UPLOAD_PATHS
3. **ส่ง 2 เครื่องมือในข้อความเดียว:** `browser_batch` actions = BATCH2 **และ** Bash `python posting/autopost.py done next`
   - BATCH2 ตัวสุดท้ายได้ `POSTED` / `POSTED_PENDING_ADMIN` → ใช้ NEXT จาก Bash กลับไปข้อ 1 (Bash ได้ `ROUND_COMPLETE` → ข้อ "จบรอบ")
   - `BLOCKED` → Bash `python posting/autopost.py undo` แล้วข้อ "แจ้งผู้ใช้" ทันที
   - อย่างอื่น (`MISMATCH` `UPLOAD_TIMEOUT` `NO_DIALOG` …) → Bash `python posting/autopost.py undo fail <ผล>` แล้วข้อ "พัง"

## พัง
- Bash: `python posting/autopost.py fail <ผลสั้นๆ>` (มาจากข้อ 3 ใช้ `undo fail` ตามข้างบน)
  - `RETRY` → Bash `python posting/autopost.py next` แล้วเริ่มข้อ 1 ใหม่ (BATCH1 navigate ใหม่ ล้างร่างเอง)
  - `STOP` → ข้อ "แจ้งผู้ใช้"
- ⚠️ ไม่แน่ใจว่าโพสต์ขึ้นหรือยัง (`CLICKED` แล้วได้ `STILL_OPEN`/`FB_ERROR` · ถูกผู้ใช้กดหยุดกลางคัน · แชทหลุด) → `navigate` ไป `<url กลุ่ม>/my_posted_content` + `get_page_text` ดูโพสต์ล่าสุดก่อนเสมอ · ขึ้นแล้ว = `done` ไม่ลงซ้ำ · ไม่ขึ้น = `undo` แล้วลงใหม่

## แจ้งผู้ใช้ (เฉพาะบั๊กจริง)
Chrome ไม่เชื่อม · FB หลุดล็อกอิน · `BLOCKED` · `STOP` · `TOO_SOON` → ตอบ 1 บรรทัด: ติดตรงไหน + ผล `autopost.py status` · **ไม่เคลียร์แชท**
- `TOO_SOON` แล้วผู้ใช้ตอบชัดว่าลงซ้ำได้ → ค่อย `python posting/autopost.py force next`

## จบรอบ
1. Bash: `git add posting/โพสต์บอล.md && git commit -m "โพสเลยออโต้: ลงครบรอบ"` (ใส่บรรทัด Co-Authored-By ตามที่ระบบกำหนด) · ห้าม push
2. `clear_session` session_id `"self"` (ถูกปฏิเสธ เช่น Remote Control ก็ปล่อยไป)
3. ข้อความสุดท้ายแค่ `✅ <เสร็จ>/<ทั้งหมด>` ตามบรรทัด ROUND_COMPLETE

## แชทหลุดกลางทาง
คิวอยู่ใน `posting/ready/queue.json` → แชทใหม่พิมพ์ "โพสเลย" ลงต่อจากที่ค้างเอง ไม่ต้อง handoff

## ห้ามพลาดซ้ำ (เคยพลาดจริง · สคริปต์กันไว้แล้ว ห้ามทำทางอ้อม)
| วันที่ | ที่พลาด | กันไว้ด้วย |
|---|---|---|
| 17 พ.ย. | Claude พิมพ์ข้อความไทยเองใน JS แล้วคำเพี้ยน | ห้ามพิมพ์ข้อความโพสต์เอง ใช้คลิปบอร์ดจาก `clip.put()` + JS เป็น `\uXXXX` |
| 17 พ.ย. | คลิปบอร์ดโดนทับ (ลิงก์ IG, คำว่า "resign", ลิงก์ Google) ก่อนวาง | เช็กแฮชข้อความก่อนกดโพสต์ทุกครั้ง (`MISMATCH`/`HAS_LINK` = ห้ามโพสต์) · ผู้ใช้ห้ามก๊อปอะไรระหว่างรัน |
| 17 พ.ย. | สองกลุ่มได้ข้อความเหมือนเป๊ะ | `v` ไม่ซ้ำทุกกลุ่ม (เทสต์คุม) · ห้ามแก้ `v` |
| 17 พ.ย. | อัปรูปจาก `Desktop\Bladeball` ไม่ได้ | ใช้รูปใน `posting/ready/` จาก prep.py เท่านั้น |
| 17 พ.ย. | FB ขึ้น "เกิดข้อผิดพลาด" แต่โพสต์อาจขึ้นแล้ว | เช็ก my_posted_content ก่อนลงซ้ำ |
| 18 พ.ย. | javascript_tool ไม่รอ Promise ได้ `{}` | JS async ขึ้นต้น `await` (อยู่ใน BATCH แล้ว) |
| 18 พ.ย. | นับรูป blob ไม่ครบเพราะ FB ทำ collage | ไม่ใช้จำนวนรูปเป็นเกณฑ์ ดูแถบโหลดแทน |
| 18 พ.ย. | file_upload เกิน 10MB | prep.py ย่อรูป · autopost STOP ถ้าโพสต์มีรูปหลายชุด |
| ทุกครั้ง | Action Blocked แล้วลองซ้ำ = โดนบล็อกนานขึ้น | `BLOCKED` = หยุดทันที |
| 19 พ.ย. | ใส่ `TABID` ตัวอักษรแทนเลขแท็บจริง | ใช้เลขจาก `tabs_context_mcp` เท่านั้น |
| 19 พ.ย. | **ลงซ้ำกลุ่มใหญ่** เพราะเชื่อไฟล์สถานะเก่า (ค้าง 3/24) + `next` เริ่มรอบใหม่เองหลังรอบเพิ่งจบ | `next` อ่านล็อกเลือกเฉพาะกลุ่มที่ถึงคิว · ทุกกลุ่มเพิ่งลง = `TOO_SOON` · ห้าม `force` เอง · เทสต์ `posting/test_autopost.py` |

แก้ autopost.py แล้วต้องรัน `python posting/test_autopost.py` ให้ผ่านทุกครั้ง · เจอพลาดแบบใหม่ → เพิ่มแถวในตารางนี้ + เพิ่มเทสต์
