# MSS_Core

## Responsibility

Own session IDs and generations, agent-to-session assignment, application and test-worker lifecycle, process identity, resource leases, and controlled close/cleanup. It is the only planned module allowed to start or stop MSS-owned child processes.

## Design contracts

- One session binds one authorized agent, one app process, one test context, and one evidence root.
- Store PID together with process-birth identity, executable path and digest, launch record, and ownership generation.
- Launch apps and test workers as separate processes with explicit arguments and session-specific directories.
- Never discover ownership by process name, title, guessed port, or stale PID.
- Unknown process state or failed cleanup is surfaced and quarantined; it is not silently reported closed.

## Current state

Architecture only. The Cargo crate contains no session manager or process implementation.
