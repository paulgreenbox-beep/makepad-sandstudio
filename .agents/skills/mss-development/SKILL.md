---
name: mss-development
description: "Develop, debug, test, review, or release Makepad SandStudio itself. Use for MSS MCP Python router changes, launcher ownership, Desktop source, build admission, native verification, licensing, and Windows packaging."
---

# Develop and verify Makepad SandStudio

Read [AGENTS.md](../../../AGENTS.md) and the relevant [security rules](../../../SECURITY.md). Use this skill for changes to MSS. To verify a guest's behavior, use AI Direct. Drive Desktop only for a test of Human View itself.

## Identify the source and the affected contract

1. Run `git status --short --branch`, `git rev-parse HEAD`, `git diff` and `git diff --cached`. Read the current PR head and base before work on a PR. Preserve unrelated changes and use a separate worktree when needed. Use the requested branch or the current stacked base. Review the final diff, record the exact tested SHA, and publish only the authorized branch or PR. Merge, force push and release publication require separate authorization.
2. Follow the actual process path in [architecture](../../../doc/architecture.md). Rust `MSS_Desktop/src` is the Human View binary. It starts `MSS_MCP/tools/mss_universal.py` over stdio. The router uses `mss_profiles.py`, `mss_builds.py`, `mss_process.py` and `mss_shared.py`. The pinned `Start-MakepadMcp.ps1` owns native guest launch and cleanup. Guest operations use the matching official `makepad-remote.exe`. The Rust library targets in Core, API, Remote, Render, SDK, MCP and Desktop remain scaffolds. Preserve existing SKLT object IDs.
3. Check [compatibility](../../../doc/compatibility.md) and `Cargo.lock`. The Desktop's Makepad pin and the guest's Makepad/Remote revisions are separate. Qualify the exact guest and client hashes. Preserve upstream and local runtime configuration unless the task explicitly authorizes changes.

## Build and select verification

Build from the repository root on native Windows x64. Set `MSS_TEST_PYTHON` to a trusted absolute Python 3.12+ and `MSS_PWSH_EXE` to a trusted absolute PowerShell 7.4+. `cargo build --workspace --release --locked` builds the Desktop. The MCP runtime runs as Python stdio with its five source modules and PowerShell launcher, so use the source or installed layout in [configuration](../../../CONFIGURATION.md).

After a Python router change, run the nearest `test_mss_*.py` tests under `MSS_MCP/tests`, then the complete Python suite. For shared routing, the focused pattern is `test_mss_shared_router.py`. Use the Rust stdio test if tool schemas, routing or protocol behavior changed.

```powershell
& $env:MSS_TEST_PYTHON -I -B -m unittest discover -s MSS_MCP/tests -p 'test_mss_*.py'
cargo test -p mss-mcp --test gui_tools --locked --offline
```

Use a fresh task TEMP/TMP for Windows fixtures. Run the retained-process PowerShell test for launcher or identity changes and the Rust workspace checks for affected Rust contracts or release verification. Use the exact [TESTING.md commands](../../../TESTING.md), including `Test-RetainedProcessIdentity.ps1` with `-Launcher` and `-EvidenceRoot`. Use `--offline` when the locked dependencies are cached.

## Qualify native changes and packaging

- For admission changes, check the baseline, candidate, allowed roots, pinned EXE, launch descriptor and runtime hashes. Use launcher `-ValidateOnly` for profile validation. Use an owned hidden app for live qualification. Registering, activating and rolling back are separate operations. Verify the candidate through semantic readback, native pixels and a task-specific postcondition before authorized activation.
- For native guest UI regressions, use the official `libs/makepad_test` and Rust `#[makepad_test]` in the matching guest source workspace when supported. Use admitted app/Remote binaries, explicit App ID and window, independent health and state readback, and verified owned cleanup. Keep uncertain mutations unresolved and preserve receipts. Do not retry a mutation after an unknown outcome.
- Save the exact source SHA or diff, command, exit code, app/Remote/runtime pins, identity, observations and cleanup under task-scoped `proof/`. Keep private data and credentials local. `PASS` requires evidence for the named check. Record assertion failures as `FAIL`, missing prerequisites as `BLOCKED`, and distinguish `NOT_RUN` and `NOT_VERIFIED`. See [verification contracts](../../../doc/testing.md).
- For a packaging or licensing task, inventory the exact EXE and MSI payload, embedded and external resources, dependency pins, licenses and notices. Check external Python/PowerShell requirements and capture bounded install/run/uninstall evidence. Keep clean-machine resource qualification separate. See [licensing](../../../LICENSE_AUDIT.md), [WiX](../../../packaging/windows/README.md) and [preview limitations](../../../KNOWN_LIMITATIONS.md).
