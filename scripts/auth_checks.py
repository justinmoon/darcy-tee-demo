"""Real HTTP authorization checks; no stub server or fake verification."""

import base64
import json
import secrets
import time
import urllib.error
import urllib.request

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def check(base, key):
    def envelope(signer):
        raw = json.dumps(
            {
                "action": "status",
                "time": int(time.time()),
                "nonce": secrets.token_hex(16),
            }
        ).encode()
        return json.dumps(
            {
                "payload": base64.b64encode(raw).decode(),
                "signature": base64.b64encode(signer.sign(raw)).decode(),
            }
        ).encode()

    def post(body):
        req = urllib.request.Request(
            base + "/control", data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                return response.status
        except urllib.error.HTTPError as error:
            error.read()
            return error.code

    assert post(b"{}") == 401, "anonymous access accepted"
    assert post(envelope(Ed25519PrivateKey.generate())) == 401, "wrong owner accepted"
    signed = envelope(key)
    assert post(signed) == 200, "valid owner rejected"
    assert post(signed) == 401, "replayed owner request accepted"
    return {
        "anonymous": "denied",
        "wrong_owner": "denied",
        "signed_owner": "accepted",
        "replay": "denied",
    }
