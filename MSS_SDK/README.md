# MSS_SDK — Application semantics

Status: **DESIGN ONLY**.

## Responsibility
Contract for live widget/focus/value/selection observation, action witnesses and app health.

## Boundary
The app integration producer must be authenticated and real, not a client-provided JSON echo.

## Expected interfaces
Explicit session identity, generation, typed success/refusal, cancellation and evidence correlation. Concrete interfaces require design review and tests before exposure.

## Dependencies
See [architecture](../doc/architecture.md) and [Toolkit parity](../doc/compatibility.md). No external executable or Makepad source is bundled.
