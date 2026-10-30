# Architecture

## Scope and state

MSS has a seven-crate workspace with an in-process logical integration of Core, API, Remote admission and Render storage. This integration preserves the PR #1-#4 source histories listed in [compatibility.md](compatibility.md). The Desktop shell remains illustrative and disconnected from those modules. No application/test-worker process is launched, no Makepad command is delivered and no native frame is acquired or displayed by this integration.

`IMPLEMENTED` below describes a source mechanism, not a passing test or accepted product feature. `TESTED` requires exact-source executed checks in [testing.md](testing.md) and its evidence; test declarations alone are insufficient. Native process ownership, authenticated app/client transport, complete Toolkit parity and full OS isolation remain `NOT_VERIFIED`. No dispatcher, GOAL executor or native-check-broker branch is included.

| Current source slice | Implemented boundary | Still absent |
|---|---|---|
| MSS_Core | Scoped logical IDs, registry ownership/generation checks, allocation/refusal rules, selection and logical close | App/agent OS identity, process launch, native lifecycle and cleanup |
| MSS_API | Shared logical authorization, four operation classes, auth-first unsupported/named dispatch and pre-dispatch cancellation | Execution backend, wire protocol/server, external caller authentication |
| MSS_Remote | Read/Focus/Text intent shape checks, exact API authorization and explicit NotDispatched | App transport, widget lookup/capabilities, actual input, replay/outcome ledger |
| MSS_Render | Owner-scoped supplied-frame admission/latest/cleanup, bounded cache/sequence fences and narrow decoded PNG validation | Renderer producer authenticity, capture, native frame transport, Desktop display |
| MSS_SDK / MSS_MCP | Module declarations only; integration NOT_IMPLEMENTED | Semantic producer, telemetry and MCP client/server bindings |
| MSS_Desktop | Makepad illustrative UI shell source | Live Core/API sessions and renderer-backed selected frame |
| MSS_Skills | Development instructions | No execution authority is granted by instructions |

## Responsibilities

This table states module ownership, including planned native responsibilities; the implemented subset is identified above.

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

### Current logical identities

`RegistryId` is allocated monotonically within one process. `AgentId` and `SessionId` include that namespace and a nonzero local number; equality and map keys preserve the full scoped ID. `.get()` exposes only the local number and is not a complete identity. Two independent registries may both allocate local number one without authorizing each other's handles. Namespace/session/agent allocation refuses exhaustion without wrap or identity reuse; `SessionRegistry::try_new` exposes namespace exhaustion while `new` can panic at that bound.

`SessionHandle` combines the scoped SessionId and nonzero generation. A new logical session currently starts at generation one; no process-rebind/generation-advance runtime is implemented. Supplying `SessionGeneration::new` is not authority to create a matching live session. Authorization checks the exact registry/session/generation and owner, and refuses stale, closed/unknown or foreign references without selecting another session.

These identities are process-local values, not random credentials, persistent global IDs or authenticated OS/network principals. Process restart begins a new identity domain. `RequestContext` is supplied by trusted in-process code; equality with a registered AgentId does not authenticate an external MCP/API caller. Native process-bound identities and protected serialized envelopes require later design and evidence.

Logical close removes only the exact owned record, marks the returned immutable `Session` value `Closed`, and clears selection only if that record was selected. Render may consume that closed-session value to release its matching cache/fence. This logical receipt proves neither app termination nor OS resource release; it is not a durable cross-process check receipt.

### Planned native ownership

The future runtime must bind each logical session to independently verified process and channel identities. The planned session owns:

1. One Makepad application process created by MSS_Core.
2. One test-worker process per active test job, separate from the app process.
3. One session-bound Remote channel and, when implemented, one render subscription.
4. A session-scoped project/artifact root, evidence log, and resource leases.

An agent may be an externally hosted process. MSS does not claim to create or isolate the agent's OS identity. MSS must reject a session reference that is unknown, stale, or owned by another agent; it must never fall back to a current/default session. Closing a tab, stopping an agent, stopping its app, and deleting artifacts are distinct operations with separate authorization and evidence.

The proposed process identity includes PID, process-birth identity, canonical executable path, executable digest, launch record, app build/source revision, session ID, and generation. A title, PID by itself, port scan, process name, or widget ID is not ownership proof. Processes are signalled only through retained handles after rechecking identity.

## Lifecycle

Current Rust `SessionState` contains only `Created` and `Closed`. They describe logical records; they do not imply a process is starting or running.

Proposed state transitions:

