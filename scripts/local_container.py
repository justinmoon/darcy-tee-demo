"""Owned local Linux test VM/container. This is not evidence of TEE execution."""

import json
import secrets
import subprocess
import time
import urllib.request

from client import signed_request
from common import ROOT
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

IMAGE = "ghcr.io/justinmoon/darcy-tee-demo:dev"


class LocalContainer:
    def __init__(self, network=None, alias=None):
        self.name = "darcy-tee-test-" + secrets.token_hex(6)
        self.network = network
        self.alias = alias
        self.key = Ed25519PrivateKey.from_private_bytes(
            (ROOT / ".cache/owner.key").read_bytes()
        )

    def __enter__(self):
        args = [
            "docker",
            "run",
            "-d",
            "--name",
            self.name,
            "--platform",
            "linux/amd64",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--tmpfs",
            "/tmp:size=128m,mode=1777",
            "--tmpfs",
            "/workspace:size=1g,uid=1000,gid=1000",
            "--pids-limit",
            "256",
            "--memory",
            "2g",
            "--cpus",
            "2",
            "-p",
            "127.0.0.1::8080",
            "-e",
            "DARCY_OWNER_PUBLIC_KEY=" + self.key.public_key().public_bytes_raw().hex(),
        ]
        if self.network:
            args += ["--network", self.network, "--network-alias", self.alias]
        try:
            subprocess.run(args + [IMAGE], check=True, capture_output=True)
            port = (
                subprocess.check_output(
                    ["docker", "port", self.name, "8080/tcp"], text=True
                )
                .strip()
                .rsplit(":", 1)[1]
            )
            self.base = "http://127.0.0.1:" + port
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                try:
                    with urllib.request.urlopen(self.base + "/health", timeout=2) as r:
                        if json.load(r).get("service") == "darcy-tee-demo":
                            return self
                except (OSError, ValueError):
                    time.sleep(0.3)
            raise RuntimeError("local container did not become healthy")
        except BaseException:
            self.__exit__()
            raise

    def request(self, action, **fields):
        return signed_request(self.base, self.key, action, **fields)

    def __exit__(self, *args):
        if args and args[0] is not None:
            self.capture_diagnostics()
        logs = subprocess.run(
            ["docker", "logs", self.name], capture_output=True, text=True
        )
        (ROOT / ".cache" / f"{self.name}.log").write_text(logs.stdout + logs.stderr)
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True)

    def capture_diagnostics(self):
        diagnostics = ROOT / ".cache" / (self.name + "-diagnostics")
        diagnostics.mkdir(mode=0o700, exist_ok=True)
        for source in ["sessions", "last-harness.stderr", "config/tau/harness.yaml"]:
            subprocess.run(
                ["docker", "cp", self.name + ":/workspace/" + source, str(diagnostics)],
                capture_output=True,
            )
        return str(diagnostics)
