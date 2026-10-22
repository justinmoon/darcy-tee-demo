"""Fetch the pinned macOS ARM CLI; verify its archive before installing it."""

import hashlib
import io
import platform
import tarfile
import urllib.request

from common import ROOT

VERSION = "0.19.9"
EXPECTED = "94ac9e3a9a14ed64dccd40e1f3c35fe40b3768d09fb8b45967277b1498cae943"
if platform.system() != "Darwin" or platform.machine() != "arm64":
    raise RuntimeError("this demo host bootstrap targets Apple Silicon macOS")
archive = ROOT / ".cache/tinfoil.tar.gz"
archive.parent.mkdir(exist_ok=True, mode=0o700)
if not archive.exists():
    url = f"https://github.com/tinfoilsh/tinfoil-cli/releases/download/v{VERSION}/tinfoil-cli_{VERSION}_darwin_arm64.tar.gz"
    with urllib.request.urlopen(url, timeout=60) as response:
        archive.write_bytes(response.read())
data = archive.read_bytes()
if hashlib.sha256(data).hexdigest() != EXPECTED:
    raise RuntimeError("CLI archive SHA256 mismatch; refusing to install")
with tarfile.open(fileobj=io.BytesIO(data)) as bundle:
    binary = bundle.extractfile("tinfoil").read()
destination = ROOT / ".cache/bin/tinfoil"
destination.parent.mkdir(exist_ok=True)
destination.write_bytes(binary)
destination.chmod(0o700)
print(f"Verified and installed Tinfoil CLI {VERSION}")
