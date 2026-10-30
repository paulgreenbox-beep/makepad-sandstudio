# MSS_Remote — Addressed input

Status: **DESIGN ONLY**.

## Responsibility
Transports commands to the exact owned Makepad app, rejects cross-session/stale widget addressing.

## Boundary
No implicit fallback to global Windows mouse/keyboard.

## Expected interfaces
Explicit session identity, generation, typed success/refusal, cancellation and evidence correlation. Concrete interfaces require design review and tests before exposure.

## Dependencies
See [architecture](../doc/architecture.md) and [Toolkit parity](../doc/compatibility.md). No external executable or Makepad source is bundled.
