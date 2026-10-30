# MSS_Skills — agent operating guidance

Status: design only. No tools or authorization are granted by these instructions.

Agents must read [AGENTS.md](../AGENTS.md), [SECURITY.md](../SECURITY.md) and [compatibility](../doc/compatibility.md). Always bind exact SessionId, owner, process incarnation, widget identity and evidence scope. After action request, independently verify state and application health; never infer success from an acknowledgment. Unknown results must be fenced without blind replay. Never operate another session or fall back to global desktop input.

Planned skills: session management, GUI inspection, verified input, frame capture, Toolkit scenario execution, diagnostics, cancellation, owned cleanup.
