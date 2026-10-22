"""Signed owner client over Tinfoil's verified proxy. No direct TLS fallback."""

import argparse
import base64
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from common import ROOT, credentials
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class Client:
    def __init__(self, endpoint, repo, owner=None, cli=None):
        self.endpoint = endpoint.removeprefix("https://").rstrip("/")
        self.repo = repo
        self.key = Ed25519PrivateKey.from_private_bytes(
            Path(owner or ROOT / ".cache/owner.key").read_bytes()
        )
        self.cli = str(cli or ROOT / ".cache/bin/tinfoil")
        self.process = None
        self.directory = None

    def __enter__(self):
        import socket

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.directory = tempfile.TemporaryDirectory(prefix="darcy-attested-")
        self.log = open(Path(self.directory.name) / "proxy.log", "w+b")
        env = {k: v for k, v in os.environ.items() if not k.startswith("TINFOIL_")}
        self.process = subprocess.Popen(
            [
                self.cli,
                "--enclave",
                self.endpoint,
                "--repo",
                self.repo,
                "proxy",
                "--bind",
                "127.0.0.1",
                "--port",
                str(self.port),
            ],
            stdout=self.log,
            stderr=self.log,
            env=env,
        )
        deadline = time.monotonic() + 90
        try:
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    self.log.seek(0)
                    raise RuntimeError(
                        "attestation proxy failed: "
                        + self.log.read().decode(errors="replace")[-3000:]
                    )
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{self.port}/health", timeout=2
                    ) as response:
                        health = json.load(response)
                        if health.get("service") == "darcy-tee-demo":
                            return self
                except (OSError, ValueError):
                    time.sleep(0.3)
            raise TimeoutError("verified container connection timed out")
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def request(self, action, **fields):
        if self.process.poll() is not None:
            raise RuntimeError("verified proxy stopped")
        return signed_request(
            f"http://127.0.0.1:{self.port}", self.key, action, **fields
        )

    def __exit__(self, *args):
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if self.directory:
            self.log.close()
            self.directory.cleanup()


def signed_request(base, key, action, **fields):
    # Also used by the explicitly local Docker test. Cloud callers always use Client.
    payload = json.dumps(
        dict(
            action=action, time=int(time.time()), nonce=secrets.token_hex(16), **fields
        ),
        separators=(",", ":"),
    ).encode()
    body = json.dumps(
        {
            "payload": base64.b64encode(payload).decode(),
            "signature": base64.b64encode(key.sign(payload)).decode(),
        }
    ).encode()
    req = urllib.request.Request(
        base + "/control", data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=210) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        value = json.load(e)
        raise RuntimeError(value.get("error", f"HTTP {e.code}")) from None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default=os.environ.get("DARCY_ENDPOINT"))
    parser.add_argument("--repo", default=os.environ.get("DARCY_REPO"))
    parser.add_argument("--owner", default=os.environ.get("DARCY_OWNER_KEY"))
    parser.add_argument("--cli", default=os.environ.get("DARCY_TINFOIL_CLI"))
    parser.add_argument("action", choices=["status", "initialize", "run", "exec"])
    parser.add_argument("argument", nargs="?")
    args = parser.parse_args()
    if not args.endpoint or not args.repo:
        parser.error("--endpoint and --repo are required")
    fields = {}
    if args.action == "initialize":
        fields = {
            "inference_key": credentials()["TINFOIL_API_KEY"],
            "model": args.argument or "gpt-oss-120b",
        }
    elif args.action == "run":
        fields = {"prompt": args.argument or sys.stdin.read()}
    elif args.action == "exec":
        fields = {"command": args.argument or sys.stdin.read()}
    with Client(args.endpoint, args.repo, args.owner, args.cli) as client:
        print(json.dumps(client.request(args.action, **fields), indent=2))


if __name__ == "__main__":
    main()
