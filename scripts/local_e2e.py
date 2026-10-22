"""Preflight only: real Tau, Linux tools, attested inference; no cloud harness."""

import json

from auth_checks import check
from check_agent import challenge, inject_failure, wait_inference
from common import ROOT, credentials
from local_container import LocalContainer

if __name__ == "__main__":
    with LocalContainer() as c:
        print(json.dumps(c.request("status")), flush=True)
        print(json.dumps(check(c.base, c.key)), flush=True)
        wait_inference(c)
        c.request(
            "initialize",
            inference_key=credentials()["TINFOIL_API_KEY"],
            model="gpt-oss-120b",
        )
        result = challenge(c, "local preflight")
        (ROOT / ".cache/local-agent-trace.json").write_text(
            json.dumps(result, indent=2)
        )
        failure = inject_failure(c)
        (ROOT / ".cache/local-fault.txt").write_text(failure)
        print(
            json.dumps(
                {
                    "local_tools": result["tools"],
                    "challenge": "passed",
                    "fault_detected": True,
                }
            ),
            flush=True,
        )
