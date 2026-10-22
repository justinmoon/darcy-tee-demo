# Real demo checks

No fake models, tools, SSH or cloud API in the E2E tests. Unit tests exercise
signatures and HTTP framing separately. Passing a local test does not prove a
confidential cloud workload.

| Check | Command | Required result |
|---|---|---|
| Owner signatures and wire framing | `just test` | Anonymous, wrong-owner, expired and replayed requests fail; real signed length/chunked HTTP works; invalid framing fails |
| Static checks | `just lint` | Ruff passes |
| Actual local agent | `just local-e2e` | Real verified Tinfoil inference; unknown-file task succeeds; real broken YAML stops Tau while owner control survives |
| Slow two-agent recovery | `just local-recovery-e2e` | Second real local Tau fixes the first; every remote command takes at least three seconds; every tool returns a terminal result; fresh task succeeds |
| Attested Sandbox and persistence | `just sandbox-e2e` | Exact reviewed config; disk unlock; real cloud task; real failure; actual local Tau repair over pinned SSH; fresh cloud task; entire VM stop/start; new attested SSH host key; both disk markers survive; another real task passes |
| Playable prompt | `just sandbox-chat '…'` | Start, attest, unlock, real prompt/tools, stop compute |
| Minimal custom Container | `scripts/e2e.py --endpoint … --config …` | Exact workload check before credentials; wrong workload denied; owner checks; real task/failure/local repair/fresh task. Account flag required; currently blocked |

Each hidden-file test writes a fresh 48-character random value without putting it
in the prompt. The agent must read the input, run a program that reads and reverses
it, then inspect the output. The test reads the resulting file independently and
compares exact contents. A model's claim of success cannot pass this check.

The injected failure replaces the harness YAML with an actual unclosed sequence.
The owner API is a separate process from Tau. The repair agent gets a general
remote shell tool, logs and shipped defaults, with instructions to preserve the
inference route. There is no repair endpoint or script that chooses the fix.
The test accepts repair only after another independent agent task succeeds.

The Sandbox restart check writes random values to `/workspace` and
`/usr/local/share`, then stops the VM through the real lifecycle API. It waits for
stopped, starts it, waits for running, verifies again, unlocks with locally held
keys, requires a changed SSH host pin, and reads both values. Reinitialize the
inference key: gateway RAM intentionally does not survive restart.

Private prompts, files and tool traces stay under `.cache`. Public evidence uses
selected outcome fields only. No automatic claim that arbitrary logs are free of
personal data. The demo stops owned compute in `finally`; inspect status after a
host crash or forced kill. Retained encrypted disks still incur storage charges.

Not proved: malicious-tool containment from the supervisor, egress restrictions,
Monitor credential isolation, disk-key loss recovery, automatic PII removal, or
full compromise recovery. All tools and owner control share one cloud trust zone.
