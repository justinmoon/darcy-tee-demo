# Darcy confidential Tau demo

Small, single-owner experiment: Tau harness and file/shell tools run in a Tinfoil
confidential VM. Inference goes through a verified Tinfoil connection. A separate local
Tau agent can inspect and repair a failed remote harness through owner-signed
commands.

Two deployment paths: a minimal custom Container, and an owner-installed image in
Tinfoil's managed Sandbox. **The full Sandbox E2E passed**, including local-agent
repair and encrypted-disk recovery after a VM restart. [Selected proof](evidence/sandbox-e2e.json).
The org currently permits Sandboxes but rejects modern custom config deployments.
The [one-command prompt](evidence/playable-demo.json) also passed a separate
start/attest/run/stop cycle. Compute is stopped; the encrypted 16 GB disk remains.

## Parts

- `app/tau_agent.py`: small adapter based on Darcy's pinned Tau protocol.
- `app/server.py`: owner control API, Tau child process, inference gateway.
- `scripts/client.py`: Tinfoil verified proxy plus signed owner requests. No
  ordinary-TLS fallback.
- `scripts/e2e.py`: actual cloud task, actual startup failure, actual local agent
  repair, fresh cloud task. No model or tool mocks.
- `scripts/recovery.py`: recovery harness on this Mac's local Linux runtime.
- `scripts/sandbox.py`: measured base config review, attested SSH, encrypted disk
  unlock, start/stop; project-owned keys and trust policy.
- `scripts/sandbox_e2e.py`: Sandbox task, local repair, full VM restart and fresh task.
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

## Sandbox demo

The working route uses the pinned official Sandbox template, with direct networking
(`NO_MONITOR=1`). We attest its exact owner-specific config before SSH or disk
unlock, then install our image by OCI digest. The app image is an owner-installed
workload, not part of the measured base image. No claim of a reviewed Monitor or
credential isolation from malicious tools.

```sh
# Existing project state: one real prompt; stops compute afterward.
just sandbox-chat 'Use Python to count the files in this workspace.'
# Full task, deliberate failure, local agent repair, stop/start, persistence test.
just sandbox-e2e
just sandbox status
```

For a fresh account, run `just sandbox create` first. The default encrypted workspace
is 16 GB. It needs enough disk for the app image and Docker state; our 4 GB test
could not boot. Review costs and keep account access enabled before creating it.

Back up **all of `.cache/sandbox`**, securely, plus `.cache/owner.key`. The Sandbox
directory holds volume keys as well as owner SSH identity. An SSH key alone does
not recover the encrypted disk. Nothing modifies `~/.ssh`; SSH host keys and trust
policy stay in this project. Re-attestation replaces the host key on each boot.
Compute stops after a normal demo command; encrypted disk storage remains billable
until deleted. Do not delete that disk to stop compute.

## Custom Container route

Build the Nix image, publish it to GHCR, pin its OCI digest in
`tinfoil-config.yml`, and publish the measured release with the two Tinfoil
workflows. `publish-image.yml` can load the prebuilt Nix archive from a GitHub
release asset named `image.tar.gz`; this keeps image builds in Nix.

The current V3 path uses an exact local config and a pinned runtime manifest. Our
org returned `config deployments are not enabled for this organization`; enable
that with Tinfoil before trying this route. The older GitHub deployment path could
not load the runtime manifest pin. Do not use old demo tags as a workaround.

Once enabled: freeze `tinfoil-config.yml` into a private trusted copy, create with
`just deploy create --config <copy>`, then use `scripts/e2e.py` with the same
`--config` expectation. No unverified TLS fallback.

Creating/deploying requires an active Containers subscription and available host.
Stop the instance after testing to end compute use. Stop/restart clears this
minimal Container's memory-backed workspace and inference key. The Sandbox route
keeps its workspace on an encrypted disk; its inference key still needs to be
sent again after boot, through verified owner access.
The local test containers clean themselves up on success or failure.

The test uses `gpt-oss-120b`, low reasoning effort, at most 2,048 output tokens per
request and 16 inference requests per running instance. There is no metered
fan-out. Private traces stay under `.cache`; publishing a bug report requires a
separate review of its contents. This demo does not promise automatic PII removal.

## Test proof

Commands, assertions and limits: [test plan](docs/test-plan.md).

1. Verify the pinned release before sending credentials, prompts or commands.
2. Deny anonymous requests, another owner's signatures and replayed requests.
3. Seed a random file unknown to the model; require real tools to read it and
   write its reversed contents. Check the file from outside the agent.
4. Break the remote harness YAML. Confirm Tau fails while owner control remains
   reachable.
5. Let a second real Tau agent on this Mac inspect remote logs/files and fix the
   cause. It gets a command client, not a canned repair action.
6. Run a fresh hidden-file challenge in the repaired cloud harness.
7. Sandbox route: write random markers to the encrypted workspace and system
   overlay; stop/start the entire VM, re-attest, unlock with local keys, require
   a fresh SSH host key, check both files, and repeat the agent task.

The local recovery regression adds a real three-second delay to each remote
command. Every tool must return a terminal result; a background placeholder does
not count. `DARCY_BLOCKING_SHELL=1` opts this request-scoped adapter into foreground
execution. Upstream's default remains unchanged. All E2E paths use real models,
files and transport. Unit tests cover signatures and real HTTP body framing.

This proves a configuration recovery path. A dead VM, dead control process,
compromised supervisor or lost key needs a different recovery route. Network
egress is open for this experiment; arbitrary tools can send data out. Tight
network permissions and a separate credential boundary remain later work.
