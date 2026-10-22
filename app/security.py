"""Measured owner public key; private signing key stays on the client."""

import base64
import json
import threading
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class Unauthorized(Exception):
    pass


class Owner:
    def __init__(self, public_hex):
        self.key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_hex))
        self.nonces = {}
        self.lock = threading.Lock()

    def verify(self, body):
        if len(body) > 128 * 1024:
            raise Unauthorized("request too large")
        try:
            outer = json.loads(body)
            raw = base64.b64decode(outer["payload"], validate=True)
            sig = base64.b64decode(outer["signature"], validate=True)
            self.key.verify(sig, raw)
            p = json.loads(raw)
            if (
                abs(time.time() - p["time"]) > 120
                or not isinstance(p["nonce"], str)
                or len(p["nonce"]) != 32
            ):
                raise ValueError()
            with self.lock:
                now = time.time()
                self.nonces = {n: t for n, t in self.nonces.items() if now - t < 240}
                if p["nonce"] in self.nonces or len(self.nonces) > 4096:
                    raise ValueError()
                self.nonces[p["nonce"]] = now
            return p
        except Exception as e:
            raise Unauthorized("invalid owner signature or replay") from e
