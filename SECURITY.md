# Security model

## Status

This document states design requirements, not implemented protections. MSS has no session broker, remote gateway, permission enforcement, file broker, process supervisor, or OS sandbox yet. All such controls are NOT_VERIFIED.

The PR #1–#4 integration adds in-process logical ownership/generation checks,
registry-scoped opaque IDs, pre-dispatch cancellation and bounded frame admission.
These are library contracts only. `RequestContext` is supplied by trusted calling
code; it does not authenticate an external agent. Core controller methods and
Closed Session cleanup receipts must not be exposed directly to untrusted clients.
Process-local namespace counters are not persistent, random session credentials.
The planned external permission enforcement above remains NOT_VERIFIED.

## Trust boundaries

- AI-agent requests, test scripts, application files, and app telemetry are untrusted input.
- MSS_API is planned as the policy boundary. MSS_Core is planned to own session identity and only the processes it starts.
- Makepad applications and their plugins run with the operating-system permissions of their process identity. A separate process per session prevents shared process memory; it does not grant a separate security principal or restrict that process's filesystem and network access.
- The Makepad Desktop prototype and structural SKLT files grant no authority and provide no security enforcement.
- MCP clients must not receive operating-system handles, raw unrestricted process controls, or authority to select another agent's session.
- Toolkit and Makepad source repositories are research inputs, not components whose source is copied into MSS.

## Session identity and permissions

Every request must resolve to an existing session and its authorized agent. A session binding is planned to include a random session ID, owner/agent ID, generation, app process ID and birth identity, canonical executable path and digest, launch record, and a session-scoped channel identity. A PID, window title, port number, widget ID, or agent-supplied session alias alone is insufficient.

Permissions should be capability-based and narrow: inspect, read, invoke, set value, input, capture, run a test, access an artifact directory, and close. The app must declare which semantic operations it supports. A caller must not gain a capability by supplying its own widget tree, window handle, process identity, or evidence path.

## Input channel isolation

Commands must carry a session binding and be delivered only to the app process launched for that session. The app must independently check the target and return an observable result. MSS must not inject into the user's foreground desktop or use desktop-global keyboard/mouse input as a fallback.

The inspected Makepad --remote implementation is a loopback HTTP surface in the application process. The inspected source and documentation do not establish per-agent authentication or an OS-enforced caller boundary for that endpoint. A random local port is not authentication. Until an authenticated gateway or OS-protected channel is proven, enabling this endpoint is only acceptable for a trusted, single-user development setup; multi-agent security remains NOT_VERIFIED.

**Makepad input isolation is not full OS isolation.** Separate app processes do not stop same-user processes from accessing files, network resources, credentials, or other OS objects allowed to that user. MSS must not claim a sandbox based on addressed input or separate processes.

## Files and evidence

- Resolve every path under a session-owned, configured project or artifact root. Reject traversal, unexpected reparse points/symlinks, device paths, and writes outside that root.
- Do not accept arbitrary executable paths, shell text, environment variables, or output directories from an agent without policy validation.
- Keep per-session logs, screenshots, reports, and temporary files distinct. Attach source/process/session identity, timestamps, content hashes, and generation IDs to evidence.
- Redact credentials and declared secrets before reports or MCP responses are persisted or returned.
- Preserve incomplete evidence and cleanup failures. Never label a missing or corrupt evidence bundle as a successful test.

## Network limits

The initial design is local-only. Do not expose app Remote ports or MSS_API on a network interface. Remote MCP/API access requires a separate design review for authentication, authorization, transport protection, origin policy, replay handling, rate limits, and audit logs. Applications may initiate their own network requests; MSS must not infer that local control limits app network access.

## Process and resource cleanup

Only the recorded owning session may request cleanup. Before signalling a process, re-check its PID, birth identity, executable identity, and ownership generation. Never kill by process name or port. Wait for normal exit, verify descendants/resources, and report anything still owned or uncertain. If ownership cannot be confirmed, preserve it as unresolved/quarantined and require explicit recovery.

On Windows, a Job Object may help control the lifetime of an MSS-owned process tree; it does not provide filesystem or network isolation. Forced containment is not a normal exit and must be reported separately. Physical desktop operations require a separate safety policy; if a reliable background equivalent is unavailable, return an explicit unsupported outcome.

No Docker or other container, WSL/WSLC, Hyper-V, or virtual machine is part of the proposed execution architecture. A future OS-level isolation feature would require its own threat model and acceptance evidence; it must not be inferred from this design.

Report security issues privately to the repository owner. Do not put credentials or private session traces in public issues.
