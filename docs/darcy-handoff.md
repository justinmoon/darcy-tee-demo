# Findings for the Darcy desktop session

The original Darcy working tree stays untouched. This demo reuses its Tau pin,
CBOR adapter shape and outer-sandbox compatibility patch.

Changes worth carrying back:

- `prompt_override` names a template; it does not hold prompt text. Ship a named
  `.hbs` file under Tau's config `prompts/` directory. Literal text caused an
  actual `agent.prompt_failed` before inference.
- Surface `harness.notice` failures and `agent.prompt_failed` immediately. Waiting
  only for `agent.outer_turn_finished` turned that error into a timeout.
- Use buffered Python pipes for CBOR. Unbuffered pipe reads may return fewer bytes
  than a decoder requests.
- Include basic shell tools. The real agent tried `rev`, `awk` and `perl` before
  recovering with Python. The image now adds `rev` and `awk` explicitly.
- Keep Linux compilation on nixbuild.net; assemble the image with macOS
  `dockerTools` and explicit `architecture = "amd64"`. Downloading the assembled
  archive from the remote builder was much slower.
- Encrypted HTTP forwarding streams decrypted request bodies without a known
  length. A server that requires `Content-Length` rejects valid signed requests.
  `app/http_body.py` adds bounded chunk decoding; its socket test covers real
  signatures, both body formats, oversize bodies and ambiguous framing.

Read-only check at 20:09 local time: Darcy now ships the named `darcy` prompt
template. Its Python bridge still uses `bufsize=0`; the buffered-pipe finding
above remains worth carrying back. No files or processes in that session changed.

The real local test passed an unknown-file transformation, then broke Tau's YAML
and confirmed that the separate owner control API stayed reachable. That is local
execution with verified Tinfoil inference; cloud harness validation is separate.

The owner client, attestation, inference gateway and control API have no Hermes
dependency. Tau-specific launch/event code lives in `app/tau_agent.py`.

Further source checks and real recovery tests:

- Tau backgrounds shell calls after two seconds by default. An SSH call can take
  longer. A background placeholder must not count as command output or a completed
  repair. Include `wait`/`cancel` in roles that use this mode and keep the harness
  alive. Our short-lived RPC adapter instead opts into `DARCY_BLOCKING_SHELL=1`;
  the second hunk in `nix/tau-container.patch` changes only that opt-in mode. The
  desktop's long-lived harness may not need this choice.
- The regression adds a real three-second delay to every remote command and
  requires a terminal result for every tool call. It still uses real inference,
  signed HTTP and real files, without model or tool mocks.
- Tinfoil's current CLI requires a runtime manifest digest. Our org's legacy
  GitHub Container path tried to treat that digest as part of a release URL.
  The current local-config deployment path returned an explicit account gate:
  `config deployments are not enabled for this organization`.
- Managed Sandbox configs contain owner-specific values. Review the whole config
  against the pinned base template, allow only the intended fields, then pin its
  exact content reference. Blindly pinning the public base tag does not verify
  the personalized deployment.
- `TINFOIL_CONFIG` and `TINFOIL_KNOWN_CONFIGS` are separate paths. Set both to
  project-owned files. Back up the entire local Sandbox key directory, not only
  its SSH key: it also holds encrypted-volume keys.

Latest read-only check: original Darcy remains on `e9da7ed`; its bridge still
uses `bufsize=0`. No original files or processes changed.
