# MSS_API — Typed interface

Status: **DESIGN ONLY**.

Single stable façade over Core, Remote, Render and existing Toolkit verification. MCP forwards operations here; no runtime implementation yet.

## Boundaries
Every call requires approved session/owner identity; no global input, implicit native fallback or fabricated PASS. See [architecture](../doc/architecture.md) and [parity](../doc/compatibility.md).
