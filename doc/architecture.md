# Architecture

## Scope and state

MSS is an architecture seed with a seven-crate workspace and a GUI-only Makepad Desktop shell. The six non-Desktop libraries report NOT_IMPLEMENTED; the Desktop source renders illustrative session rows and a no-frame placeholder. There is no session runtime, process supervisor, app control channel, app frame pipeline, SDK producer, MCP server, or automated test execution. Module names and diagrams describe intended ownership only.

## Responsibilities

| Module | Owns | Must not own |
|---|---|---|
| MSS_Core | Session registry, agent binding, process identity, lifecycle, resource leases, close/cleanup | GUI command semantics, MCP provider logic, renderer pixels |
| MSS_Remote | One session's app transport, request correlation, capability and result checks | Session creation, agent policy, global desktop input |
| MSS_Render | App-originated frame acquisition, frame metadata, bounded delivery | Session authorization or UI actions |
| MSS_SDK | Typed app-side semantic IDs, declared operations, telemetry and health hooks | Makepad SDK copy, host process control |
| MSS_API | Shared authorization, stable operation envelope, orchestration and status/evidence contract | Provider-specific MCP behavior or app-private state |
| MSS_MCP | MCP transport and thin API adaptation | Business logic or alternate lifecycle rules |
| MSS_Desktop | Native tab/session UX and selected frame presentation | Direct process discovery, raw input injection, alternate API |
| MSS_Skills | Agent-facing instructions and safe examples | Hidden authorization bypass or privileged implementation |

## Ownership model

Each session has a fresh ID and generation and is assigned to one agent identity. It owns:

1. One Makepad application process created by MSS_Core.
2. One test-worker process per active test job, separate from the app process.
3. One session-bound Remote channel and, when implemented, one render subscription.
4. A session-scoped project/artifact root, evidence log, and resource leases.

An agent may be an externally hosted process. MSS does not claim to create or isolate the agent's OS identity. MSS must reject a session reference that is unknown, stale, or owned by another agent; it must never fall back to a current/default session. Closing a tab, stopping an agent, stopping its app, and deleting artifacts are distinct operations with separate authorization and evidence.

The proposed process identity includes PID, process-birth identity, canonical executable path, executable digest, launch record, app build/source revision, session ID, and generation. A title, PID by itself, port scan, process name, or widget ID is not ownership proof. Processes are signalled only through retained handles after rechecking identity.

## Lifecycle

Proposed state transitions:

~~~text
CREATING -> STARTING -> READY -> ACTIVE -> CLOSING -> CLOSED
                    \-> FAILED       \-> CLEANUP_PENDING
ACTIVE -> OUTCOME_UNKNOWN -> VERIFYING -> ACTIVE or FAILED
Any live state -> OWNER_LOST -> RECOVERING or RESOURCE_QUARANTINED
~~~

These are draft states, not an API enum. A timeout after a mutating request is OUTCOME_UNKNOWN until an independent read or evidence observation resolves it. It must not be treated as a failed dispatch or automatically repeated. A session with uncertain ownership or resource release remains unresolved.

## API contract proposal

MSS_API is the sole business-logic boundary for:

- session.create, session.list, session.inspect, session.close;
- application.launch, application.inspect, application.stop;
- ui.inspect, ui.read, ui.perform;
- test.submit, test.inspect, test.cancel;
- render.subscribe, render.latest;
- evidence.list, evidence.export;
- agent.bind, agent.unbind.

Names are illustrative, not stable APIs. Every request must be authorized, session-scoped, correlated, bounded, and checked against declared capabilities. A mutating request must include a request ID and an idempotency classification. OUTCOME_UNKNOWN cannot be automatically retried. Every completed mutation requires a distinct postcondition observation and runtime-health check.

A response should distinguish:

~~~json
{
  "request_id": "opaque-correlation-id",
  "session_id": "opaque-session-id",
  "generation": 1,
  "outcome": "OBSERVED",
  "application_healthy": true,
  "postcondition": "verified-condition",
  "evidence_refs": []
}
~~~

This JSON is a shape sketch only. No schema or endpoint is implemented. Outcome values and failure taxonomy need compatibility review against the Toolkit contract before stabilization. PASS belongs to a verified test report, never to transport acknowledgement.

