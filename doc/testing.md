# Testing and Toolkit parity

## Status vocabulary

| Status | Meaning |
|---|---|
| PASS | The exact contract passed its required check with retained, attributable evidence. |
| FAIL | The contract was executed and an observed failure was recorded. |
| BLOCKED | An attempted check could not run because a named external/environment condition prevented it. Include the attempted command and blocker. |
| NOT_RUN | No execution evidence exists for this check. |
| NOT_VERIFIED | Source/design is insufficient to establish the contract, or the required implementation/evidence does not yet exist. |

BLOCKED and NOT_RUN are not passes. Missing, stale, ambiguous, or unowned evidence is not a pass. A transport acknowledgement, build, screenshot, or unit test cannot stand in for a required runtime postcondition.

## Acceptance baseline

The full Rust Makepad Toolkit public contract and regression suite is the target acceptance baseline. MSS must preserve the .aiui.json schema and scenarios, public Script API, operation catalog, runner semantics, reliability checks, Scheduler behavior, verification-economy policy, evidence, and failure classification. Do not shorten, delete, weaken, or replace Toolkit tests. Any baseline change is separate and requires explicit compatibility review.

The parity row stays NOT_VERIFIED until the complete unchanged baseline runs against MSS adapters and passes, including all environment-required scenarios. A source-level operation mapping or an MSS-only test suite cannot establish full parity.

## Summary acceptance matrix

| Toolkit/source contract | Required MSS behavior and proof | Status |
|---|---|---|
| Core logical registry, object `mss.core` | In-memory ownership/generation checks, allocation exhaustion and refusal nonmutation; source-bound unit results in the Core development record below | PASS |
| session.open, session.list, session.close | Per-agent ownership, no silent default-session fallback, identity-checked close, verified process/resource release | NOT_VERIFIED |
| App executable and literal argument launch | Separate process per app; trusted executable policy; exact PID/birth/path/digest evidence; no shell-string execution | NOT_VERIFIED |
| inspect_ui, inspect_semantic, read | Session-scoped semantic tree/state and independent readback, including stale/unknown target errors | NOT_VERIFIED |
| set_value, input, click, focus, toggle, choose, selection operations | Preserve each public semantic operation and its declared physical-input behavior; prove target and resulting state; no unproven fallback substitution | NOT_VERIFIED |
| UIA invoke/value actions and physical-input fallbacks | Preserve Toolkit execution-method reporting, input-lock/focus requirements, failure taxonomy, and desktop resource semantics | NOT_VERIFIED |
| Waits, assertions, postconditions, wait_until, wait_idle | Bounded polling; include last observation and app health; unmet condition is a failure, not timeout-as-success | NOT_VERIFIED |
| Runtime health and recognized Makepad/Script errors | Detect/report runtime failure even after the action endpoint acknowledged dispatch | NOT_VERIFIED |
| .aiui.json version 1 schema | Validate unchanged public schema; preserve application, options, variables, setup, steps, teardown, cases, tags, and metadata | NOT_VERIFIED |
| Script controls, dependencies, expected errors, extraction and redaction | Preserve public runner execution order and reports; test success and negative/error cases without schema simplification | NOT_VERIFIED |
| Scheduler queue, worker capability, leases, cancellation, application limits | Run independent worker processes; enforce eligibility and resource capacity; verify queue and leases drain | NOT_VERIFIED |
| Retry policy, timeout, worker loss and uncertain mutation | Preserve idempotency classifications; no automatic replay after uncertain mutation; verify recovery and quarantine | NOT_VERIFIED |
| Test report, screenshots, exported evidence, runtime timeline | Bind artifacts to exact script, session, app build, process identity, request, state, timestamps, and hashes; redact secrets | NOT_VERIFIED |
| Makepad --remote input and screenshot/readback | Verify endpoint belongs to launched app; validate per-agent authorization, operation parity, no desktop focus dependency, observed postconditions, and health | NOT_VERIFIED |
| Multiple agents and simultaneous Makepad apps | Prove N independent sessions with no crossed commands, state, frame, test job, evidence, or cleanup; show separate process identities | NOT_VERIFIED |
| Native app frames in MSS_Desktop | Capture and display current app-originated frame per session; prove freshness, renderer reset handling, and claimed GPU/platform support | NOT_VERIFIED |
| MCP integrations | Conformance for each supported client over one common MSS_API; verify caller/session authorization and failure semantics | NOT_VERIFIED |
| Graceful close and cleanup | Stop only owned workers/apps; verify process exit, handle/channel/resource release, and evidence flush; retain unresolved state | NOT_VERIFIED |
| Complete unchanged Toolkit regression suite | Record exact baseline revision and command; do not remove or weaken any existing test; retain full report and evidence | NOT_RUN |
| Cargo workspace metadata | cargo metadata --no-deps --format-version 1 for the seven-member published workspace | PASS |
| Cargo workspace check | cargo check --workspace --all-targets for the seven-member published workspace | PASS |

