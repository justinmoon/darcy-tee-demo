"""Project-owned Sandbox lifecycle and attested SSH. No changes to ~/.ssh."""

import argparse
import base64
import json
import os
import re
import subprocess
import urllib.error
import uuid

from common import ROOT, admin, credentials
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

REPO = "tinfoilsh/confidential-agent-sandbox"
TAG = "v0.1.25"
DIRECTORY = ROOT / ".cache/sandbox"
STATE = DIRECTORY / "deployment.json"
IDENTITY = DIRECTORY / "owner_ed25519"
CONFIG = DIRECTORY / "ssh.conf"
PINS = DIRECTORY / "known_hosts"
ALIAS = "darcy-tee-sandbox"


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(data, indent=2))
    path.chmod(0o600)


def key():
    DIRECTORY.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not IDENTITY.exists():
        private = Ed25519PrivateKey.generate()
        IDENTITY.write_bytes(
            private.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.OpenSSH,
                serialization.NoEncryption(),
            )
        )
        IDENTITY.chmod(0o600)
    return serialization.load_ssh_private_key(IDENTITY.read_bytes(), password=None)


def lifecycle(action):
    if action == "create":
        if STATE.exists():
            raise RuntimeError("Sandbox state exists; inspect it before another create")
        owner = (
            "ed25519:"
            + base64.b64encode(key().public_key().public_bytes_raw()).decode()
        )
        row = admin(
            "/api/containers",
            {
                "name": ALIAS,
                "repo": REPO,
                "tag": TAG,
                "mark_latest_release": False,
                "workspace_size_gb": 4,
                "variables": {
                    "SANDBOX_OWNER_PUBLIC_KEY": owner,
                    "SANDBOX_INSTANCE_ID": str(uuid.uuid4()),
                    "NO_MONITOR": "1",
                },
            },
        )
    else:
        previous = json.loads(STATE.read_text())
        route = "/api/containers/" + previous["id"]
        row = (
            admin(route)
            if action == "status"
            else admin(route + ("/stop" if action == "stop" else "/deploy"), {})
        )
    save(STATE, row)
    return row


def attest():
    row = json.loads(STATE.read_text())
    env = {k: v for k, v in os.environ.items() if not k.startswith("TINFOIL_")}
    env.update(
        TINFOIL_ADMIN_KEY=credentials()["TINFOIL_ADMIN_KEY"],
        TINFOIL_CONFIG=str(DIRECTORY / "tinfoil/config.json"),
    )
    result = subprocess.run(
        [
            str(ROOT / ".cache/bin/tinfoil"),
            "--repo",
            REPO + "@" + TAG,
            "attest-ssh",
            row["id"],
            "--identity",
            str(IDENTITY),
            "--name",
            ALIAS,
            "--user",
            "sandbox",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=240,
    )
    (DIRECTORY / "attest.stderr").write_text(result.stderr)
    if result.returncode:
        raise RuntimeError(
            "Sandbox attestation/unlock failed: " + result.stderr[-3000:]
        )
    marker = "# ~/.ssh/tinfoil/" + ALIAS + ".known_hosts\n"
    if result.stdout.count(marker) != 1:
        raise RuntimeError("unexpected attested SSH profile; refusing unpinned SSH")
    profile, pins = result.stdout.split(marker)
    if "StrictHostKeyChecking yes" not in profile or not pins.strip():
        raise RuntimeError("missing strict SSH pin")
    profile = re.sub(
        r"UserKnownHostsFile .*", "UserKnownHostsFile " + str(PINS), profile
    )
    CONFIG.write_text(
        profile
        + "\n  IdentityAgent none\n  ForwardAgent no\n  BatchMode yes\n  ConnectTimeout 20\n"
    )
    PINS.write_text(pins)
    CONFIG.chmod(0o600)
    PINS.chmod(0o600)
    return "Attestation verified; disk unlocked; SSH profile saved inside this project"


def ssh(command, timeout=120):
    return subprocess.run(
        ["ssh", "-F", str(CONFIG), ALIAS, command],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=["create", "status", "stop", "start", "attest", "exec"]
    )
    parser.add_argument("command", nargs="?")
    args = parser.parse_args()
    try:
        if args.action == "attest":
            print(attest())
        elif args.action == "exec":
            result = ssh(args.command)
            print(
                json.dumps(
                    dict(
                        returncode=result.returncode,
                        stdout=result.stdout,
                        stderr=result.stderr,
                    )
                )
            )
            raise SystemExit(result.returncode)
        else:
            row = lifecycle(args.action)
            print(
                json.dumps(
                    {
                        k: row.get(k)
                        for k in [
                            "id",
                            "status",
                            "domain",
                            "ssh_port",
                            "error_message",
                            "last_deploy_attempt_error",
                        ]
                    },
                    indent=2,
                )
            )
    except urllib.error.HTTPError as error:
        print(
            json.dumps(
                {"http_status": error.code, "error": error.read().decode()[:4096]}
            )
        )
        raise SystemExit(1)
