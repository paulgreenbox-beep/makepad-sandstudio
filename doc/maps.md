# Windows preview maps

The arrows represent the current Windows implementation. [Architecture](architecture.md) · [Security](../SECURITY.md) · [Historical maps](history/initial-architecture/maps.md)

## Human View and AI Direct

```mermaid
flowchart LR
    Human["Human View · Rust Makepad Desktop"] -->|worker and local stdio| DesktopMcp["Desktop MSS MCP · Python"]
    Agent["Agent · AI Direct"] -->|local stdio| AgentMcp["Agent MSS MCP · Python"]
    DesktopMcp -->|admitted launches| Launcher["Pinned PowerShell launcher"]
    AgentMcp -->|admitted launches| Launcher
    DesktopMcp <-->|owner and participants| Store["Local SQLite share and operation store"]
    AgentMcp <-->|owner and participants| Store
    Launcher -->|hidden child| Guest["Admitted Makepad app"]
    Launcher <-->|stdio| Client["Official Makepad Remote MCP client"]
    Client <-->|discovery and token-checked loopback| Guest
    DesktopMcp <-->|explicit attachment uses its own native client| Client
    AgentMcp <-->|explicit attachment uses its own native client| Client
    DesktopMcp -->|validated PNG and metadata| Human
```

Separate instances use separate App IDs, owned process identities, launcher receipts and artifact roots. The diagram shows a representative process path. Sharing one App ID is optional and does not merge separate app instances.

## Identity, control and observation

```mermaid
sequenceDiagram
    participant Caller as Desktop worker or AI Direct
    participant MSS as MSS MCP connection
    participant Remote as Official Makepad Remote client
    participant App as Exact owned Makepad process/window
    Caller->>MSS: Request for an exact App ID and window
    MSS->>MSS: Check ownership or granted mode, identity and capability
    MSS->>MSS: Admit a mutation to the per-app queue if applicable
    MSS->>Remote: Dispatch addressed app command
    Remote->>App: Route to bound guest
    App-->>Remote: Native response
    Remote-->>MSS: Dispatch outcome
    MSS-->>Caller: Response and effect classification
    Caller->>MSS: Independent state, health or PNG readback
    MSS->>Remote: Query exact app and window
    Remote->>App: Observe guest
    App-->>Remote: Observed state or native pixels
    Remote-->>MSS: Observation
    MSS-->>Caller: Evidence bound to the guest
```

If a dispatched mutation becomes uncertain, the app may enter `OUTCOME_UNKNOWN`. Recovery uses explicit status and observation without resending the mutation.

## Detach and owned close

```mermaid
flowchart TD
    Action["User or agent selects a lifecycle action"] --> Kind{"Owner close or participant detach"}
    Kind -->|Detach| Detach["Cancel own queued requests and close own clients"]
    Detach --> Alive["Guest and owner stay active"]
    Kind -->|Close| Close["Check owner and retained process identity"]
    Close --> Quit["Request graceful Remote quit"]
    Quit --> Receipt{"Exit confirmed and receipt valid"}
    Receipt -->|Yes| Exited["CLOSED or FAILED_CLOSED according to launch outcome"]
    Receipt -->|No| Pending["CLEANUP_PENDING with evidence"]
```

## User-approved recording delivery

```mermaid
flowchart LR
    View["Human View"] --> Record["Session-bound recording"]
    Record --> Export["Review privacy options and export"]
    Export --> Approve{"User approves exact package"}
    Approve -->|Send| CLI["Installed Codex CLI · ephemeral analysis"]
    CLI --> Result["Trace, receipt and analysis"]
    CLI --> Unknown["BLOCKED or OUTCOME_UNKNOWN if unconfirmed"]
```

The handoff consumes saved data. Live application control uses the independent AI Direct path.