~~~text
CREATING -> STARTING -> READY -> ACTIVE -> CLOSING -> CLOSED
                    \-> FAILED       \-> CLEANUP_PENDING
ACTIVE -> OUTCOME_UNKNOWN -> VERIFYING -> ACTIVE or FAILED
Any live state -> OWNER_LOST -> RECOVERING or RESOURCE_QUARANTINED
~~~

These are draft states, not an API enum. A timeout after a mutating request is OUTCOME_UNKNOWN until an independent read or evidence observation resolves it. It must not be treated as a failed dispatch or automatically repeated. A session with uncertain ownership or resource release remains unresolved.

## Current API and Remote contracts

`Api::authorize` is the common logical authorization facade over Core. All four current classes (`Inspect`, `Capture`, `Input`, `Test`) remain unsupported for execution. Named class dispatch recognizes only `inspect`, `capture`, `input`, and `test`; it checks ownership before class parsing and returns `Unsupported` for unknown names or absent execution support. These names are not the Toolkit wire operation catalog and must not become a replacement `.aiui.json` schema.

`CancellationToken` is a shared monotonic in-process request flag. API cancellable admission authorizes the exact context first, then checks the flag and returns `Cancelled` before dispatch. A foreign/stale context cannot mask its error with a cancellation request. This does not cancel in-flight work, roll back an app mutation, resolve OUTCOME_UNKNOWN or prove process cleanup.

Remote uses the same API checks. Its AutomationId is only a requested string: nonblank, at most 256 UTF-8 bytes and without controls. Text is nonempty, at most 4096 UTF-8 bytes and without controls. Sequence must be nonzero. Every otherwise valid request returns `NotDispatched`; there is no transport, consumed sequence, completed action or automatic retry. The removed unused completion map is not described as replay protection. A future backend must add bounded pending/completed/unknown fencing before introducing side effects, plus independent target/capability and result checks. Pre-dispatch cancellation is available without claiming cancellation of app-side work.

## Planned execution API

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

This JSON is a future execution-response shape sketch only. No execution schema or server endpoint is implemented. The current Rust logical interfaces above must not be confused with that wire proposal. Outcome values and failure taxonomy need compatibility review against the Toolkit contract before stabilization. PASS belongs to a verified test report, never to transport acknowledgement.

## Addressed input and semantic capability

The preferred path delivers a semantic operation to the app process that owns the addressed widget and reads back the declared state. The app must expose stable semantic identifiers, supported operations, runtime health, and observations. A session adapter independently confirms the process and generation.

Global desktop input, focus changes, and SendInput affect a shared desktop resource and cannot satisfy the required non-interactive, independent-session acceptance by assumption. If a Toolkit operation only works through a physical fallback, retain that distinction and report the operation as unsupported or NOT_VERIFIED until equivalent behavior is independently proven. Do not replace the Toolkit operation or weaken its assertion.

## Test execution and Toolkit parity

Each submitted .aiui.json job receives a separate worker process, working directory, evidence root, and session identity. The target is the Toolkit public Script API, operation catalog, schema, runner, reliability checks, Scheduler contracts, verification economy, and evidence semantics at the pinned baseline. MSS may add adapters; it must not fork away the public test behavior or shrink the regression suite.

The current Toolkit source includes UI Automation semantic actions, physical-input fallbacks, runtime health and postconditions, declarative scripts, scheduler leases, retry classification, and evidence capture. Some Toolkit capabilities require a Windows interactive desktop or serialize access to desktop-global input. MSS must preserve those test requirements and result categories while separately proving the proposed Makepad addressed-input path. A scheduler concurrency result alone is not proof of concurrent app behavior.

The required operation-by-operation matrix and acceptance evidence are in [testing.md](testing.md).

## Current supplied-frame storage

`FrameStore` accepts caller-supplied encoded bytes and checks the API context against the frame's exact scoped SessionHandle. It uses full SessionId keys and `(SessionId, generation)` sequence watermarks; a duplicate/nonincreasing sequence is refused. Live `forget(api, context)` authorizes the owner and removes only matching pixels while retaining the replay watermark. `forget_closed(&Session)` accepts only Core's immutable `Closed` result and clears that exact incarnation's pixels/fence. Neither operation deletes files or stops processes. Closed-session cleanup must be explicitly called by the trusted owner path; no background lifecycle service is implied.

