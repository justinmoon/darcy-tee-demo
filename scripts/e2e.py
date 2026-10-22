"""Cloud E2E: attested harness/tools, injected failure, real local agent repair."""

import argparse
import json
import time

from auth_checks import check
from check_agent import challenge, inject_failure, wait_inference
from client import Client
from common import ROOT, credentials
from recovery import repair

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--endpoint", required=True)
    p.add_argument("--repo", required=True)
    args = p.parse_args()
    started = time.monotonic()
    evidence = ROOT / ".cache/cloud-e2e"
    evidence.mkdir(parents=True, exist_ok=True)
    with Client(args.endpoint, args.repo) as remote:
        print("Verified expected Container release", flush=True)
        try:
            with Client(args.endpoint, "tinfoilsh/confidential-agent-sandbox@v0.1.25"):
                raise AssertionError("wrong expected workload passed verification")
        except RuntimeError as error:
            if "attestation proxy failed" not in str(error):
                raise
            (evidence / "wrong-workload.txt").write_text(str(error))
        auth = check(f"http://127.0.0.1:{remote.port}", remote.key)
        print("Wrong workload rejected; owner authorization checks passed", flush=True)
        wait_inference(remote)
        status = remote.request("status")
        assert (
            status["platform"] == "Linux"
            and status["uid"] == 1000
            and status["proxy_alive"]
        )
        if not status["initialized"]:
            remote.request(
                "initialize",
                inference_key=credentials()["TINFOIL_API_KEY"],
                model="gpt-oss-120b",
            )
        first = challenge(remote, "confidential agent")
        print("Cloud agent passed hidden-file challenge with real tools", flush=True)
        (evidence / "before.json").write_text(json.dumps(first, indent=2))
        failure = inject_failure(remote)
        print(
            "Actual Tau startup fault confirmed; owner control remains reachable",
            flush=True,
        )
        (evidence / "failure.txt").write_text(failure)
        recovery = repair(args.endpoint, args.repo)
        print("Local Tau recovery agent finished; checking remote result", flush=True)
        (evidence / "recovery.json").write_text(json.dumps(recovery, indent=2))
        last = challenge(remote, "repaired confidential agent")
        (evidence / "after.json").write_text(json.dumps(last, indent=2))
    summary = {
        "cloud_harness_and_tools": True,
        "mocked_components": [],
        "release": args.repo,
        "wrong_workload": "rejected before credentials",
        "authorization": auth,
        "first_tools": first["tools"],
        "fault": "invalid harness YAML",
        "local_recovery_tools": recovery["tools"],
        "repaired_tools": last["tools"],
        "seconds": round(time.monotonic() - started, 2),
    }
    (evidence / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
