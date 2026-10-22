"""Real model/tool challenge shared by local and confidential E2E tests."""

import json
import secrets
import shlex
import time

from common import ROOT


def wait_inference(client):
    deadline = time.monotonic() + 100
    while time.monotonic() < deadline:
        if client.request("status").get("proxy_ready"):
            return
        time.sleep(1)
    raise RuntimeError("attested inference proxy is not ready; inspect proxy.stderr")


def exec_ok(client, command):
    result = client.request("exec", command=command)
    if result["returncode"] != 0:
        raise RuntimeError("owner exec failed: " + result["stderr"])
    return result["stdout"]


def challenge(client, label):
    nonce = secrets.token_hex(24)
    filename = "challenge-" + secrets.token_hex(8)
    exec_ok(client, "printf %s " + shlex.quote(nonce) + " > " + filename + ".txt")
    result = client.request(
        "run",
        prompt=f"Read {filename}.txt. Then use shell to run a program that reads that input file at execution time and reverses its contents into {filename}.out. Do not reverse the text mentally or transcribe a guessed result. Finally read the output to check it. Keep your reply brief.",
    )
    actual = exec_ok(client, "cat " + filename + ".out").strip()
    trace = ROOT / ".cache/last-challenge.json"
    trace.write_text(
        json.dumps(
            {
                "label": label,
                "expected": nonce[::-1],
                "actual": actual,
                "result": result,
            },
            indent=2,
        )
    )
    trace.chmod(0o600)
    assert actual == nonce[::-1], (
        f"{label}: generated file did not match hidden challenge; inspect {trace}"
    )
    assert result["tools"], f"{label}: no actual tool calls recorded"
    return result


def inject_failure(client):
    exec_ok(client, "printf 'extensions: [\n' > config/tau/harness.yaml")
    try:
        client.request(
            "run", prompt="Read the current directory and report its file count."
        )
    except RuntimeError as error:
        assert client.request("status")["control"] == "ready"
        return str(error)
    raise AssertionError("broken harness unexpectedly succeeded")
