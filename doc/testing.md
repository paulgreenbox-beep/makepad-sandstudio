# Verification contracts and preview evidence

[Run the source checks](../TESTING.md) · [Architecture](architecture.md) · [Security](../SECURITY.md)

## Verification layers

| Layer | What it establishes | Executable source or fixture |
| --- | --- | --- |
| Rust workspace | Formatting, compilation, static warnings, unit behavior and the stdio contract. | Cargo workspace, [Desktop input geometry](../MSS_Desktop/src/human_input.rs), [recording](../MSS_Desktop/src/recording.rs), [Codex receipt handling](../MSS_Desktop/src/codex_handoff.rs), [MCP stdio integration](../MSS_MCP/tests/gui_tools.rs). The Windows stdio test uses an empty-profile Python router. |
| Python policy and router | Build/configuration pins, action guards, selected guest/window, sharing, mutation order, user sequence, transfer, cleanup and startup identity. | [MSS_MCP/tests](../MSS_MCP/tests). In particular [user-sequence](../MSS_MCP/tests/test_mss_user_seq.py), [cleanup](../MSS_MCP/tests/test_mss_cleanup.py), [startup manifest](../MSS_MCP/tests/test_mss_startup_manifest.py), [resize](../MSS_MCP/tests/test_mss_resize.py) and [Human View](../MSS_MCP/tests/test_mss_human_view.py). |
| Retained process handle | Windows PID/birth/image binding and observation after rapid owned helper exit. | [PowerShell retained-handle fixture](../MSS_MCP/tests/Test-RetainedProcessIdentity.ps1). It exercises production launcher helpers. |
| Native guest and Desktop | Real hidden guest discovery, addressed observations, GPU PNG readback, resize/input where admitted, detach and graceful close. | Separate admitted exact Windows guest/Remote build, process receipt, tool trace, PNG hash and independent postcondition. |
| Guest UI regression | Actual Makepad app behavior under its pinned Makepad test crate. | Upstream `libs/makepad_test` and `#[makepad_test]` in the guest workspace when its Makepad revision supports them. [Guide at the tested work revision](https://github.com/makepad/makepad/blob/2271c0eb350cedd497c84373f17ad2b0b662cb72/libs/makepad_test/GUIDE.md) |
| Installation and Codex delivery | Separate MSI and opt-in real Codex executions. | Verify exact installed bytes and runtime paths or verify the approved handoff bytes and delivery receipt. The normal MSS source regressions are model-free. |

For a guest mutation, capture the prior state, perform the action once, check current app/process/window identity and read an independent postcondition. Use tree/wait, pixels or appropriate runtime state. Include app status and evidence when required by the contract. A transport ACK or screenshot alone does not establish unrelated state. `DISPATCHED` with `effect: NOT_VERIFIED` records dispatch only. Preserve the failure, elapsed time and last observation.

For resize/input checks, record the selected App ID, owned PID/birth, native window, requested/observed layout, DPI and pixel dimensions. Correlate frame hash and test action with the same app. When testing detach and cleanup, check that participant detach leaves the same owner PID alive and that explicit owner close eventually yields a matching exit receipt. Check neighboring instances independently in a multi-app test.

## Status vocabulary

| Status | Meaning |
| --- | --- |
| PASS | A named check completed against the exact fixture and retained matching evidence. |
| FAIL | A named check ran and recorded a failed result or assertion. |
| BLOCKED | A named prerequisite or environmental condition prevented completion. Include the blocker and the attempted command when available. |
| NOT_RUN | The check was not executed. |
| NOT_VERIFIED | Available source, design or lower-level evidence does not establish the claim. |

Keep execution status separate from operational states such as `OUTCOME_UNKNOWN`, `FAILED_CLOSED` and `CLEANUP_PENDING`. Never replay an uncertain mutation. Inspect its operation and safe readback, then document the outcome before deciding how to recover.

## Observed Windows preview evidence

The published source baseline is `04ea3c52d5777adcbd9e36f0bf18572836d1d120`. The following filenames identify retained local proof from the release qualification. These are evidence references, not files shipped in the source preview or MSI.

| Check | Result and scope | Local evidence under `proof/` |
| --- | --- | --- |
| Release source checks | Cargo fmt/check/test/Clippy and release build passed. Final Rust 12/12, Python 190/190, retained-handle 8/8. | `release-readiness/BUILD_RESULTS.md`, `release-readiness/TEST_RESULTS.md` |
| Native multi-app UI | Separate dev EXE exercised two hidden RudraOffice instances and a RudraOffice/AI CAD scenario including resize, input and recording. | `release-readiness/run-resize-20261113-093831144/results.json`, `release-readiness/run-recording-20261113-093831144/results.json` |
| Relocated release executable | Short-root native guest preview and detach passed. Longer paths reproduced Remote readiness failure while the launcher recorded owned exit. | `release-readiness/run-portable-short-03/results.json`, `release-readiness/path-matrix-7c3d1f4e/results.json` |
| RC2 and follow-up MSI | Exact RC2 setup/uninstall and empty profile behavior passed on the development host. A separate local prerequisite candidate passed missing-runtime rejection and 7/7 installed-path checks with standalone Python/PowerShell outside Codex cache. | `release-readiness/msi-rc2-aaef2629b3114fabb33ef5263aff4aab/result.json`, `release-readiness/CHECKS-A-B.md`, `release-readiness/run-installed-standalone-03/results.json` |
| Real recording handoff | Separate dev build retained a real Codex response bound to the approved export. Its original harness failed after receipt while parsing the displayed path. A readback of existing evidence verified delivery without a second send. | `codex-demonstration-handoff/REPORT.md` |
| Clean Windows host, portability, protected execution | Clean-host resource independence NOT_RUN. Public binary redistribution BLOCKED. OS sandbox, unattended dispatcher qualification and full Toolkit parity NOT_VERIFIED. | `release-readiness/check-b-license/REPORT.md` |

Keep the exact checkout commit or diff hash, command and exit code, runtime versions, artifact and executable hashes, process/window identity, cleanup and known limitations with each result. Use an independent allowed runtime observation for live claims. The old Toolkit inventory and Scheduler acceptance proposal are retained as [historical research](history/initial-architecture/testing.md).
