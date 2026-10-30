# Architecture (proposed, not implemented)

## Execution ownership
MSS Desktop is a viewer/client. MSS Core is the only session supervisor. The API owns cross-module typing and authorization boundary; MCP delegates to API and must not implement duplicate execution rules.

A logical tab is a persistent, owner-scoped **session**, not an OS window handle. It binds exactly one agent context, approved app instance, scoped test jobs, frame stream, action ledger and evidence namespace. Closing a tab, stopping an agent, closing the app, and deleting artifacts are separate explicitly authorized operations.

## Rendering choices to prove
A. Makepad hosted-child model feeding the parent renderer.
B. Process-local App Remote capture piped into a viewer (initial still frame, later incremental updates).
Neither native Windows hosted-frame parity nor fully offscreen GPU readback is assumed proven. Avoid naming a decoded screenshot a shared GPU surface. No window reparenting as security isolation.

## Testing compatibility
Reference source: rust-makepad-toolkit, especially prototypes/ai-ui-test-tool-auto-probe/operations.json and runner, scheduler and evidence verification. Prefer adapter/reuse over duplicating implementation.

## Invariants
- Session IDs, process identities, widget identities and evidence cannot cross namespaces.
- No implicit physical-input fallback.
- Unsupported semantics remain unsupported; postcondition and runtime observations are independent from command acknowledgment.
- Parallelism is real only after proving concurrent input and process lifecycle without stealing user focus.
- No containers or VMs.
