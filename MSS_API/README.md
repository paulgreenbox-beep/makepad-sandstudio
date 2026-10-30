# MSS_API

## Responsibility

Define the single backend contract used by MSS_Desktop, MSS_MCP, MSS_Remote, test workers, and MSS_Render for sessions, applications, GUI operations, tests, frames, evidence, and cleanup.

## Planned contract

The API owns authorization, session routing, capability checks, request correlation, idempotency declarations, failure taxonomy, and evidence linkage. It distinguishes a request accepted for dispatch from an independently observed result. Mutations with uncertain outcomes are never retried automatically.

Draft operation names and status envelopes are documented in doc/architecture.md. They are design proposals, not stable public APIs.

## Current state

No API schema, server, transport, permission layer, or business logic is implemented. API compatibility is NOT_VERIFIED.
