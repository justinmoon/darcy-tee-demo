# Containers and Sandboxes

Source review: 2026-10-21. Sandbox access changed from disabled to enabled during
the demo build. Live Sandbox validation remains pending.

| | Containers | Sandboxes |
|---|---|---|
| Starting point | Our image and measured service config | Tinfoil's Ubuntu workspace template |
| Boundary | Confidential VM against the host/operator; container restrictions inside it | Confidential VM; template requests `cvm_admin: true` for full workspace administration |
| Tools | We ship Tau and the small tool set | Ubuntu, Docker, Nix tool pack, coding agents, native SSH |
| Files | Scratch memory for this demo; persistent volumes are an option | Owner-unlocked encrypted workspace; local CLI holds disk/owner keys |
| Network | Explicit egress policy; our demo permits internet access | Normally through Monitor; measured `NO_MONITOR=1` permits direct networking |
| Recovery | Our owner-signed API, separate from the Tau child | Attested owner SSH, storage unlock, and workspace lifecycle already supplied |
| Cost of adoption | Small surface; we write owner access and recovery | Less workspace plumbing; more services, permissions and beta dependencies |

Sandboxes is an agent workspace built on the confidential VM infrastructure,
not a wholly different privacy primitive. Its template asks for privileges that
ordinary Containers cannot request. Those privileges belong inside the user's
confidential VM, not on Tinfoil's physical host.

Monitor holds connector credentials, checks network permissions, and can verify
the upstream inference enclave. It can handle plaintext between those endpoints,
so its code, attestation and owner access form part of the trust boundary. A
separate Monitor could keep credentials away from compromised agent tools.
We could read the public Sandbox and CLI sources; the named Monitor repository
returned 404 without access. Full Monitor review remains open.

V3 attestation, encrypted volumes, attested keys/SSH and CLI verified connections
are beta. The inference API and attestation in general are not all labeled beta.
The account gate controls Sandbox access; it does not establish a public launch
date or support promise.

Decision: complete the small Containers demo first, then test Sandboxes before
building our own persistent workspace/SSH/credential service.
An owner recovery path helps when Tau fails. It cannot revive a dead confidential
VM or unlock a disk after loss of its keys; those need a restart/recovery design.

Sources:

- [Sandbox source](https://github.com/tinfoilsh/confidential-agent-sandbox/tree/721b2ae6a9eb0b68aad40074466478cb39a89c6e)
- [Sandbox CLI](https://github.com/tinfoilsh/tinfoil-cli/blob/c9eec5d35d4cfde8cd221d610ee4519ac32912a2/sandbox.go)
- [Runtime defaults and CVM administrator exception](https://docs.tinfoil.sh/containers/config-runtime)
- [V3 feature status](https://docs.tinfoil.sh/resources/feature-status)
- [Container quickstart](https://docs.tinfoil.sh/containers/quickstart)
