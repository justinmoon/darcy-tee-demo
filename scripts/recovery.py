"""A second real Tau harness on this Mac's Linux VM repairs the remote harness."""

import base64
import shlex

import yaml
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
    helper = """import json,sys
from client import Client
with Client(ENDPOINT,REPO,owner='/workspace/remote-owner.key',cli='/bin/tinfoil') as c:
    print(json.dumps(c.request('exec',command=sys.argv[1])))
""".replace("ENDPOINT", repr(endpoint)).replace("REPO", repr(repo))
    return repair_with_helper(helper)


def repair_with_helper(helper, network=None):
    with LocalContainer(
        network=network, alias="recovery-agent" if network else None
    ) as host:
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
        put(host, "/workspace/remote.py", helper.encode())
        configure_remote_tools(host)
        result = host.request(
            "run",
            prompt="""The remote Tau agent fails to start. Diagnose and repair it using remote_shell.
Every remote_shell command executes in the REMOTE agent's /workspace, through its owner's command client.
Inspect its configuration and last-harness.stderr. Remote shipped defaults and adapter source live in /app.
Fix the cause; preserve the inference route and model. Use few commands, with bounded output. Do not alter /app or credentials.
Check the repaired file, then report the cause and change in two sentences. A separate test will run the remote agent afterward.""",
        )
        if not result["tools"]:
            raise AssertionError("recovery agent did not use real tools")
        return result


def configure_remote_tools(host):
    """Route actual tool execution; do not rely on the model choosing the right host."""
    config = yaml.safe_load((ROOT / "app/harness.yaml").read_text())
    role = config["agents"]["role_groups"]["darcy"]["roles"]["darcy"]
    role["tools"] = ["remote_shell"]
    role["prompt_override"] = "recovery"
    shell = config["extensions"]["core-shell"]
    shell["tool_prefix"] = "remote"
    shell["config"] = {
        "shell": {
            "command": "/bin/bash",
            "prefix": ["python3", "/workspace/remote_shell.py"],
        }
    }
    put(host, "/workspace/config/tau/harness.yaml", yaml.safe_dump(config).encode())
    put(
        host,
        "/workspace/config/tau/prompts/recovery.hbs",
        b"You repair a separate remote agent. Your only tool, remote_shell, runs commands on that remote system. Read its real diagnostics before changing files. Keep changes small. Never print credentials.\n",
    )
    wrapper = """import json,subprocess,sys
if len(sys.argv)!=4 or sys.argv[1:3]!=['/bin/bash','-c']:
    raise SystemExit('invalid remote shell invocation')
r=subprocess.run([sys.executable,'/workspace/remote.py',sys.argv[3]],capture_output=True,text=True,timeout=120)
if r.returncode:
    sys.stderr.write(r.stderr)
    raise SystemExit(r.returncode)
value=json.loads(r.stdout)
sys.stdout.write(value['stdout'])
sys.stderr.write(value['stderr'])
raise SystemExit(value['returncode'])
"""
    put(host, "/workspace/remote_shell.py", wrapper.encode())
