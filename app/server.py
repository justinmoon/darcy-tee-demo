"""Single-owner confidential Tau demo; independent control process, no host admin key."""

import json
import os
import signal
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from security import Owner, Unauthorized
from tau_agent import configure, run

ROOT = Path(os.environ.get("DARCY_WORKSPACE", "/workspace"))
ROOT.mkdir(parents=True, exist_ok=True)
OWNER = Owner(os.environ["DARCY_OWNER_PUBLIC_KEY"])
BUSY = threading.Lock()
KEY = None
MODEL = None
PROXY = None
PROXY_READY = threading.Event()
MODEL_REQUESTS = 0
BUDGET_LOCK = threading.Lock()


def proxy():
    global PROXY
    log = (ROOT / "proxy.stderr").open("wb")
    PROXY = subprocess.Popen(
        ["tinfoil", "proxy", "--bind", "127.0.0.1", "--port", "8082"],
        stdout=log,
        stderr=log,
        env={
            k: v
            for k, v in os.environ.items()
            if k not in ["TINFOIL_ADMIN_KEY", "TINFOIL_API_KEY"]
        },
    )
    end = time.monotonic() + 90
    while time.monotonic() < end:
        if PROXY.poll() is not None:
            raise RuntimeError("attested inference proxy exited")
        try:
            urllib.request.urlopen("http://127.0.0.1:8082/v1/models", timeout=2).close()
            PROXY_READY.set()
            return
        except urllib.error.HTTPError:
            PROXY_READY.set()
            return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError("attested inference proxy timed out")


class Gateway(BaseHTTPRequestHandler):
    # Only Tau's loopback keyless profile can reach this gateway. External routing exposes port 8080 only.
    def log_message(self, *a):
        pass

    def do_POST(self):
        global MODEL_REQUESTS
        with BUDGET_LOCK:
            if MODEL_REQUESTS >= 16:
                return self.send_error(429)
            MODEL_REQUESTS += 1
        if self.path != "/v1/chat/completions" or not KEY:
            return self.send_error(503)
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 2 * 1024 * 1024:
            return self.send_error(413)
        started = False
        try:
            data = json.loads(self.rfile.read(length))
            data["model"] = MODEL
            data["max_tokens"] = min(int(data.get("max_tokens", 2048)), 2048)
            data.pop("chat_template_kwargs", None)
            data["reasoning_effort"] = "low"
            req = urllib.request.Request(
                "http://127.0.0.1:8082/v1/chat/completions",
                data=json.dumps(data).encode(),
                headers={
                    "Authorization": "Bearer " + KEY,
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=150) as response:
                self.send_response(response.status)
                self.send_header(
                    "Content-Type",
                    response.headers.get("Content-Type", "application/json"),
                )
                self.end_headers()
                started = True
                while chunk := response.read(512):
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except Exception:
            # Upstream bodies may contain credentials or prompts. Do not expose them.
            if not started:
                self.send_error(502, "attested inference unavailable")
            self.close_connection = True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, value):
        data = json.dumps(value, default=lambda _: None).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            return self.reply(200, {"service": "darcy-tee-demo", "control": "ready"})
        self.reply(404, {"error": "not found"})

    def do_POST(self):
        global KEY, MODEL
        if self.path != "/control":
            return self.reply(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n < 1 or n > 128 * 1024:
                raise Unauthorized("invalid length")
            p = OWNER.verify(self.rfile.read(n))
            action = p["action"]
        except Exception:
            return self.reply(401, {"error": "owner authentication required"})
        locked = action in ["initialize", "run"]
        if locked and not BUSY.acquire(blocking=False):
            return self.reply(409, {"error": "another operation is running"})
        try:
            if action == "initialize":
                if KEY is not None:
                    raise RuntimeError("already initialized")
                key = p["inference_key"]
                model = p["model"]
                if not isinstance(key, str) or not 8 < len(key) < 512 or "\n" in key:
                    raise ValueError("invalid inference key")
                if not isinstance(model, str) or not 1 <= len(model) <= 128:
                    raise ValueError("invalid model")
                configure(ROOT, model)
                KEY = key
                MODEL = model
                self.reply(200, {"initialized": True, "model": MODEL})
            elif action == "run":
                if not KEY:
                    raise RuntimeError("initialize first")
                prompt = p["prompt"]
                if not isinstance(prompt, str) or not 1 <= len(prompt) <= 32768:
                    raise ValueError("invalid prompt")
                result = run(ROOT, prompt, MODEL, timeout=180)
                self.reply(200, result)
            elif action == "exec":
                command = p["command"]
                if not isinstance(command, str) or not 1 <= len(command) <= 16384:
                    raise ValueError("invalid command")
                env = {
                    k: v
                    for k, v in os.environ.items()
                    if k in ["PATH", "SSL_CERT_FILE", "LANG"]
                }
                env["HOME"] = str(ROOT)
                child = subprocess.Popen(
                    ["/bin/bash", "-c", command],
                    cwd=ROOT,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    start_new_session=True,
                )
                try:
                    out, err = child.communicate(timeout=30)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.communicate()
                    raise RuntimeError("command timed out")
                self.reply(
                    200,
                    {
                        "returncode": child.returncode,
                        "stdout": out[:65536].decode(errors="replace"),
                        "stderr": err[:65536].decode(errors="replace"),
                    },
                )
            elif action == "status":
                self.reply(
                    200,
                    {
                        "control": "ready",
                        "initialized": KEY is not None,
                        "model": MODEL,
                        "uid": os.getuid(),
                        "platform": os.uname().sysname,
                        "proxy_alive": PROXY is not None and PROXY.poll() is None,
                        "proxy_ready": PROXY_READY.is_set()
                        and PROXY is not None
                        and PROXY.poll() is None,
                        "model_requests": MODEL_REQUESTS,
                    },
                )
            else:
                self.reply(400, {"error": "unknown action"})
        except Exception as e:
            # The authenticated owner may inspect private diagnostics; no logging or external crash collector.
            self.reply(500, {"error": str(e)[:4096]})
        finally:
            if locked:
                BUSY.release()


if __name__ == "__main__":
    threading.Thread(
        target=ThreadingHTTPServer(("127.0.0.1", 8081), Gateway).serve_forever,
        daemon=True,
    ).start()
    # A proxy failure does not disable the owner control API.
    threading.Thread(target=proxy, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
