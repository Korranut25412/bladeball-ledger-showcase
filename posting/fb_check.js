// fb_check.js — เช็กช่องเขียนโพสต์ของกล่อง "สร้างโพสต์" บน Facebook ก่อนกดโพสต์
// ใช้กับ javascript_tool: ก๊อปทั้งไฟล์ แล้วแก้ 'xxxxxxxx' บรรทัดสุดท้ายเป็นแฮชที่ clip.py พิมพ์ออกมา
// ใส่ '' แทน = เช็กว่าช่องว่างก่อนวาง (กันร่างเก่าค้าง เช่นลิงก์ IG เมื่อ 17 พ.ย. 2569)
// ผลลัพธ์:  OK = ตรงไฟล์เป๊ะ กดโพสต์ได้ · EMPTY = ช่องว่าง วางได้
//          อย่างอื่น = ห้ามโพสต์ (โหลดหน้าใหม่ด้วย navigate force แล้วเริ่มใหม่)
// ห่อเป็นฟังก์ชันเพราะ javascript_tool รันในหน้าเดิมซ้ำ ถ้าประกาศ const ไว้นอกฟังก์ชันรอบสองจะ error
// แฮชต้องคิดแบบเดียวกับ text_hash() ใน prep.py ทุกตัวอักษร ไม่งั้นจะไม่ตรงกันเลย
((WANT) => {
  const boxes = [...document.querySelectorAll('[role=dialog] [contenteditable=true][role=textbox]')];
  if (!boxes.length) return 'NO_DIALOG ยังไม่ได้เปิดกล่องสร้างโพสต์';
  const box = boxes[boxes.length - 1];
  box.focus();  // ให้ ctrl+v ถัดไปลงช่องนี้แน่ๆ (เคยวางพลาดเพราะโฟกัสไม่อยู่ในช่อง)
  const s =box.innerText.replace(/[​-‍﻿]/g, '').replace(/\s+/g, ' ').trim();
  const imgs = box.closest('[role=dialog]').querySelectorAll('img[src^="blob:"]').length;
  if (!s) return WANT ? 'EMPTY_BUT_EXPECTED_TEXT' : 'EMPTY';
  if (/https?:\/\//.test(s)) return 'HAS_LINK ' + s.slice(0, 80);
  if (!WANT) return 'NOT_EMPTY ' + s.slice(0, 80);
  let h = 0x811c9dc5;
  for (const c of s) h = Math.imul((h ^ c.codePointAt(0)) >>> 0, 0x01000193) >>> 0;
  const got = h.toString(16).padStart(8, '0');
  return (got === WANT ? 'OK' : 'MISMATCH got=' + got + ' ' + s.slice(0, 80)) + ' imgs=' + imgs;
})('xxxxxxxx')
