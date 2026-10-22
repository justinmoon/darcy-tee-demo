"""Project-owned Sandbox lifecycle and attested SSH. No changes to ~/.ssh."""

import argparse
import base64
import copy
import hashlib
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
import uuid

import yaml
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


def lifecycle(action, name=ALIAS, workspace_size=16):
    if action == "create":
        if STATE.exists():
            raise RuntimeError("Sandbox state exists; inspect it before another create")
        owner = (
            "ed25519:"
            + base64.b64encode(key().public_key().public_bytes_raw()).decode()
        )
        variables = {
            "SANDBOX_OWNER_PUBLIC_KEY": owner,
            "SANDBOX_INSTANCE_ID": str(uuid.uuid4()),
            "NO_MONITOR": "1",
        }
        save(
            DIRECTORY / "create-intent.json",
            {"name": name, "workspace_size": workspace_size, "variables": variables},
        )
        row = admin(
            "/api/containers",
            {
                "name": name,
                "repo": REPO,
                "tag": TAG,
                "mark_latest_release": False,
                "workspace_size_gb": workspace_size,
                "variables": variables,
            },
            timeout=180,
        )
    else:
        previous = json.loads(STATE.read_text())
        route = "/api/containers/" + previous["id"]
        row = admin(route)
        already = (action == "stop" and row["status"] in {"stopped", "stopping"}) or (
            action == "start"
            and row["status"] in {"running", "started", "deploying", "starting"}
        )
        if action != "status" and not already:
            row = admin(
                route + ("/stop" if action == "stop" else "/deploy"), {}, timeout=180
            )
    save(STATE, row)
    return row


def attest():
    row = json.loads(STATE.read_text())
    source = reviewed_source(row)
    policy = DIRECTORY / "tinfoil/known-configs.json"
    save(policy, {"mode": "frozen", "record": "pin", "allow": {"pins": [source]}})
    env = {k: v for k, v in os.environ.items() if not k.startswith("TINFOIL_")}
    env.update(
        TINFOIL_ADMIN_KEY=credentials()["TINFOIL_ADMIN_KEY"],
        TINFOIL_CONFIG=str(DIRECTORY / "tinfoil/config.json"),
        TINFOIL_KNOWN_CONFIGS=str(policy),
    )
    result = subprocess.run(
        [
            str(ROOT / ".cache/bin/tinfoil"),
            "--repo",
            source,
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


def reviewed_source(row):
    """Check all code/settings against the pinned template before accepting its personal config."""
    base = DIRECTORY / "base-release/tinfoil-config.yml"
    expected_sha = "1ba86daaef769abf050193e5440c3238a0c24c572cc8b963e0673d9e9ffc508b"
    if not base.exists():
        base.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(
            "https://github.com/"
            + REPO
            + "/releases/download/"
            + TAG
            + "/tinfoil-config.yml",
            timeout=45,
        ) as response:
            base.write_bytes(response.read())
    if hashlib.sha256(base.read_bytes()).hexdigest() != expected_sha:
        raise RuntimeError("Sandbox release template hash changed")
    actual = yaml.safe_load(row["config"])
    env = {k: v for entry in actual["containers"][0]["env"] for k, v in entry.items()}
    owner = (
        "ed25519:" + base64.b64encode(key().public_key().public_bytes_raw()).decode()
    )
    if env.get("SANDBOX_OWNER_PUBLIC_KEY") != owner or env.get("NO_MONITOR") != "1":
        raise RuntimeError("Sandbox owner or network mode changed")
    uuid.UUID(env["SANDBOX_INSTANCE_ID"])
    intent_path = DIRECTORY / "create-intent.json"
    if intent_path.exists():
        intent = json.loads(intent_path.read_text())
        if intent["name"] != row["name"] or intent["variables"] != env:
            raise RuntimeError("Sandbox no longer matches local create intent")
        size = intent["workspace_size"]
    else:
        # Existing test instance predates intent recording: approve only the
        # reviewed 16 GB template and this machine's owner key, then pin it.
        size = 16
    expected = copy.deepcopy(yaml.safe_load(base.read_text()))
    expected["containers"][0]["env"] = [
        {k: env[k]}
        for k in ["SANDBOX_OWNER_PUBLIC_KEY", "SANDBOX_INSTANCE_ID", "NO_MONITOR"]
    ]
    expected["volumes"][0]["size"] = str(size) + "GB"
    expected["shim"]["tls-mode"] = "cert-proxy"
    expected["cvm-network"] = {"inbound-ports": [22]}
    if actual != expected or row["repo"] != REPO or row["current_tag"] != TAG:
        raise RuntimeError(
            "Sandbox differs from reviewed pinned template and allowed personal settings"
        )
    digest = hashlib.sha256(row["config"].encode()).hexdigest()
    if row["config_name"] != "/tinfoil/containers/" + digest:
        raise RuntimeError("Sandbox config bytes do not match its content reference")
    source = "tinfoil/containers@" + digest + "@sha256:" + digest
    pin = DIRECTORY / (row["id"] + "-reviewed.json")
    if pin.exists() and json.loads(pin.read_text())["source"] != source:
        raise RuntimeError("Previously reviewed Sandbox configuration changed")
    save(
        pin,
        {
            "source": source,
            "base_release": REPO + "@" + TAG,
            "template_sha256": expected_sha,
        },
    )
    return source


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
    parser.add_argument("--name", default=ALIAS)
    parser.add_argument(
        "--workspace-size", type=int, choices=[2, 4, 8, 16, 32, 64], default=16
    )
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
            row = lifecycle(
                args.action, name=args.name, workspace_size=args.workspace_size
            )
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
