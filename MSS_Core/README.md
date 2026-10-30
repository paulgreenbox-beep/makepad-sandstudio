# MSS_Core

## Responsibility

Own session IDs and generations, agent-to-session assignment, application and test-worker lifecycle, process identity, resource leases, and controlled close/cleanup. It is the only planned module allowed to start or stop MSS-owned child processes.

## Design contracts

- One session binds one authorized agent, one app process, one test context, and one evidence root.
- Store PID together with process-birth identity, executable path and digest, launch record, and ownership generation.
- Launch apps and test workers as separate processes with explicit arguments and session-specific directories.
- Never discover ownership by process name, title, guessed port, or stale PID.
- Unknown process state or failed cleanup is surfaced and quarantined; it is not silently reported closed.

## Current state

The crate implements a dependency-free, in-memory logical session registry.
It allocates nonzero agent/session IDs, stores session ownership and generation,
supports exact-handle lookup and selection, and removes an owned session on close.
The returned closed record is a logical result; no OS process or resource is
started, stopped or inspected.

IDs are monotonic and are not reused during one registry's lifetime. Exhaustion
returns `IdExhausted`; invalid input and refused owner/handle operations must not
consume a session ID or change the registry's selection or live records.

## Caller boundary

All callers sharing sessions must use the same authoritative registry. Opaque
IDs now include a process-local `RegistryId`; local `.get()` numbers alone may
still match in separate registries and must never be used as cache keys or
credentials. Namespaces are allocated atomically without reuse, including after
registry drop. `try_new()` reports namespace exhaustion; the compatible `new()`
constructor panics if that process-wide space is exhausted. Process restart is
a new identity domain. An `AgentId` is not an authenticated
external principal, and a `SessionHandle` is not a process/window identity.

`get_session`, `list_sessions` and `set_selected_session` are trusted-controller
operations. Agent-facing code must first authenticate its caller and use
`get_owned_session`, `select_owned_session` and `close_owned_session` with that
caller's registered identity. These methods compare logical ownership and
generation; they do not authenticate network, MCP or model clients.

Closing removes the live record. Reusing its handle then returns
`UnknownSession`; a mismatched generation on a live record returns
`StaleGeneration`. Closing a nonselected session preserves the existing
selection; closing the selected session clears it.

## Verification

The cheapest package check is `cargo test -p mss-core --lib --locked --offline`.
Run the workspace metadata/check/test gates separately and retain their actual
results. The reviewed Makepad dependency and lockfile remain unchanged; Core
itself uses only the Rust standard library.

At source `3ca93bbc94823651b0974d09e85cee1f37196251`, all twelve Core tests and
the locked/offline workspace checks passed. The other workspace members in
this tree have no tests; this is not a result for their separate implementation PRs.

See the [source-bound development record](../doc/cronica/20261030-core-pr1.json)
and [test scope](../doc/testing.md). Test execution verifies the declared logical
registry contracts only. Native process identity/lifecycle, GUI isolation,
parallel Makepad apps and full Toolkit parity remain `NOT_VERIFIED`.

The integration branch combines PR #1–#4 without rewriting their source history.
`SessionGeneration::new` constructs a nonzero data value for checked requests;
it grants no session authority. Existing public lookup/selection/close signatures
are preserved. See [integration verification](../doc/testing.md) for the new
combined-source evidence; the older Core record above remains historical.
