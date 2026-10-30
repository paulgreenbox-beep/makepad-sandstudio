# MSS_Desktop — Native Makepad viewer

Status: **DESIGN ONLY**.

Proposed left session list and right selected native frame, with status, tests, logs and evidence. No renderer/UI is implemented yet.

## Boundaries
Every call requires approved session/owner identity; no global input, implicit native fallback or fabricated PASS. See [architecture](../doc/architecture.md) and [parity](../doc/compatibility.md).

## Current source prototype

See [main.rs](src/main.rs): native Makepad UI with three selectable **illustrative** session entries, left status sidebar and right explicit no-frame area. Uses pinned upstream `dev` revision `130be1d0318adcf69453d925342607466353152c`. No process management, native window hosting, screenshots, Toolkit execution or runtime acceptance is implemented.

Build in an approved Windows Makepad toolchain using `cargo run -p mss-desktop`; not yet executed or compiled in CI.
