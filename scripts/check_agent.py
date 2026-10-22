"""Real model/tool challenge shared by local and confidential E2E tests."""

import secrets
import shlex
import time


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
        prompt=f"Read {filename}.txt. Use a tool to write its exact contents, reversed character by character, to {filename}.out. Then read the output to check it. Do not guess the input. Keep your reply brief.",
    )
    actual = exec_ok(client, "cat " + filename + ".out").strip()
    assert actual == nonce[::-1], (
        f"{label}: generated file did not match hidden challenge"
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
