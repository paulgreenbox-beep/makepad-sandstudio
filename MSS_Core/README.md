# MSS_Core — Session supervisor

Status: **DESIGN ONLY**.

## Responsibility
Owns session lifecycle, agent binding, process identity, quotas and safe cleanup.

## Boundary
Must never adopt a foreign process by PID alone.

## Expected interfaces
Explicit session identity, generation, typed success/refusal, cancellation and evidence correlation. Concrete interfaces require design review and tests before exposure.

## Dependencies
See [architecture](../doc/architecture.md) and [Toolkit parity](../doc/compatibility.md). No external executable or Makepad source is bundled.
