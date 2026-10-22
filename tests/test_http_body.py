"""Body framing over real HTTP sockets, including a signed chunked request."""

import base64
import http.client
import json
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from http_body import read_body
from security import Owner


class BodyTests(unittest.TestCase):
    def test_signed_chunked_and_length_requests(self):
        key = Ed25519PrivateKey.generate()
        owner = Owner(key.public_key().public_bytes_raw().hex())

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                try:
                    owner.verify(read_body(self, 4096))
                    self.send_response(200)
                except Exception:
                    self.send_response(400)
                self.send_header("Content-Length", "0")
                self.end_headers()

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for chunked in [False, True]:
                raw = json.dumps(
                    dict(
                        action="status",
                        time=int(time.time()),
                        nonce=("a" if chunked else "b") * 32,
                    )
                ).encode()
                body = json.dumps(
                    dict(
                        payload=base64.b64encode(raw).decode(),
                        signature=base64.b64encode(key.sign(raw)).decode(),
                    )
                ).encode()
                conn = http.client.HTTPConnection(*server.server_address, timeout=3)
                payload = iter([body[:17], body[17:]]) if chunked else body
                conn.request("POST", "/control", body=payload, encode_chunked=chunked)
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                response.read()
                conn.close()
            for headers, body in [
                ({"Content-Length": "5000"}, b"x"),
                ({"Content-Length": "1", "Transfer-Encoding": "chunked"}, b"0\r\n\r\n"),
                ({"Transfer-Encoding": "chunked"}, b"2000\r\n"),
            ]:
                conn = http.client.HTTPConnection(*server.server_address, timeout=3)
                conn.request("POST", "/control", body=body, headers=headers)
                response = conn.getresponse()
                self.assertEqual(response.status, 400)
                response.read()
                conn.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
