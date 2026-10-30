# Security and trust boundaries

**This repository is an architectural scaffold, not a security-certified sandbox.** Multiple native processes in one Windows user session are **not** equivalent to VM/container isolation. Separate Makepad `Cx` and event streams alone do not isolate filesystem, network, GPU, clipboard, OS windows, or credentials.

## Threat model
An AI agent, app, plugin or test script may send unwanted input, access foreign resources, leak artifacts or leave processes alive. Assume tool arguments are untrusted.

## Controls required before mutable access
1. Explicit allowlist of approved executable bytes (hash), arguments, working directory and operator policies.
2. Independently obtained process birth/handle identity; bind owner + generation + SessionId; reject PID reuse and stale widget/window IDs.
3. Per-session command authentication/authorization. Prevent routing into another agent's session.
4. Require real focus, value, selection and postcondition witnesses where the operation promises them.
5. State-changing requests are serialized **within** a session; cross-session concurrency only when resources do not conflict.
6. Separate evidence roots, bounded artifact sizes, cancellation and cleanup. Never delete foreign files/processes.
7. Strict file path validation, filesystem permissions, network policy, secret redaction, auditable denial records.
8. Treat unknown post-dispatch results as uncertain; no automatic replay.
9. Clearly distinguish graceful app exit, agent disconnect, process containment and resource cleanup.
10. Physical desktop operations require a separate safety policy; absence of reliable background equivalent is an explicit unsupported outcome.

## Native boundaries
Windows Job Objects enable process lifetime control but do **not** provide filesystem/network isolation. Any stronger claims require independently validated OS security controls, compatible with the no-VM/no-container requirement.

Report security concerns privately to the repository owner. Do not include credentials or private session traces in issues.

## GitHub Issue worker

The [Issue dispatcher](doc/codex-issue-runner.md) is disabled by default. Its trusted control jobs and untrusted generation/check execution require separate accounts, physical runners and independently verified native Windows restrictions. An allowlisted label sender is not a grant of unrestricted host access. The action's Windows `unsafe` strategy omits privilege reduction; only the separately provisioned native elevated sandbox and reviewed host policy may provide the required boundary. Never enable the route based on labels, hashes or configuration alone. No model key reaches publication, generated code or check-broker environment. Raw model output is not published. Review and qualify the broker separately; it is not supplied by this PR.
