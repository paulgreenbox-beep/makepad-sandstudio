# MSS_Render — Native-frame viewing

Status: **DESIGN ONLY**.

## Responsibility
Captures child GPU output, tags frames by session/generation and publishes to API/Desktop.

## Boundary
Windows hosted/offscreen path is unproven; screenshots are not zero-copy GPU surfaces.

## Expected interfaces
Explicit session identity, generation, typed success/refusal, cancellation and evidence correlation. Concrete interfaces require design review and tests before exposure.

## Dependencies
See [architecture](../doc/architecture.md) and [Toolkit parity](../doc/compatibility.md). No external executable or Makepad source is bundled.