## Addressed input and semantic capability

The preferred path delivers a semantic operation to the app process that owns the addressed widget and reads back the declared state. The app must expose stable semantic identifiers, supported operations, runtime health, and observations. A session adapter independently confirms the process and generation.

Global desktop input, focus changes, and SendInput affect a shared desktop resource and cannot satisfy the required non-interactive, independent-session acceptance by assumption. If a Toolkit operation only works through a physical fallback, retain that distinction and report the operation as unsupported or NOT_VERIFIED until equivalent behavior is independently proven. Do not replace the Toolkit operation or weaken its assertion.

## Test execution and Toolkit parity

Each submitted .aiui.json job receives a separate worker process, working directory, evidence root, and session identity. The target is the Toolkit public Script API, operation catalog, schema, runner, reliability checks, Scheduler contracts, verification economy, and evidence semantics at the pinned baseline. MSS may add adapters; it must not fork away the public test behavior or shrink the regression suite.

The current Toolkit source includes UI Automation semantic actions, physical-input fallbacks, runtime health and postconditions, declarative scripts, scheduler leases, retry classification, and evidence capture. Some Toolkit capabilities require a Windows interactive desktop or serialize access to desktop-global input. MSS must preserve those test requirements and result categories while separately proving the proposed Makepad addressed-input path. A scheduler concurrency result alone is not proof of concurrent app behavior.

The required operation-by-operation matrix and acceptance evidence are in [testing.md](testing.md).

## Rendering boundary

MSS_Render accepts frames only with source session/process identity and renderer generation. MSS_Desktop displays the latest valid frame for the selected tab; a stale or cross-session frame is rejected. Frame delivery must preserve native app state and identify capture mode and dimensions.

The official Makepad app Remote's PNG readback is a source-inspected capture candidate. The Linux hosted Vulkan code's descriptor transfer is a platform-specific rendering mechanism, not a generic image-stream contract. Neither mechanism has been integrated or live-tested by MSS. See [compatibility.md](compatibility.md).

Two integration routes remain to be evaluated rather than assumed compatible: Makepad hosted-child rendering into a parent renderer, and app-process Remote capture delivered to an MSS viewer. Neither Windows hosted-frame parity nor fully offscreen GPU readback is established. A decoded screenshot must not be described as a shared GPU surface, and window reparenting is not an isolation boundary.

## Process and resource model

The host process runs MSS_API/Core and the native MSS_Desktop. Each target app and each active test execution gets its own process. No Docker or container, WSL/WSLC, Hyper-V, or VM participates in test or runtime execution. A future Windows supervisor may use a Job Object only for processes MSS created and recorded; ownership, descendant behavior, and termination must be proven before relying on it.

Resources are session-scoped by default. Truly global resources, if unavoidable, must be named and leased explicitly. A global desktop-input lease serializes the affected work and is not evidence of independent input. Lost workers with unresolved app/process state keep their resources quarantined until safe recovery.

## Planned implementation stages

1. **Compatibility oracle:** freeze the Toolkit operation/schema/test inventory, source revisions, status semantics, and protected baseline suite.
2. **Core ownership:** implement session IDs, agent binding, executable policy, process-birth identity, separate app/test processes, resource ownership, and exact close behavior.
3. **Remote contract:** adapt app-originated Makepad Remote for owned process instances; verify discovery, auth boundary, semantic capabilities, postconditions, health, unknown outcomes, and no global input.
4. **SDK/telemetry:** define app-side semantic identity, typed state/action/health, capability negotiation, and bounded observations.
5. **Test execution:** run unchanged .aiui.json scripts through the public Toolkit runner/API and reproduce all failure, reporting, redaction, scheduling, retry, and cleanup contracts.
6. **Render:** prove per-session app-originated frame capture, transport, freshness, GPU/device behavior, and Desktop display on every claimed platform.
7. **API, MCP, and Desktop:** add the one shared API first, thin standard MCP mappings second, and native Makepad tabbed UI last.
8. **Acceptance:** run complete unchanged Toolkit regression and operation conformance, then no-interactive-desktop and parallel-session tests, process/worker-loss tests, security boundary tests, and release evidence review.

No stage is accepted by design text, a static scan, a source revision link, or compilation alone.
