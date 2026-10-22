"""Local admin credentials; never print or pass them into agent processes."""

import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"


def credentials():
    path = Path(os.environ.get("DARCY_ENV_FILE", ENV_FILE))
    path.chmod(0o600)
    values = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip().removeprefix("export ")
        if name in ["TINFOIL_ADMIN_KEY", "TINFOIL_API_KEY"]:
            values[name] = value.strip().strip("\"'")
    return values


def admin(route, data=None, method=None):
    key = credentials()["TINFOIL_ADMIN_KEY"]
    req = urllib.request.Request(
        "https://api.tinfoil.sh" + route,
        data=None if data is None else json.dumps(data).encode(),
        method=method,
        headers={
            "Authorization": "Bearer " + key,
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        return json.load(response)
