"""A second real Tau harness on this Mac's Linux VM repairs the remote harness."""

import base64
import shlex
from pathlib import Path

import yaml
from check_agent import exec_ok, wait_inference
from common import ROOT, credentials
from local_container import LocalContainer

VALIDATE = "HOME=/workspace XDG_CONFIG_HOME=/workspace/config DARCY_OUTER_SANDBOX=tinfoil-container timeout 20 tau dev print-system-prompt >/dev/null"


def put(client, path, data, mode="600"):
    encoded = base64.b64encode(data).decode()
    exec_ok(
        client,
        f"printf %s {shlex.quote(encoded)} | base64 -d > {shlex.quote(path)}; chmod {mode} {shlex.quote(path)}",
    )


def repair(endpoint, repo, config=None):
    helper = (
        """import json,sys
from client import Client
with Client(ENDPOINT,REPO,owner='/workspace/remote-owner.key',cli='/bin/tinfoil',config=CONFIG) as c:
    print(json.dumps(c.request('exec',command=sys.argv[1])))
""".replace("ENDPOINT", repr(endpoint))
        .replace("REPO", repr(repo))
        .replace("CONFIG", repr("/workspace/remote-config.yml") if config else "None")
    )
    files = {"remote-config.yml": Path(config).read_bytes()} if config else {}
    return repair_with_helper(helper, files=files)


def repair_with_helper(helper, network=None, files=None, model="gpt-oss-120b"):
    with LocalContainer(
        network=network, alias="recovery-agent" if network else None
    ) as host:
        wait_inference(host)
        host.request(
            "initialize",
            inference_key=credentials()["TINFOIL_API_KEY"],
            model=model,
        )
        for name in ["client.py", "common.py"]:
            put(host, "/workspace/" + name, (ROOT / "scripts" / name).read_bytes())
        put(
            host,
            "/workspace/remote-owner.key",
            (ROOT / ".cache/owner.key").read_bytes(),
        )
        put(host, "/workspace/remote.py", helper.encode())
        for name, data in (files or {}).items():
            put(host, "/workspace/" + name, data)
        configure_remote_tools(host)
        result = host.request(
            "run",
            prompt="""The remote Tau agent fails to start. Diagnose and repair it using remote_shell.
Every remote_shell command executes in the REMOTE agent's /workspace, through its owner's command client.
Inspect its configuration and last-harness.stderr. Remote shipped defaults and adapter source live in /app.
Fix the cause; preserve the inference route and model. Use few commands, with bounded output. Do not alter /app or credentials.
Check with Tau's own config loader, not only YAML syntax. Run this remotely and fix any error before reporting success:
"""
            + VALIDATE
            + """
Then report the cause and change in two sentences. A separate test will run the remote agent afterward.""",
        )
        if not result["tools"]:
            raise AssertionError("recovery agent did not use real tools")
        return result


def configure_remote_tools(host):
    """Route actual tool execution; do not rely on the model choosing the right host."""
    config = yaml.safe_load((ROOT / "app/harness.yaml").read_text())
    role = config["agents"]["role_groups"]["darcy"]["roles"]["darcy"]
    role["tools"] = ["remote_shell", "wait", "cancel"]
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
        b"You repair a separate remote agent. remote_shell runs commands on that remote system. Slow tools are backgrounded: use wait with their tool_call_id (or wait({})) to obtain completed output. A background placeholder is not a result. Wait for every command before reading its output or finishing. Read real diagnostics and inspect the shipped reference configuration. Validate with the actual application's loader; YAML syntax alone is insufficient. Keep changes small. Never print credentials.\n",
    )
    wrapper = """import json,subprocess,sys,time,os
if len(sys.argv)!=4 or sys.argv[1:3]!=['/bin/bash','-c']:
    raise SystemExit('invalid remote shell invocation')
started=time.monotonic()
r=subprocess.run([sys.executable,'/workspace/remote.py',sys.argv[3]],capture_output=True,text=True,timeout=120)
with os.fdopen(os.open('/workspace/remote-tools.jsonl',os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600),'a') as trace:
    trace.write(json.dumps(dict(command=sys.argv[3],returncode=r.returncode,stdout=r.stdout[:65536],stderr=r.stderr[:65536],seconds=round(time.monotonic()-started,3)))+'\\n')
if r.returncode:
    sys.stderr.write(r.stderr)
    raise SystemExit(r.returncode)
value=json.loads(r.stdout)
sys.stdout.write(value['stdout'])
sys.stderr.write(value['stderr'])
raise SystemExit(value['returncode'])
"""
    put(host, "/workspace/remote_shell.py", wrapper.encode())


def capture_tool_trace(host, path):
    result = host.request(
        "exec", command="cat /workspace/remote-tools.jsonl 2>/dev/null || true"
    )
    path.write_text(result["stdout"])
    path.chmod(0o600)
