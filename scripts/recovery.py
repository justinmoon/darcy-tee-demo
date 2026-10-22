"""A second real Tau harness on this Mac's Linux VM repairs the remote harness."""

import base64
import shlex

from check_agent import exec_ok, wait_inference
from common import ROOT, credentials
from local_container import LocalContainer


def put(client, path, data, mode="600"):
    encoded = base64.b64encode(data).decode()
    exec_ok(
        client,
        f"printf %s {shlex.quote(encoded)} | base64 -d > {shlex.quote(path)}; chmod {mode} {shlex.quote(path)}",
    )


def repair(endpoint, repo):
    with LocalContainer() as host:
        wait_inference(host)
        host.request(
            "initialize",
            inference_key=credentials()["TINFOIL_API_KEY"],
            model="gpt-oss-120b",
        )
        for name in ["client.py", "common.py"]:
            put(host, "/workspace/" + name, (ROOT / "scripts" / name).read_bytes())
        put(
            host,
            "/workspace/remote-owner.key",
            (ROOT / ".cache/owner.key").read_bytes(),
        )
        helper = """import json,sys
from client import Client
with Client(ENDPOINT,REPO,owner='/workspace/remote-owner.key',cli='/bin/tinfoil') as c:
    print(json.dumps(c.request('exec',command=sys.argv[1])))
""".replace("ENDPOINT", repr(endpoint)).replace("REPO", repr(repo))
        put(host, "/workspace/remote.py", helper.encode())
        result = host.request(
            "run",
            prompt="""The remote Tau agent fails to start. Diagnose and repair it using the shell tool.
Run remote commands with: python3 /workspace/remote.py 'COMMAND'
That helper verifies the remote enclave and signs requests as its owner. Do not read or print its owner key.
Inspect the remote workspace, configuration and last-harness.stderr. Remote shipped defaults and adapter source live in /app.
Fix the cause; preserve the inference route and model. Use few commands, with bounded output. Do not alter /app or credentials.
Check the repaired file, then report the cause and change in two sentences. A separate test will run the remote agent afterward.""",
        )
        if not result["tools"]:
            raise AssertionError("recovery agent did not use real tools")
        return result
