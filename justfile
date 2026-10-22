set shell := ["bash", "-euo", "pipefail", "-c"]
default:
    @just --list
bootstrap:
    nix develop --command python3 scripts/bootstrap.py
    nix develop --command python3 scripts/owner_key.py
build-image:
    nix build .#image --out-link .cache/image
test:
    nix develop --command python3 -m unittest discover -s tests -v
lint:
    nix develop --command ruff check app scripts tests
format:
    nix develop --command ruff format app scripts tests
owner-key:
    nix develop --command python3 scripts/owner_key.py
client *args:
    nix develop --command python3 scripts/client.py {{args}}
account:
    nix develop --command python3 scripts/account.py
load-image:
    docker load -i .cache/image
local-e2e:
    nix develop --command python3 scripts/local_e2e.py
deploy *args:
    nix develop --command python3 scripts/deploy.py {{args}}
configure-release digest:
    nix develop --command python3 scripts/configure_release.py {{quote(digest)}}
e2e endpoint repo:
    nix develop --command python3 scripts/e2e.py --endpoint {{quote(endpoint)}} --repo {{quote(repo)}}
sandbox *args:
    nix develop --command python3 scripts/sandbox.py {{args}}
sandbox-e2e *args:
    nix develop --command python3 scripts/sandbox_e2e.py {{args}}
