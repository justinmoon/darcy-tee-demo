"""Real two-agent recovery locally. Explicitly not cloud attestation evidence."""

import json
import secrets
import subprocess

from auth_checks import check
from check_agent import challenge, inject_failure, wait_inference
from common import ROOT, credentials
from local_container import LocalContainer
from recovery import repair_with_helper


def main():
    network = "darcy-tee-test-" + secrets.token_hex(6)
    subprocess.run(
        ["docker", "network", "create", network], check=True, capture_output=True
    )
    evidence = ROOT / ".cache/local-recovery-e2e"
    evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        with LocalContainer(network=network, alias="broken-agent") as remote:
            auth = check(remote.base, remote.key)
            wait_inference(remote)
            remote.request(
                "initialize",
                inference_key=credentials()["TINFOIL_API_KEY"],
                model="gpt-oss-120b",
            )
            first = challenge(remote, "local pre-repair agent")
            (evidence / "before.json").write_text(json.dumps(first, indent=2))
            fault = inject_failure(remote)
            (evidence / "fault.txt").write_text(fault)
            print(
                "Real local agent passed task; injected startup fault confirmed",
                flush=True,
            )
            # Direct signed HTTP is allowed only on this owned local test network.
            # It is not a substitute or fallback for the production TEE client.
            helper = """import json,sys
from pathlib import Path
from client import signed_request
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
key=Ed25519PrivateKey.from_private_bytes(Path('/workspace/remote-owner.key').read_bytes())
print(json.dumps(signed_request('http://broken-agent:8080',key,'exec',command='sleep 3; '+sys.argv[1])))
"""
            recovery = repair_with_helper(helper, network=network)
            assert "wait" in recovery["tools"], (
                "slow commands must use real Tau wait completion"
            )
            (evidence / "recovery.json").write_text(json.dumps(recovery, indent=2))
            last = challenge(remote, "local repaired agent")
            (evidence / "after.json").write_text(json.dumps(last, indent=2))
            summary = dict(
                location="two local Linux containers; not a cloud TEE harness",
                inference="real Tinfoil gpt-oss-120b through verified proxy",
                mocked_components=[],
                authorization=auth,
                first_tools=first["tools"],
                recovery_tools=recovery["tools"],
                repaired_tools=last["tools"],
                failure="actual Tau invalid YAML startup error",
                cloud_attestation_tested=False,
            )
            (evidence / "summary.json").write_text(json.dumps(summary, indent=2))
            print(json.dumps(summary, indent=2), flush=True)
    finally:
        subprocess.run(["docker", "network", "rm", network], capture_output=True)


if __name__ == "__main__":
    main()