These two scaffold checks do not imply any runtime acceptance.

## Core logical registry verification

PR #1 keeps the registry's public interface and logical behavior, preserves its
seven original tests, and adds five boundary/refusal tests. At tested source
`3ca93bbc94823651b0974d09e85cee1f37196251`, all twelve Core tests passed. The
[append-only Core development record](cronica/20261030-core-pr1.json) identifies
the exact commands, source, result summaries and local raw-log digests.

| Contract in this slice | Observed Core proof | Limit |
|---|---|---|
| ID allocation | Nonzero, monotonic IDs; closed IDs are not reused; the last `u64` agent/session ID succeeds and further allocation refuses without wrap or loss of existing state | IDs are local to one registry, not authenticated external identities |
| Ownership and generation | Foreign owner, stale generation and closed handle are refused; the live records and existing selection remain unchanged | No process, window, widget or network caller is authenticated |
| Selection and logical close | Owned selection succeeds; closing a nonselected neighbor preserves the selection; closing the selected session clears it and removes only that record | Logical removal is not OS process shutdown or resource-cleanup evidence |
| Invalid creation | Invalid titles and an unregistered agent are refused without consuming a session ID or modifying existing state | This is the registry input contract, not a general application security boundary |

The cheapest first proof was the original seven-test Core suite after integrating
the current main baseline. The final path uses locked, offline package tests and
then workspace formatting/check/test gates; their actual outcomes are retained
in the development record rather than inferred from the presence of tests.

Workspace checks cover the seven members present in this PR's tree. The API,
Remote and Render implementations proposed in PR #2–#4 remain separate branches;
their combined execution is `NOT_RUN` here. Public Core compatibility with PR #2
was reviewed at source level only. Native process identity/lifecycle, GUI,
parallel Makepad sessions and full Toolkit parity remain `NOT_VERIFIED`.

## Public operation matrix

The following names are from the Toolkit operations catalog at the baseline SHA in compatibility.md. MSS must preserve every operation's arguments, capability, input method, result, error, postcondition, and evidence behavior. Grouping is for review only; it does not merge or replace contracts.

