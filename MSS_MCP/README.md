# MSS_MCP

## Responsibility

Expose MSS capabilities to Codex, Claude, Cline, OpenCode, and other compatible clients through standard MCP, while delegating all session, permission, test, render, and evidence logic to MSS_API.

## Planned rules

- Keep MCP tools thin: validate the MCP envelope, authenticate the client, resolve its authorized session, and call MSS_API.
- Do not duplicate lifecycle or automation business logic in provider-specific adapters.
- Never allow a caller to choose another agent's session by guessing an ID.
- Return explicit refusal, unknown outcome, postcondition failure, health failure, and evidence references.
- Do not return PASS from a command acknowledgement.

## Current state

The Rust library remains an architecture placeholder. `tools/` now publishes the
existing trusted-local Windows stdio connector and its launcher. This Python
connector delegates UI operations to the official Makepad Remote executable;
it does **not yet call MSS_API**. Its connection-local lifecycle and shared
registry are a transitional implementation, not proof of the planned Rust
authorization boundary or a production sandbox.

The source introduction is required because main did not contain this local
connector. It includes the existing build/shared/transfer helpers needed by the
router, without changing their GUI contracts. The following repair adds retained
process-handle identity, failed-launch reconciliation and frozen source identity.
No local application profiles, credentials, runtime executables or private
evidence are distributed. Existing Rust PRs remain independent review inputs.

See [setup, lifecycle and identity contract](../doc/mss-cleanup-source-identity.md)
for reproduction and explicit limitations. No installation or MCP reconnection
is performed by this source change.
