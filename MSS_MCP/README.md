# MSS_MCP — MCP protocol adapter

Status: **DESIGN ONLY**.

Connects Codex, Claude, Cline and OpenCode using common MCP tool contracts, with per-session permission and cancellation. No MCP server yet.

## Boundaries
Every call requires approved session/owner identity; no global input, implicit native fallback or fabricated PASS. See [architecture](../doc/architecture.md) and [parity](../doc/compatibility.md).