| Operation group | Toolkit public operations | Toolkit test/reference surface | Required MSS proof | Status |
|---|---|---|---|---|
| Session and discovery | session.open, session.list, session.close, acquire_input_lock, release_input_lock, inspect_ui, inspect_semantic, inspect_spatial_target, read, wait_for_automation_id | operations.json; reliability session/window identity; script runner session binding | Per-agent ownership, no default-session fallback, exact session/process identity, stale/foreign session rejection, verified close | NOT_VERIFIED |
| Semantic and widget actions | set_value, input, click, focus, double_click, right_click, toggle, choose, select, add_to_selection, remove_from_selection, clear_selection, select_many, select_range | operations.json; ai-ui-test-script.schema.json; reliability verified actions and postconditions; contract-negative.aiui.json | Preserve action meaning, input method, target capability, readback, expected errors, and postconditions. No unproven fallback substitution | NOT_VERIFIED |
| Pointer, keyboard, scroll, and drag | ensure_visible, scroll, scroll_to_start, scroll_to_end, move_pointer, pointer_down, pointer_up, click_relative, double_click_relative, right_click_relative, hover_relative, wheel_relative, drag, drag_to, drag_relative, select_region, hotkey, press, press_repeat, type_text, activate_window | operations.json; spatial-smoke.aiui.json; spatial-suite.aiui.json; scheduler Windows E2E examples | Preserve Toolkit operation semantics and physical-input labels. Prove addressed app behavior without an interactive desktop; retain unsupported operations explicitly | NOT_VERIFIED |
| Window controls | windows_set_window_bounds, inspect_window_interaction, windows_drag_title, windows_resize_frame, windows_double_click_title, windows_set_window_state | operations.json; reliability session/window identity; focused-window.aiui.json; windows-ui-composition.aiui.json | Verify exact owned window and resulting bounds/state; no focus of user desktop or foreign process | NOT_VERIFIED |
| Waits and assertions | wait_for_value, wait_for_state, wait_until, wait_visible, wait_hidden, wait_enabled, wait_disabled, wait_selected, wait_count, wait_idle, assert_visible, assert_interactable, assert_valid_bounds, assert_canvas_healthy, get_canvas_health | operations.json; reliability waits, assertions and compact trees; semantic-ui-composition.aiui.json; windows-ui-composition.aiui.json | Bounded polling, last observation, runtime health, exact assertion result, and failure on unmet condition | NOT_VERIFIED |
| Screenshots and visual assertions | screenshot_window, screenshot_element, capture_region, windows_capture_region, assert_not_blank, assert_region_changed, assert_region_unchanged, assert_similarity, compare_screenshot, get_makepad_visual_diagnostics | operations.json; async-observation-visual-failure.aiui.json; frozen-smoke and GPU-rendering profiles | Bind capture to app/session/generation, preserve dimensions and timing, verify visual predicates, and reject stale/cross-session frames | NOT_VERIFIED |
| Runtime and asynchronous task checks | get_runtime_health, get_runtime_stderr, get_task_state, wait_for_task, wait_for_task_state, wait_for_task_complete, assert_task_success, get_runtime_milestones, wait_for_runtime_milestone, assert_runtime_milestone, get_runtime_timeline | operations.json; RELIABILITY.md; async-observation-success.aiui.json; async-observation-task-fails.aiui.json; async-observation-missing-milestone.aiui.json | Preserve health, task, milestone, timeline and runtime-failure behavior; action acknowledgement alone never passes | NOT_VERIFIED |
| API and file postconditions | get_api_request_state, wait_for_api_state, wait_for_api_response, assert_api_success, assert_api_failure, wait_for_file, assert_file_exists, assert_file_not_exists, assert_file_size, assert_file_count, assert_file_hash, wait_for_file_stable | operations.json; async-observation-api-* and async-observation-file-* fixtures | Preserve timeout, HTTP, invalid-response, acceptance, file stability, path ownership, and content postconditions | NOT_VERIFIED |
| Logs, traces, cleanup and evidence | windows_export_evidence, windows_validate_evidence, get_application_logs, wait_for_log, assert_log_contains, assert_log_not_contains, assert_trace_event, assert_no_stale_window, assert_no_pending_task, assert_no_phantom_semantic_node | operations.json; Toolkit evidence.rs; RELIABILITY.md; error-collection.aiui.json; failure evidence fixtures | Bind reports and artifacts to script, source, session, process, request and state; retain redaction, cleanup failures and no-stale-resource assertions | NOT_VERIFIED |
| Script controls | repeat_until, wait_for_outcome, click_once_and_wait_for_outcome | public schema and runner; full-script-e2e.aiui.json; script-self-test.aiui.json; async observation fixtures | Preserve ordering, bounded repeats, dependencies, expected errors, extraction, teardown, status and report behavior | NOT_VERIFIED |

Toolkit distinguishes action mechanisms. Its catalog marks set_value as not requiring physical input, while input, click, focus, pointer, keyboard and scroll operations are marked physical-input operations. MSS must not silently implement input or click by calling set_value, or the reverse. Any changed mechanism needs its own measured semantic parity proof and remains NOT_VERIFIED until accepted.

## Toolkit verification and test inventory

