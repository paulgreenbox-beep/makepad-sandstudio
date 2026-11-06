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

The Windows development connector exposes one stdio MCP named mss. It selects an admitted profile at runtime and forwards tools to official Makepad Remote through Start-MakepadMcp.ps1. The Rust library and its planned MSS_API integration remain scaffolds. See the [setup and testing guide](../doc/mss-universal-mcp.md).
