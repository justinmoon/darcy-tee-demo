# Darcy confidential Tau demo

Small, single-owner experiment: Tau harness and file/shell tools run in a Tinfoil
Container. Inference goes through a verified Tinfoil connection. A separate local
Tau agent can inspect and repair a failed remote harness through owner-signed
commands.

Cloud E2E validation remains pending. See `.cache/cloud-e2e/summary.json` after a
successful run; local execution alone does not prove confidential execution.

## Parts

- `app/tau_agent.py`: small adapter based on Darcy's pinned Tau protocol.
- `app/server.py`: owner control API, Tau child process, inference gateway.
- `scripts/client.py`: Tinfoil verified proxy plus signed owner requests. No
  ordinary-TLS fallback.
- `scripts/e2e.py`: actual cloud task, actual startup failure, actual local agent
  repair, fresh cloud task. No model or tool mocks.
- `scripts/recovery.py`: recovery harness on this Mac's local Linux runtime.
- [Containers vs Sandboxes](docs/containers-and-sandboxes.md): source review and
  account access findings.

No OpenShell or VM runs inside the cloud container. Tau tools and the control
service share one trust zone. This is a demo for one owner, not a multi-tenant
service or a boundary between malicious tools and the supervisor.
The pinned Tau build carries Darcy's small outer-sandbox patch, scoped to
`DARCY_OUTER_SANDBOX=tinfoil-container`. It omits Tau's nested mount namespace;
the ordinary upstream path keeps its existing behavior.

## Host setup

Apple Silicon Mac, Nix, and a running Docker-compatible Linux runtime. Docker is
used for the local test/recovery harness; the cloud privacy boundary is the
confidential VM. This developer demo has not been packaged as a desktop app.

Create `.env` (mode `0600`, ignored by Git):

```dotenv
TINFOIL_ADMIN_KEY=<organization admin key>
TINFOIL_API_KEY=<inference key>
```

Or set `DARCY_ENV_FILE` to an existing dotenv file. The parser reads these two
names; it does not execute the file. The admin key stays on the host. The inference
key reaches the cloud only through the verified connection after owner login.
It stays in the gateway's memory, outside Tau's environment and provider file.
This does not make it safe against arbitrary code in the same trust zone.

```sh
just bootstrap
just account
just test
just lint
just build-image
just load-image
just local-e2e
```

Back up `.cache/owner.key` securely. The public key is part of the measured config;
another owner needs their own config and release. A lost private key has no
operator bypass.

## Release and cloud test

Build the Nix image, publish it to GHCR, pin its OCI digest in
`tinfoil-config.yml`, and publish the measured release with the two Tinfoil
workflows. `publish-image.yml` can load the prebuilt Nix archive from a GitHub
release asset named `image.tar.gz`; this keeps image builds in Nix.

```sh
just deploy create --tag v0.1.0
just deploy status
just e2e <instance-domain> justinmoon/darcy-tee-demo@v0.1.0
just deploy stop
```

Creating/deploying requires an active Containers subscription and available host.
Stop the instance after testing to end compute use. Stop/restart clears this
demo's memory-backed workspace and inference key; initialize again after boot.
The local test containers clean themselves up on success or failure.

The test uses `gpt-oss-120b`, low reasoning effort, at most 2,048 output tokens per
request and 16 inference requests per running instance. There is no metered
fan-out. Private traces stay under `.cache`; publishing a bug report requires a
separate review of its contents. This demo does not promise automatic PII removal.

## Test proof

1. Verify the pinned release before sending credentials, prompts or commands.
2. Deny anonymous requests, another owner's signatures and replayed requests.
3. Seed a random file unknown to the model; require real tools to read it and
   write its reversed contents. Check the file from outside the agent.
4. Break the remote harness YAML. Confirm Tau fails while owner control remains
   reachable.
5. Let a second real Tau agent on this Mac inspect remote logs/files and fix the
   cause. It gets a command client, not a canned repair action.
6. Run a fresh hidden-file challenge in the repaired cloud harness.

This proves a configuration recovery path. A dead VM, dead control process,
compromised supervisor or lost key needs a different recovery route. Network
egress is open for this experiment; arbitrary tools can send data out. Tight
network permissions and a separate credential boundary remain later work.