Host-selected `FrameLimits` bound one encoded frame, total retained encoded bytes, frame count, watermark count, dimensions and accepted reconstructed pixel bytes. Defaults are 64 retained frames, 256 watermarks, maximum 4096-by-4096 dimensions, 16 MiB accepted reconstructed pixels per validation and total encoded capacity of 64 times the per-frame cap. Zero/exhausted bounds refuse admission rather than silently evicting another session. Invalid input, stale sequence and capacity refusal precede mutation of the cached frame and watermark. The pixel guard is not an exact peak-RAM cap: encoded/filtered/decoded buffers have separate lifetimes. The reviewed upstream inflater's limit is best effort: stored blocks can overshoot, and literal paths can continue without that check, so temporary allocation also depends on the admitted encoded IDAT bytes. Literal expansion is bounded by those encoded bits, rather than by a fixed decoded-limit overhead. Trusted host limits must account for this behavior and decoder allocation overhead. These are local admission/cache bounds, not limits on an already allocated caller payload or a complete OS memory quota.

Admission validates CRC/chunk structure, declared dimensions against IHDR, bounded zlib data/checksum/filter rows and actual pixel decode. The supported profile is deliberately narrow: static, noninterlaced 8-bit grayscale/RGB/grayscale-alpha/RGBA with IHDR, consecutive IDAT and IEND. Palette, 16-bit, interlaced, ancillary-metadata and animated PNG are refused. This is not universal PNG compatibility or a blank-image/visual assertion. The encoder/decoder compatibility of real Makepad renderer output remains to be established before connecting a producer.

The decoded pixels are used to validate supplied bytes; retained encoded bytes can then be read by an authorized caller. Successful publication proves cache admission, not capture, freshness, renderer origin, app health, postconditions or Toolkit screenshot acceptance. The store has no verified process identity, renderer-reset generation, native subscription or Desktop presentation path.

## Planned native rendering boundary

The future Render adapter must bind frames to source session/process identity and renderer generation. Desktop must display the latest valid app-originated frame for the selected tab and reject stale/cross-session frames. Native delivery must identify capture mode and preserve app state.

The official Makepad app Remote's PNG readback is a source-inspected capture candidate. The Linux hosted Vulkan code's descriptor transfer is a platform-specific rendering mechanism, not a generic image-stream contract. Neither mechanism has been integrated or live-tested by MSS. See [compatibility.md](compatibility.md).

Two integration routes remain to be evaluated rather than assumed compatible: Makepad hosted-child rendering into a parent renderer, and app-process Remote capture delivered to an MSS viewer. Neither Windows hosted-frame parity nor fully offscreen GPU readback is established. A decoded screenshot must not be described as a shared GPU surface, and window reparenting is not an isolation boundary.

## Process and resource model

The host process runs MSS_API/Core and the native MSS_Desktop. Each target app and each active test execution gets its own process. No Docker or container, WSL/WSLC, Hyper-V, or VM participates in test or runtime execution. A future Windows supervisor may use a Job Object only for processes MSS created and recorded; ownership, descendant behavior, and termination must be proven before relying on it.

Resources are session-scoped by default. Truly global resources, if unavoidable, must be named and leased explicitly. A global desktop-input lease serializes the affected work and is not evidence of independent input. Lost workers with unresolved app/process state keep their resources quarantined until safe recovery.

## Planned implementation stages

1. **Compatibility oracle:** preserve the refreshed Toolkit operation/schema/test inventory, source revisions and status semantics; complete protected baseline execution remains ahead.
2. **Core ownership:** logical scoped registry/selection/close is implemented; add executable policy, process-birth identity, separate app/test processes, native resource ownership and verified shutdown.
3. **Remote contract:** retain the current auth-first refusal gate while adding an authenticated app transport for owned instances; verify discovery, semantic capabilities, replay/unknown outcomes, postconditions, health and no global input.
4. **SDK/telemetry:** define app-side semantic identity, typed state/action/health, capability negotiation, and bounded observations.
5. **Test execution:** run unchanged .aiui.json scripts through the public Toolkit runner/API and reproduce all failure, reporting, redaction, scheduling, retry, and cleanup contracts.
6. **Render:** retain bounded supplied-frame validation/cleanup while proving app-originated capture, producer authentication, transport, freshness, renderer/PNG compatibility, GPU/device behavior and Desktop display on every claimed platform.
7. **API, MCP, and Desktop:** add the one shared API first, thin standard MCP mappings second, and native Makepad tabbed UI last.
8. **Acceptance:** run complete unchanged Toolkit regression and operation conformance, then no-interactive-desktop and parallel-session tests, process/worker-loss tests, security boundary tests, and release evidence review.

No stage is accepted by design text, a static scan, a source revision link, or compilation alone.
