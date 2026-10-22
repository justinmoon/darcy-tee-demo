"""Real Sandbox task, owner SSH recovery, and encrypted-disk restart proof."""

import argparse
import json
import shlex
import socket
import subprocess
import time
import urllib.request

import yaml
from auth_checks import check
from check_agent import challenge, inject_failure, wait_inference
from client import signed_request
from common import ROOT, credentials
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from local_container import LocalContainer
from recovery import VALIDATE, capture_tool_trace, configure_remote_tools, put
from sandbox import (
    ALIAS,
    CONFIG,
    DIRECTORY,
    PINS,
    REPO,
    TAG,
    attest,
    lifecycle,
    save,
    ssh,
)

NAME = "darcy-agent"
WORKSPACE = "/workspace/darcy-tee-demo"


def command(value, timeout=120):
    result = ssh(value, timeout=timeout)
    if result.returncode:
        raise RuntimeError("owner SSH command failed: " + result.stderr[-3000:])
    return result.stdout


def wait_started():
    deadline = time.monotonic() + 600
    last = None
    while time.monotonic() < deadline:
        row = lifecycle("status")
        status = row.get("status")
        if status != last:
            print("Sandbox: " + str(status), flush=True)
            last = status
        if status == "running":
            return
        if status in {"failed", "stopped", "error"}:
            save(DIRECTORY / "last-boot-failure.json", row)
            raise RuntimeError(
                "Sandbox boot failed: "
                + json.dumps(
                    row.get("error_message") or row.get("last_deploy_attempt_error")
                )
            )
        time.sleep(10)
    raise TimeoutError("Sandbox boot exceeded ten minutes")


