"""Small subset of Darcy's Tau adapter, without its OpenShell execution adapter."""

import json
import os
import queue
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path

import cbor2

MAX_EVENTS = 2000


def configure(root, model, provider_url="http://127.0.0.1:8081/v1"):
    config = Path(root) / "config/tau"
    profiles = config / "providers/provider-builtin"
    profiles.mkdir(parents=True, exist_ok=True)
    (config / "harness.yaml").write_bytes(
        Path(__file__).with_name("harness.yaml").read_bytes()
    )
    (config / "prompts").mkdir(exist_ok=True)
    (config / "prompts/darcy.hbs").write_bytes(
        Path(__file__).with_name("darcy.hbs").read_bytes()
    )
    # Keyless only toward the owned loopback gateway, which holds the inference credential.
    profile = {
        "kind": "chat_completions",
        "base_url": provider_url,
        "models": [{"id": model, "context_window": 32768}],
        "max_output_tokens": 2048,
        "credential": {"kind": "none"},
    }
    (profiles / "darcy.json").write_text(json.dumps(profile))
    return profiles / "darcy.json"


def run(root, prompt, model, timeout=180):
    root = Path(root)
    env = {
        k: v
        for k, v in os.environ.items()
        if k in ["PATH", "SSL_CERT_FILE", "NIX_SSL_CERT_FILE", "LANG"]
    }
    sid = uuid.uuid4().hex
    home = root / "sessions" / sid
    home.mkdir(parents=True, exist_ok=True)
    env.update(
        DARCY_OUTER_SANDBOX="tinfoil-container",
        DARCY_BLOCKING_SHELL="1",
        HOME=str(home),
        XDG_CONFIG_HOME=str(root / "config"),
        XDG_STATE_HOME=str(home / "state"),
        XDG_CACHE_HOME=str(home / "cache"),
        XDG_RUNTIME_DIR="/tmp",
        TAU_SESSION_ID=sid,
    )
    log = root / "last-harness.stderr"
    with log.open("wb") as error:
        child = subprocess.Popen(
            ["tau", "component", "harness", "--initial-ui-stdio"],
            cwd=root,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=error,
            start_new_session=True,
            bufsize=-1,
        )
        messages = queue.Queue(maxsize=32)

        def read():
            try:
                while True:
                    messages.put(cbor2.load(child.stdout))
            except BaseException as e:
                messages.put(e)

        threading.Thread(target=read, daemon=True).start()

        def send(message, payload):
            cbor2.dump({"message": message, "payload": payload}, child.stdin)
            child.stdin.flush()

        send(
            "hello",
            {
                "protocol_version": {"major": 14, "minor": 0},
                "client_name": "darcy-demo",
                "client_kind": "ui",
            },
        )
        send(
            "subscribe",
            {
                "historical_selectors": [{"kind": "prefix", "value": "harness."}],
                "live_selectors": [{"kind": "prefix", "value": ""}],
            },
        )
        started = time.monotonic()
        submitted = False
        events = []
        text = ""
        tools = []
        failure = None
        failure_notice = None
        finished = False
        try:
            while time.monotonic() - started < timeout:
                try:
                    frame = messages.get(
                        timeout=min(
                            1, max(0.01, timeout - (time.monotonic() - started))
                        )
                    )
                except queue.Empty:
                    if child.poll() is not None:
                        raise RuntimeError(
                            "Tau exited: " + log.read_text(errors="replace")[-2500:]
                        )
                    continue
                if isinstance(frame, BaseException):
                    raise RuntimeError(
                        f"Tau stream ended ({type(frame).__name__}: {frame}; exit={child.poll()}): "
                        + log.read_text(errors="replace")[-2500:]
                    )
                if frame.get("message") == "disconnect":
                    raise RuntimeError("Tau disconnected: " + str(frame.get("payload")))
                if frame.get("message") != "deliver":
                    continue
                delivery = frame["payload"]
                event = delivery["event"]
                kind = event["event"]
                p = event["payload"]
                if kind == "harness.notice" and p.get("kind") == "harness.failure":
                    failure_notice = p.get("message")
                if kind == "agent.prompt_failed":
                    raise RuntimeError(
                        failure_notice or p.get("message", "prompt failed")
                    )
                if len(events) >= MAX_EVENTS:
                    raise RuntimeError("event limit reached")
                if (
                    kind == "harness.models_available"
                    and not submitted
                    and "darcy/" + model in json.dumps(p)
                ):
                    submitted = True
                    send(
                        "emit",
                        {
                            "event": {
                                "event": "ui.create_agent",
                                "payload": {
                                    "request_id": sid,
                                    "session_id": sid,
                                    "role": "darcy",
                                    "initial_prompt": prompt,
                                    "literal": True,
                                    "ctx_id": sid,
                                    "model_override": "darcy/" + model,
                                },
                            },
                            "persist": True,
                        },
                    )
                if kind in [
                    "tool.started",
                    "tool.result",
                    "tool.error",
                    "tool.result_display",
                    "provider.response_finished",
                    "agent.outer_turn_finished",
                    "ui.create_agent_result",
                ]:
                    events.append(event)
                if kind == "provider.response_updated":
                    text += "".join(
                        d["text"]
                        for d in p.get("deltas", [])
                        if d.get("type") == "message"
                    )
                if kind == "tool.started":
                    tools.append(p["tool_name"])
                if kind == "provider.response_finished" and p.get("error"):
                    failure = p["error"]
                if kind == "agent.outer_turn_finished" and submitted:
                    finished = True
                    break
            if not finished:
                raise TimeoutError("Tau task exceeded deadline")
            if failure:
                raise RuntimeError(failure)
            return {
                "answer": text,
                "tools": tools,
                "events": events,
                "session": sid,
                "seconds": round(time.monotonic() - started, 2),
            }
        finally:
            # Kill the entire owned group, including any tool process left behind.
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
