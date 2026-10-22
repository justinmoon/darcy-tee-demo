import os

from common import ROOT
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

path = ROOT / ".cache/owner.key"
path.parent.mkdir(exist_ok=True, mode=0o700)
if not path.exists():
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(Ed25519PrivateKey.generate().private_bytes_raw())
key = Ed25519PrivateKey.from_private_bytes(path.read_bytes())
print(key.public_key().public_bytes_raw().hex())
