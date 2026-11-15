"""
เว็บเซิร์ฟเวอร์จิ๋ว ตอบคำเดียวว่า "ok"

ทำไมต้องมี
----------
Render แบบฟรีนับบริการเป็น "เว็บ" ซึ่งต้องเปิดพอร์ตรอให้ได้ภายในไม่กี่นาที
ไม่งั้นถือว่าสตาร์ทไม่สำเร็จแล้วปิดทิ้ง  แต่บอทเราเป็นลูปดึงข้อความจาก
Telegram ไม่ได้เปิดพอร์ตอะไรเลย  จึงต้องแปะเว็บจิ๋วนี้ไว้ให้ Render เห็น

อีกเรื่องคือ Render ฟรีจะพักเครื่องถ้าไม่มีใครเข้าเว็บ 15 นาที
พอพักแล้วบอทหยุดดึงข้อความ พิมพ์ไปก็ไม่มีใครตอบ
เลยต้องมีตัวปิงจากข้างนอกมาเรียกหน้านี้ทุก 10 นาที (ดู DEPLOY.md)

ทำไมตอบแค่ "ok" ไม่โชว์ยอดขาย
-----------------------------
ลิงก์ของ Render เป็นลิงก์สาธารณะ ใครเดาเจอก็เปิดดูได้
ถ้าเอายอดขายหรือกำไรมาโชว์ตรงนี้ เท่ากับประกาศรายได้ให้คนอื่นอ่าน
อยากดูยอดให้พิมพ์ในบอท ซึ่งตอบเฉพาะ CHAT_ID ของเจ้าของเท่านั้น
"""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"ok")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        # ปิดล็อกทิ้ง ไม่งั้นตัวปิงทุก 10 นาทีจะถมล็อกจนหาของจริงไม่เจอ
        pass


def start(port: int):
    """
    เปิดเว็บจิ๋วในเธรดแยก แล้วคืนค่าทันที บอทจะได้ไปทำงานต่อได้

    daemon=True เพื่อให้เธรดนี้ตายไปพร้อมบอท
    ไม่งั้นตอนสั่งปิดบอท โปรเซสจะค้างรออยู่เฉยๆ
    """
    server = HTTPServer(("0.0.0.0", port), _Handler)
    thread = threading.Thread(target=server.serve_forever,
                              name="health", daemon=True)
    thread.start()
    return server
