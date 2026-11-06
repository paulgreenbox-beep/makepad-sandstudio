# Architecture maps

These diagrams describe the proposed architecture. They do not show implemented data paths. Every runtime edge remains NOT_VERIFIED until tested with owned processes and retained evidence.

## 1. Overall architecture

~~~mermaid
flowchart LR
  AgentA[Agent A] --> MCP[MSS MCP]
  AgentB[Agent B] --> MCP
  Desktop[MSS Desktop] <--> API[MSS API]
  MCP <--> API
  API --> Core[MSS Core]
  Core --> AppA[Makepad app process A]
  Core --> AppB[Makepad app process B]
  API --> WorkerA[Test worker A]
  API --> WorkerB[Test worker B]
  AppA <--> RemoteA[MSS Remote A]
  AppB <--> RemoteB[MSS Remote B]
  AppA --> RenderA[MSS Render A]
  AppB --> RenderB[MSS Render B]
  RenderA --> API
  RenderB --> API
  SDK[MSS SDK contract] -. opt-in app integration .-> AppA
  SDK -. opt-in app integration .-> AppB
  API --> Evidence[Session evidence store]
  Toolkit[Rust Makepad Toolkit baseline] -. verification contract .-> WorkerA
  Toolkit -. verification contract .-> WorkerB
~~~

## 2. Desktop to Makepad command path

~~~mermaid
sequenceDiagram
  participant D as MSS Desktop
  participant A as MSS API
  participant C as MSS Core
  participant R as MSS Remote
  participant P as Owned Makepad process
  participant E as Evidence
  D->>A: Request with selected session ID
  A->>C: Authorize agent and resolve owned process
  C-->>A: Session generation and process identity
  A->>R: Correlated, capability-checked command
  R->>P: Deliver on this app instance channel
  P-->>R: Dispatch acknowledgement
  R->>P: Independent readback and health request
  P-->>R: Observed state and runtime health
  R-->>A: Outcome classification, observation, health
  A->>E: Record request, postcondition, process and state identity
  A-->>D: Result plus evidence reference
~~~

## 3. Independent parallel sessions

~~~mermaid
flowchart TB
  API[MSS API and policy]
  API --> S1[Session 1]
  API --> S2[Session 2]
  API --> S3[Session N]
  S1 --> A1[Agent A]
  S1 --> P1[App process 1]
  S1 --> T1[Test worker 1]
  S1 --> C1[Control channel 1]
  S1 --> F1[Frame stream 1]
  S1 --> E1[Evidence root 1]
  S2 --> A2[Agent B]
  S2 --> P2[App process 2]
  S2 --> T2[Test worker 2]
  S2 --> C2[Control channel 2]
  S2 --> F2[Frame stream 2]
  S2 --> E2[Evidence root 2]
  S3 --> AN[Agent N]
  S3 --> PN[App process N]
  S3 --> TN[Test worker N]
  S3 --> CN[Control channel N]
  S3 --> FN[Frame stream N]
  S3 --> EN[Evidence root N]
~~~

Session-local IDs, process handles, control endpoints, artifact roots, and renderer generations must never be reused across sessions. Shared capacity limits may delay a job, but they must not merge ownership or state.

## 4. Agent, application, and test process ownership

~~~mermaid
flowchart LR
  Orchestrator[External agent orchestrator] --> Agent[One agent assigned to one session]
  Agent --> API[MSS API]
  API --> Core[MSS Core supervisor]
  Core -->|owns and verifies| App[Makepad app process]
  Core -->|owns and verifies| Test[Test worker process]
  App <--> Remote[Session-bound Remote adapter]
  Test -->|public Toolkit runner contract| Toolkit[Rust Makepad Toolkit]
  Test -->|test actions| API
  App -. separate process .-> Test
~~~

The agent may be externally managed. MSS owns only the application and test processes it starts and records.

## 5. Frame delivery

~~~mermaid
sequenceDiagram
  participant P as Makepad app renderer
  participant R as MSS Render adapter
  participant A as MSS API
  participant D as MSS Desktop
  P->>R: App-originated frame or supported readback
  R->>R: Check session, process, generation and sequence
  R->>A: Publish frame metadata and image bytes
  A-->>D: Selected session frame
  D->>D: Reject stale or mismatched session generation
~~~

The source-inspected PNG readback and Linux hosted swapchain paths are candidates only. This transfer path has not been implemented.

## 6. Verification through Toolkit

~~~mermaid
sequenceDiagram
  participant Caller as Agent or CI caller
  participant A as MSS API
  participant W as Session test worker
  participant K as Rust Makepad Toolkit public runner
  participant R as Session-bound Remote or UIA adapter
  participant P as Owned Makepad process
  participant V as Verifier and evidence recorder
  Caller->>A: Submit unchanged .aiui.json
  A->>W: Create isolated test process and artifact root
  W->>K: Execute public script contract
  K->>R: Inspect or perform declared operation
  R->>P: Address the exact app session
  P-->>R: Dispatch response and state
  R-->>K: Result, health and observation
  K->>V: Postcondition, runtime health, test report
  V->>V: Bind evidence to script, source and process identities
  V-->>A: PASS, FAIL, BLOCKED, NOT_RUN or NOT_VERIFIED
  A-->>Caller: Report and evidence references
~~~

An acknowledgement or a green compile cannot produce a PASS; the required postcondition and evidence must exist.

## 7. Close and cleanup

~~~mermaid
sequenceDiagram
  participant C as Agent or Desktop
  participant A as MSS API
  participant Core as MSS Core
  participant W as Test worker
  participant P as Owned app process
  participant R as Resource and evidence registry
  C->>A: Close exact session generation
  A->>Core: Verify requester and session owner
  Core->>W: Request graceful worker stop
  W-->>Core: Worker exit and cleanup result
  Core->>P: Request graceful app shutdown
  P-->>Core: App exit
  Core->>R: Verify leases, channels, frames and evidence flush
  R-->>Core: Released resources or unresolved items
  Core-->>A: Closed or cleanup-pending result
  A-->>C: Result with remaining owned identities
~~~

If identity or release cannot be verified, the session remains cleanup-pending or quarantined. MSS must not terminate an unrelated process to make the diagram appear complete.
