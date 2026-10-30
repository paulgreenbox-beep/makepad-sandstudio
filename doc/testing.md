# Verification and parity plan

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