class Tunnel:
    """HTTP remains local to each end of an attested, strictly pinned SSH tunnel."""

    def __enter__(self):
        self.key = Ed25519PrivateKey.from_private_bytes(
            (ROOT / ".cache/owner.key").read_bytes()
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.log = open(DIRECTORY / "tunnel.stderr", "w")
        self.process = subprocess.Popen(
            [
                "ssh",
                "-F",
                str(CONFIG),
                "-N",
                "-o",
                "ExitOnForwardFailure=yes",
                "-L",
                f"127.0.0.1:{self.port}:127.0.0.1:18080",
                ALIAS,
            ],
            stdout=subprocess.DEVNULL,
            stderr=self.log,
        )
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError(
                        "pinned SSH tunnel stopped; inspect tunnel.stderr"
                    )
                try:
                    with urllib.request.urlopen(
                        self.base + "/health", timeout=2
                    ) as response:
                        if json.load(response).get("service") == "darcy-tee-demo":
                            return self
                except (OSError, ValueError):
                    time.sleep(0.4)
            raise TimeoutError("Sandbox agent did not become healthy through SSH")
        except BaseException:
            self.__exit__()
            raise

    def request(self, action, **fields):
        if self.process.poll() is not None:
            raise RuntimeError("pinned SSH tunnel stopped")
        return signed_request(self.base, self.key, action, **fields)

    def __exit__(self, *args):
        self.process.terminate()
        try:
            self.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.log.close()


def install():
    config = yaml.safe_load((ROOT / "tinfoil-config.yml").read_text())
    image = config["containers"][0]["image"]
    owner = config["containers"][0]["env"][0]["DARCY_OWNER_PUBLIC_KEY"]
    existing = ssh("docker inspect --format '{{.Config.Image}}' " + NAME)
    if existing.returncode == 0:
        if existing.stdout.strip() != image:
            raise RuntimeError(
                "existing test agent uses another image; refusing to replace it"
            )
        return image
    # This is owner installation after base attestation, not part of base measurement.
    command("docker pull " + shlex.quote(image), timeout=240)
    digest = json.loads(
        command(
            "docker image inspect --format '{{json .RepoDigests}}' "
            + shlex.quote(image)
        )
    )
    if image not in digest:
        raise RuntimeError("installed image digest does not match release")
    command("mkdir -p " + WORKSPACE + "; test $(id -u) = 1000")
    command(
        "docker run -d --name "
        + NAME
        + " --read-only --cap-drop=ALL --security-opt=no-new-privileges"
        + " --tmpfs /tmp:size=128m,mode=1777 --pids-limit 256"
        + " --memory 2g --cpus 2 --restart unless-stopped"
        + " -v "
        + WORKSPACE
        + ":/workspace"
        + " -p 127.0.0.1:18080:8080 -e DARCY_OWNER_PUBLIC_KEY="
        + owner
        + " "
        + shlex.quote(image)
    )
    return image


def repair(transport_only=False, tool_probe=False, debug_probe=False, model="kimi-k3"):
    # Give the local agent only this boot's SSH owner identity and attested pin.
    profile = CONFIG.read_text()
    identity_line = next(
        line
        for line in profile.splitlines()
        if line.strip().startswith("IdentityFile ")
    )
    identity = shlex.split(identity_line)[1]
    from pathlib import Path

    profile = profile.replace(identity, "/workspace/sandbox-owner")
    profile = profile.replace(str(PINS), "/workspace/known_hosts")
    helper = """import json,subprocess,sys
command = 'docker exec -w /workspace darcy-agent /bin/bash -c ' + __import__('shlex').quote(sys.argv[1])
r = subprocess.run(['ssh','-F','/workspace/ssh.conf','darcy-tee-sandbox',command],capture_output=True,text=True,timeout=45)
print(json.dumps(dict(returncode=r.returncode,stdout=r.stdout,stderr=r.stderr)))
"""
    with LocalContainer() as host:
        wait_inference(host)
        host.request(
            "initialize",
            inference_key=credentials()["TINFOIL_API_KEY"],
            model=model,
        )
        put(host, "/workspace/sandbox-owner", Path(identity).read_bytes())
        put(host, "/workspace/known_hosts", PINS.read_bytes())
        put(host, "/workspace/ssh.conf", profile.encode())
        put(host, "/workspace/remote.py", helper.encode())
        configure_remote_tools(host)
        probe = host.request(
            "exec", command="python3 /workspace/remote.py 'printf transport-ok'"
        )
        save(DIRECTORY / "recovery-transport.json", probe)
        if probe["returncode"] != 0:
            raise RuntimeError(
                "local-to-Sandbox SSH failed: " + probe["stderr"][-2000:]
            )
        value = json.loads(probe["stdout"])
        if value["returncode"] != 0 or value["stdout"] != "transport-ok":
            raise RuntimeError(
                "local-to-Sandbox SSH failed: " + value["stderr"][-2000:]
            )
        wrapped = host.request(
            "exec",
            command="python3 /workspace/remote_shell.py /bin/bash -c 'printf wrapper-ok'",
        )
        save(DIRECTORY / "recovery-wrapper.json", wrapped)
        if wrapped["returncode"] != 0 or wrapped["stdout"] != "wrapper-ok":
            raise RuntimeError(
                "remote shell wrapper failed: " + wrapped["stderr"][-2000:]
            )
        if transport_only:
            catalog = host.request(
                "exec",
                command="HOME=/workspace XDG_CONFIG_HOME=/workspace/config XDG_STATE_HOME=/tmp/catalog-state DARCY_OUTER_SANDBOX=tinfoil-container timeout 20 tau --role darcy dev print-tools > /workspace/effective-tools.txt 2>&1; code=$?; grep -n -E 'wait|remote_shell|error' /workspace/effective-tools.txt | head -n 20; exit $code",
            )
            save(DIRECTORY / "effective-tools.json", catalog)
            return {
                "transport": "real pinned SSH passed",
                "model_calls": 0,
                "effective_tools": catalog,
            }
        if debug_probe:
            debug = """import json
from pathlib import Path
source=Path('/app/tau_agent.py').read_text()
start=source.index('                if kind in [')
end=source.index('                    events.append(event)',start)
source=source[:start]+'                if True:\\n'+source[end:]
scope={'__file__':'/app/tau_agent.py'}
exec(compile(source,'/app/tau_agent.py','exec'),scope)
r=scope['run']('/workspace',"Use remote_shell exactly once to run printf ACTUAL-TOOL-OK. Report the exact tool response, including any error. Do not change files.",'gpt-oss-120b',timeout=25)
r['events']=[e for e in r['events'] if ('tool' in e['event'] and 'register' not in e['event']) or 'notice' in e['event']]
print(json.dumps(r,default=str))
"""
            put(host, "/workspace/debug_ui.py", debug.encode())
            result = host.request("exec", command="python3 /workspace/debug_ui.py")
            save(DIRECTORY / "debug-ui.json", result)
            capture_tool_trace(host, DIRECTORY / "debug-ui-tool-trace.jsonl")
            return result
        if tool_probe:
            result = host.request(
                "run",
                prompt="Use remote_shell once to run: printf 'ACTUAL-TOOL-OK'; cat /workspace/config/tau/harness.yaml. Report the exact tool output or the exact error. Do not change files.",
            )
            result["private_diagnostics"] = host.capture_diagnostics()
            capture_tool_trace(host, DIRECTORY / "tool-probe-trace.jsonl")
            return result
        result = host.request(
            "run",
            prompt="""The remote Tau agent fails to start. Diagnose and repair it using remote_shell.
Every remote_shell command executes inside the REMOTE agent container through attested owner SSH.
Do not print private keys or alter credentials.
Inspect /workspace/config/tau/harness.yaml, /workspace/last-harness.stderr and shipped defaults/source under /app.
Fix the cause and preserve inference settings. Inspect the shipped reference configuration, not guessed paths. Use few commands and bounded output.
Before reporting success, use Tau's real config loader and fix any error:
"""
            + VALIDATE
            + """
Report the cause and fix in two sentences. A separate test will run the remote agent.""",
        )
        if not result["tools"]:
            raise AssertionError("local recovery agent used no tools")
        result["private_diagnostics"] = host.capture_diagnostics()
        return result


def initialize(remote):
    wait_inference(remote)
    if not remote.request("status")["initialized"]:
        remote.request(
            "initialize",
            inference_key=credentials()["TINFOIL_API_KEY"],
            model="gpt-oss-120b",
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--installed",
        action="store_true",
        help="Resume an already installed test agent",
    )
    parser.add_argument("--transport-only", action="store_true")
    parser.add_argument(
        "--keep-running",
        action="store_true",
        help="Keep this owned test VM running after the command",
    )
    args = parser.parse_args()
    evidence = DIRECTORY / "e2e"
    evidence.mkdir(exist_ok=True)
    try:
        wait_started()
        print(attest(), flush=True)
        image = install()
        if args.transport_only:
            print(json.dumps(repair(transport_only=True)), flush=True)
            return
        # Test setup: fresh gateway memory and known shipped config at initialize.
        # Persistent workspace data stays in place; the agent still performs real tasks.
        command("docker restart " + NAME)
        with Tunnel() as remote:
            auth = check(remote.base, remote.key)
            initialize(remote)
            first = challenge(remote, "Sandbox agent")
            save(evidence / "before.json", first)
            failure = inject_failure(remote)
            save(evidence / "fault.json", {"error": failure})
            recovery = repair()
            save(evidence / "recovery.json", recovery)
            last = challenge(remote, "repaired Sandbox agent")
            save(evidence / "after.json", last)
        import secrets

        nonce = secrets.token_hex(24)
        command(
            "printf %s "
            + nonce
            + " > "
            + WORKSPACE
            + "/persistence.txt; printf %s "
            + nonce
            + " | sudo tee /usr/local/share/darcy-persistence.txt >/dev/null"
        )
        old_pins = PINS.read_text()
        lifecycle("stop")
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if lifecycle("status")["status"] == "stopped":
                break
            time.sleep(5)
        else:
            raise TimeoutError("Sandbox stop did not finish")
        lifecycle("start")
        wait_started()
        print(attest(), flush=True)
        workspace = command("cat " + WORKSPACE + "/persistence.txt").strip() == nonce
        system = command("cat /usr/local/share/darcy-persistence.txt").strip() == nonce
        assert workspace and system, "encrypted workspace or system overlay lost state"
        assert old_pins != PINS.read_text(), "expected fresh boot SSH key"
        with Tunnel() as remote:
            initialize(remote)
            restarted = challenge(remote, "restarted Sandbox agent")
            save(evidence / "restarted.json", restarted)
        summary = dict(
            mocked_components=[],
            base_release=REPO + "@" + TAG,
            owner_installed_image=image,
            authorization=auth,
            first_tools=first["tools"],
            recovery_tools=recovery["tools"],
            repaired_tools=last["tools"],
            restarted_tools=restarted["tools"],
            workspace_persisted=workspace,
            system_overlay_persisted=system,
            boot_key_rotated=True,
            monitor_tested=False,
        )
        save(evidence / "summary.json", summary)
        print(json.dumps(summary, indent=2), flush=True)
    finally:
        if not args.keep_running:
            lifecycle("stop")


if __name__ == "__main__":
    main()
