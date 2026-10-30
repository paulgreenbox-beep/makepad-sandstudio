# Verification and parity plan

## Issue dispatcher checks

Owner module: `mss.skills`; GOAL: `MSS-004`. The cheapest sufficient first proof is `node --test scripts/codex-issue/test/dispatcher.test.mjs`. It exercises authorization, routing, replay, source/evidence binding, protected paths, workflow security contracts, and the real collection stage with a failed-model fixture. It makes no model calls. YAML syntax and parsed job/permission contracts are checked separately by `node scripts/codex-issue/validate-workflow.mjs <installed-yaml-module>` using an existing YAML 1.2 parser. `node --check` validates helper syntax. Exact results belong in the source-bound receipt under `goals/events/`.

Rust sources are unchanged by this dispatcher task. Cargo, app runtime, native sandbox, broker execution, real Actions dispatch and Toolkit parity checks are NOT_RUN here; unit and workflow checks do not establish those contracts. Native isolation and live integration remain NOT_VERIFIED. See [setup and blockers](codex-issue-runner.md).

**No MSS native GUI or Toolkit parity tests have run at scaffold creation.**

## Baseline
Freeze a specific rust-makepad-toolkit revision, its public `operations.json`, `.aiui.json` schema, runner behavior, generator/coverage, Scheduler, verification policy and evidence formats. Record per-operation semantic obligations, resource requirements and PASS/FAIL rules in compatibility.md.

## Gates
1. Static module/API checks (workspace metadata, formatting, compile).
2. Contract tests: namespace isolation, stale identifiers, invalid actions, cancellation, no retry after unknown result.
3. Backend tests: real widget identity, focus/value, app state and health, GPU capture/readback.
4. Parallel session tests: two+ independent processes, simultaneous requests, no cross-session event delivery or human desktop capture.
5. Same public Toolkit scenarios via original runner contract; compare outcome and artifacts. Unsupported is not PASS.
6. Failure tests: crash, orphan child, busy GPU, blocked readback, lost agent, abrupt disconnect and bounded cleanup.
7. Native OS tests for physical Windows UIA/window gesture requirements; do not substitute Remote events.
8. Performance: memory, frame latency, launch and cleanup against an explicitly recorded host, without fabricated thresholds.

Record exact commit hashes, toolchain, OS, hardware and evidence provenance for each acceptance.
