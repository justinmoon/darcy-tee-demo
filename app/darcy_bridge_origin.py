"""Darcy JSON-lines adapter for the pinned Tau CBOR protocol. Runs only in OpenShell."""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import cbor2

root = Path("/sandbox/darcy")
root.mkdir(exist_ok=True)
os.chdir(root)
session = sys.argv[1]
assert session.isalnum() and len(session) <= 64
home = root / session
home.mkdir(exist_ok=True)
env = dict(
    os.environ,
    HOME=str(home),
    XDG_CONFIG_HOME="/sandbox/config",
    XDG_STATE_HOME=str(home / "state"),
    XDG_CACHE_HOME=str(home / "cache"),
    XDG_RUNTIME_DIR="/tmp",
    TAU_SESSION_ID=session,
)
if (home / "state/tau/sessions" / session).exists():
    env["TAU_SESSION_STATUS"] = "resumed"
child = subprocess.Popen(
    ["/usr/bin/tau", "component", "harness", "--initial-ui-stdio"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=sys.stderr,
    env=env,
    bufsize=0,
)
lock = threading.Lock()


def send(value):
    with lock:
        cbor2.dump(value, child.stdin)
        child.stdin.flush()


def emit(value):
    print(json.dumps(value, ensure_ascii=False, default=lambda _: None), flush=True)


def input_loop():
    try:
        for line in sys.stdin:
            if len(line) > 1024 * 1024:
                raise ValueError("oversize command")
            send(json.loads(line))
    finally:
        child.terminate()


threading.Thread(target=input_loop, daemon=True).start()
try:
    while True:
        emit(cbor2.load(child.stdout))
except EOFError:
    code = child.wait()
    if code:
        raise SystemExit(code)
finally:
    child.terminate()