| Baseline test surface | Source scenarios or checks to retain | MSS acceptance evidence | Status |
|---|---|---|---|
| Script contract and runner | Public schema, operation catalog, runner; basic-auto-probe, full-script-e2e, contract-negative, script-self-test, error-collection, spatial-smoke and spatial-suite examples | Same input scripts and reports through the public runner contract; all negative and teardown cases preserved | NOT_VERIFIED |
| Reliability | Session/window identity, semantic and physical action reporting, postconditions, runtime health, waits, assertions, compact trees in RELIABILITY.md | Complete unchanged reliability checks pass with session/process-bound observations | NOT_VERIFIED |
| Async and external observations | async-observation success, task failure, missing milestone, visual failure, API timeout/HTTP/invalid/not-accepted, missing/unstable file fixtures | All success and failure categories retain their original result and evidence | NOT_VERIFIED |
| Scheduler | Scheduler unit tests, queue/lease/resource and capability checks, worker-loss and mixed-environment verification code | Worker processes are independent; capacities and lease recovery hold; queue and leases drain; no duplicate uncertain mutation | NOT_VERIFIED |
| Windows and spatial E2E | Existing windows-e2e suite, focused-window, windows-ui-composition, physical-advanced and physical-spatial scenarios | Preserve all scenarios and assertions. MSS acceptance must not depend on interactive Windows desktop; replace no test and do not claim the prohibited physical path passed | NOT_VERIFIED |
| Semantic Makepad profile | focused-semantic, semantic-ui-composition and frozen-smoke scenarios | Same public scripts pass through the addressed app channel with readback, health and evidence | NOT_VERIFIED |
| Scheduler worker profile | focused-worker, workers-composition and frozen-smoke scenarios | Simultaneous independent sessions plus worker-loss, recovery, isolation and cleanup evidence | NOT_VERIFIED |
| GPU/render profiles | GPU-rendering and Makepad Linux profile scenarios | Real app-originated frame evidence for each claimed platform; no static or synthetic image acceptance | NOT_VERIFIED |
| Verification economy and CI | Toolkit verification policy, plans, result recording, verification-core tests and existing CI checks | Preserve policy, required gates and evidence; no skipped mandatory scope | NOT_VERIFIED |
| Full Toolkit regression baseline | All existing Toolkit tests and scenarios, unchanged at the pinned baseline | Full attributable report with no test deletion, skip, weakening, or replacement | NOT_RUN |

Some source profiles exercise containers, WSL/WSLC, or an interactive Windows desktop. MSS must not use those environments. Their source tests remain untouched; a claim depending on their execution is BLOCKED or NOT_VERIFIED under MSS constraints until an allowed equivalent proves the same contract. BLOCKED is recorded only after an actual attempted run.

## Scenario layers

1. **Static contract:** schema, API envelopes, operation mapping, dependency pins, permissions, and module boundaries.
2. **Pure Rust checks:** identity validation, state transitions, protocol parsing, result classification, and bounded evidence metadata.
3. **Owned-process checks:** launch/attach only to MSS-created processes; verify process-birth identity, per-session routing, crash and worker-loss behavior.
4. **Headless addressed-input checks:** semantic Makepad operations and readback with no interactive Windows desktop, foreground focus, or global input.
5. **Rendering checks:** real app-renderer frame capture and independent per-session delivery to the Desktop.
6. **Composition checks:** unchanged .aiui.json behavior through MCP/API, app process, Toolkit runner, postconditions, reports, redaction, and cleanup.
7. **Parallel and failure checks:** multiple independent agents/apps/test workers; transport loss, runtime failure, cancellation, unknown mutation outcome, quarantine, and cleanup.
8. **Acceptance run:** complete Toolkit regression baseline plus all required MSS composition/risk gates for the claimed platform.

Lower layers do not replace a required higher layer. Tests must not launch or depend on an interactive Windows desktop. If a contract cannot be exercised without that dependency, report the specific limitation and leave its MSS acceptance NOT_VERIFIED.

## Evidence required for a test PASS

- Exact MSS source commit and dependency revisions.
- Exact Toolkit baseline revision, scenario/script hash, test command and environment profile.
- Session, agent, process PID/birth identity, executable identity, and app build/source identity.
- Request/dispatch classification plus an independent postcondition and runtime-health observation.
- Evidence references and hashes for required reports, screenshots, traces, and cleanup.
- Proof of no cross-session routing or artifacts for parallel acceptance.

## Current results

On 2026-10-30, `cargo metadata --no-deps --format-version 1` and `cargo check --workspace --all-targets` passed for the seven-member workspace using the exact Makepad revision recorded in `Cargo.lock`. `cargo fmt --all -- --check` and `git diff --check` also passed. Cargo reported duplicate package names inside the pinned Makepad source tree and copied incremental-cache files where hard links were unavailable; these warnings did not prevent the check from completing.

No MSS behavioral test has run. The complete unchanged Toolkit regression suite remains NOT_RUN for this architecture-scaffold task. Runtime, GUI, multi-session, addressed-input, rendering, MCP, and cleanup acceptance remain NOT_VERIFIED as shown in the matrix above.
