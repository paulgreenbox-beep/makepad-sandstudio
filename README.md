# Makepad SandStudio (MSS)

**Makepad SandStudio** is an architecture-stage project for a native, multi-session runtime, viewer, and automated testing environment for Makepad GUI applications.

| Field | Value |
|---|---|
| Project | Makepad SandStudio |
| Abbreviation | MSS |
| Language | Rust |
| License | MIT |
| Status | Initial Architecture / Development |
| Functional runtime | NOT_VERIFIED |
| Toolkit parity | Target acceptance criterion; NOT_VERIFIED |

## Purpose

MSS is intended to let independent AI agents work with separate Makepad applications at the same time. Each session is planned to own a distinct application process, control channel, test worker, render stream, state, and evidence directory. The native MSS desktop is planned as a tabbed workspace with session state on the left and the selected application's rendered view on the right.

The repository contains a seven-crate Rust workspace and a native Makepad Desktop shell. The Desktop renders an illustrative three-slot sidebar and a no-frame placeholder; it is not connected to sessions, app capture, tests or MSS_API. Core/API/Remote/Render compose an in-process logical registry, authorization/refusal gate and supplied-PNG cache, with historical test results bound to their exact source revisions. This does not implement app lifecycle, native command delivery, GPU capture, Toolkit execution, MCP transport or an OS sandbox. See the [PR #1–#4 integration report](doc/integration-pr1-4.md) for exact source, checks and limits.

## Non-negotiable constraints

- No Docker, containers, WSL, WSLC, Hyper-V, or virtual machines.
- Acceptance must not depend on an interactive Windows desktop.
- Address input to an owned Makepad process. Do not use global desktop input as an unproven fallback for semantic operations.
- Preserve the public Toolkit operations and .aiui.json scenarios. Never reduce its existing tests to make MSS pass.
- A command acknowledgement is not proof of its effect. Verify postconditions, application health, and evidence.
- An unknown mutation outcome stays unknown. Do not automatically replay it.
- Keep the official Makepad and both Toolkit repositories unchanged. Do not vendor a copy of the Makepad SDK.
- Label an unsupported or unproven claim NOT_VERIFIED.

See [architecture](doc/architecture.md), [testing and parity](doc/testing.md), [compatibility research](doc/compatibility.md), [developer rules](AGENTS.md), [security model](SECURITY.md), and the non-executable [Dungeon structure map](doc/dungeon.md).

## Planned modules

| Module | Responsibility | Current state |
|---|---|---|
| MSS_Core | Session, agent, process and resource ownership | Logical scoped registry TESTED; native lifecycle NOT_VERIFIED |
| MSS_Remote | Session-addressed Makepad commands and result checks | Admission/refusal baseline tested; latest Rust regressions NOT_RUN; transport NOT_IMPLEMENTED |
| MSS_Render | App-originated frames through API to Desktop | Supplied-PNG cache TESTED; native capture NOT_IMPLEMENTED |
| MSS_SDK | Typed app integration, widget state and telemetry | NOT_VERIFIED |
| MSS_MCP | Thin standard MCP adapters over the common API | NOT_VERIFIED |
| MSS_API | Shared session, app, GUI, test and evidence contract | Logical authorization/cancellation/refusal TESTED; executors NOT_IMPLEMENTED |
| MSS_Desktop | Native Makepad shell prototype; live session tabs and app viewer | Prototype only; runtime acceptance NOT_RUN |
| MSS_Skills | Agent instructions and safe usage examples | Documentation only |

## Source projects studied

The architecture is based on source inspection at the exact revisions listed in [compatibility research](doc/compatibility.md). Those revisions are research snapshots, not dependency pins or compatibility claims.

- [Official Makepad](https://github.com/makepad/makepad), including the dev branch's app Remote, hosted rendering paths, event dispatch, Cx, and GPU code.
- [Rust Makepad Toolkit](https://github.com/paulgreenbox-beep/rust-makepad-toolkit), including the public AI UI script/schema, runner, scheduler, verification economy, reliability checks, Windows automation, and evidence.
- [rust-makepad-tools-2](https://github.com/paulgreenbox-beep/rust-makepad-tools-2), including its experimental Remote adapter, native frame inspection, session binding, and desktop arbiter.

These projects serve different roles. Toolkit parity is the acceptance baseline. Official Makepad is an evolving application/runtime source. tools-2 contains experiments that are not accepted as production behavior.

## Build the workspace

Desktop and Render use the same exact Makepad Git revision; Render reuses already locked decoder crates without vendoring. SDK/MCP remain placeholders. Cargo must be able to resolve the lockfile's pinned sources:

~~~powershell
cargo metadata --format-version 1 --locked
cargo check --workspace --all-targets --locked
cargo test --workspace --all-targets --locked
~~~

These commands validate and compile the workspace only. They do not prove live sessions, app control, native frame capture, GUI acceptance, MCP behavior, test parity, or security isolation. The Desktop's illustrative content is not a runtime feature.

## Implementation sequence

1. Freeze the Toolkit public-operation and .aiui.json compatibility inventory.
2. Implement session and process ownership with exact process identity and bounded cleanup.
3. Add an app-specific Remote adapter, addressing every request to its owning session.
4. Prove semantic read/action contracts and preserve all Toolkit assertions and failure states.
5. Establish app-originated frame capture and native Desktop presentation for each supported platform; connect the existing UI shell only after the data path is proven.
6. Implement the shared API, then thin MCP adapters and complete the native Desktop.
7. Run the complete unchanged Toolkit regression suite and MSS multi-session, no-desktop, failure, evidence, and cleanup acceptance.

Every stage remains unaccepted until its required evidence is recorded.

## Existing Desktop shell

The source in [MSS_Desktop/src/main.rs](MSS_Desktop/src/main.rs) renders a visual shell using the Makepad revision pinned in [MSS_Desktop/Cargo.toml](MSS_Desktop/Cargo.toml). Its session entries and status are illustrative. It launches no child app and proves no real session, frame, or Toolkit operation.

## Independent product boundary and current follow-up

CWG is an external development-message service, not an MSS dependency or acceptance authority. MSS_MCP is the GUI API adapter, not CWG_MCP. Project GOAL definitions, Toolkit tests and native verification/evidence obligations stay in MSS. See [the separation decision](doc/cwg-separation.md) and [pinned scope policy](doc/plans/mss-scope-v2.json).

This combined source includes the #10 foundation, repaired #11 Unicode fixtures and the hardened #12 boundary checks. Historical TESTED labels above refer to the original integration receipt; **Rust build/test/format/Clippy at this combined HEAD remains NOT_RUN**. See [the current source follow-up](doc/product-source-followup.md) for provenance, checks and remaining gates. Do not reuse an earlier PASS for changed source.

The [scope checker](scripts/mss_scope.py) verifies the master-plan projection and can inspect tracked paths and Cargo declarations without executing Cargo. It refuses known CWG implementation imports while keeping all 112 Toolkit operations and native obligations. It is repository hygiene, not an OS sandbox or runtime qualification.
