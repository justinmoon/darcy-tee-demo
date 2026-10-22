"""Bounded container lifecycle; saves accepted IDs before any follow-up operation."""

import argparse
import json
import urllib.error
from pathlib import Path

from common import ROOT, admin

STATE = ROOT / ".cache/deployment.json"

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["create", "status", "stop", "start"])
    p.add_argument("--repo", default="justinmoon/darcy-tee-demo")
    p.add_argument("--tag")
    p.add_argument("--name", default="darcy-tau-demo")
    p.add_argument("--state", type=Path, default=STATE)
    args = p.parse_args()
    STATE = args.state
    try:
        if args.action == "create":
            if STATE.exists():
                raise RuntimeError(
                    "deployment state exists; inspect status before creating another instance"
                )
            if not args.tag:
                p.error("--tag required")
            check = admin(
                "/api/containers/validate", {"repo": args.repo, "tag": args.tag}
            )
            if not check.get("valid"):
                raise RuntimeError(json.dumps(check))
            row = admin(
                "/api/containers",
                {
                    "name": args.name,
                    "repo": args.repo,
                    "tag": args.tag,
                    "mark_latest_release": False,
                },
            )
            STATE.write_text(json.dumps(row, indent=2))
            STATE.chmod(0o600)
        else:
            previous = json.loads(STATE.read_text())
            route = "/api/containers/" + previous["id"]
            if args.action == "status":
                row = admin(route)
            else:
                row = admin(
                    route + ("/stop" if args.action == "stop" else "/deploy"),
                    {"tag": args.tag} if args.action == "start" and args.tag else {},
                )
            STATE.write_text(json.dumps(row, indent=2))
        print(
            json.dumps(
                {
                    k: row.get(k)
                    for k in [
                        "id",
                        "name",
                        "status",
                        "domain",
                        "current_tag",
                        "error_message",
                        "last_deploy_attempt_error",
                    ]
                },
                indent=2,
            )
        )
    except urllib.error.HTTPError as error:
        print(
            json.dumps(
                {"http_status": error.code, "error": error.read().decode()[:4096]}
            )
        )
        raise SystemExit(1)
