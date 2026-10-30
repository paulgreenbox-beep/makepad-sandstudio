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

No MCP server, tools, transport, or client integration is implemented. The intended standard MCP version and transport profiles require review before implementation.
