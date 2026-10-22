import base64
import json
import sys
import time
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from security import Owner, Unauthorized


class Authorization(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        self.owner = Owner(self.key.public_key().public_bytes_raw().hex())

    def frame(self, **overrides):
        value = {
            "nonce": "a" * 32,
            "time": time.time(),
            "action": "exec",
            "command": "id",
            **overrides,
        }
        raw = json.dumps(value).encode()
        return json.dumps(
            {
                "payload": base64.b64encode(raw).decode(),
                "signature": base64.b64encode(self.key.sign(raw)).decode(),
            }
        ).encode()

    def test_signature_and_replay(self):
        frame = self.frame()
        self.assertEqual(self.owner.verify(frame)["action"], "exec")
        with self.assertRaises(Unauthorized):
            self.owner.verify(frame)

    def test_tamper(self):
        frame = json.loads(self.frame())
        frame["payload"] = base64.b64encode(b'{"command":"steal"}').decode()
        with self.assertRaises(Unauthorized):
            self.owner.verify(json.dumps(frame).encode())

    def test_expired(self):
        with self.assertRaises(Unauthorized):
            self.owner.verify(self.frame(time=0))

    def test_another_owner(self):
        other = Owner(
            Ed25519PrivateKey.generate().public_key().public_bytes_raw().hex()
        )
        with self.assertRaises(Unauthorized):
            other.verify(self.frame())


if __name__ == "__main__":
    unittest.main()
