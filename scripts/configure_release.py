"""Write measured config from a published OCI digest and this owner's public key."""

import argparse
import re

import yaml
from common import ROOT
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

p = argparse.ArgumentParser()
p.add_argument("digest")
args = p.parse_args()
if not re.fullmatch(r"sha256:[0-9a-f]{64}", args.digest) or set(
    args.digest.split(":")[1]
) == {"0"}:
    p.error("a real published OCI SHA256 digest is required")
owner = (
    Ed25519PrivateKey.from_private_bytes((ROOT / ".cache/owner.key").read_bytes())
    .public_key()
    .public_bytes_raw()
    .hex()
)
config = {
    "cvm-version": "0.14.15@sha256:51166e30f9292cbddf28d493cac6f12d42a9b8aa75bb9a1b5cf759f02f8b7bf4",
    "cpus": 2,
    "memory": 8192,
    "networks": {"internet": {"egress": "open"}},
    "containers": [
        {
            "name": "darcy",
            "image": "ghcr.io/justinmoon/darcy-tee-demo@" + args.digest,
            "user": "1000:1000",
            "read_only": True,
            "networks": ["internet"],
            "pids_limit": 256,
            "restart": "on-failure",
            "env": [{"DARCY_OWNER_PUBLIC_KEY": owner}],
            "tmpfs": {
                "/tmp": "size=128m,mode=1777",
                "/workspace": "size=1g,uid=1000,gid=1000",
            },
            "healthcheck": {
                "test": ["CMD", "/bin/curl", "-sf", "http://127.0.0.1:8080/health"],
                "interval": "5s",
                "timeout": "3s",
                "retries": 12,
                "start_period": "10s",
            },
        }
    ],
    "shim": {"upstream-port": 8080, "paths": ["/health", "/control"]},
}
(ROOT / "tinfoil-config.yml").write_text(yaml.safe_dump(config, sort_keys=False))
print("Wrote measured image digest and owner public key; no secrets in config")
