"""Read-only account readiness; never prints credentials."""

import json

from common import admin

if __name__ == "__main__":
    context = admin("/api/auth/context")
    limits = admin("/api/infrastructure/limits")
    hosts = admin("/api/containers/hosts")
    print(
        json.dumps(
            {
                "context": context.get("context_type"),
                "hosts": hosts,
                "sandboxes_enabled": limits.get("sandboxes_enabled"),
                "limits": limits.get("limits"),
            },
            indent=2,
        )
    )
