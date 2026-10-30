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

The published repository contains a seven-crate Rust workspace and a native Makepad Desktop shell. The Desktop currently renders an illustrative three-slot session sidebar and a no-frame placeholder; it is not connected to sessions, app capture, tests, or MSS_API. The other crates are architecture placeholders. No app lifecycle, addressed control, frame pipeline, test execution, MCP server, or sandbox is implemented or verified.

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
| MSS_Core | Session, agent, process and resource ownership | Architecture only |
| MSS_Remote | Session-addressed Makepad commands and result checks | NOT_VERIFIED |
| MSS_Render | App-originated frames through API to Desktop | NOT_VERIFIED |
| MSS_SDK | Typed app integration, widget state and telemetry | NOT_VERIFIED |
| MSS_MCP | Thin standard MCP adapters over the common API | NOT_VERIFIED |
| MSS_API | Shared session, app, GUI, test and evidence contract | NOT_VERIFIED |
| MSS_Desktop | Native Makepad shell prototype; live session tabs and app viewer | Prototype only; runtime acceptance NOT_RUN |
| MSS_Skills | Agent instructions and safe usage examples | Documentation only |

## Source projects studied

The architecture is based on source inspection at the exact revisions listed in [compatibility research](doc/compatibility.md). Those revisions are research snapshots, not dependency pins or compatibility claims.

- [Official Makepad](https://github.com/makepad/makepad), including the dev branch's app Remote, hosted rendering paths, event dispatch, Cx, and GPU code.
- [Rust Makepad Toolkit](https://github.com/paulgreenbox-beep/rust-makepad-toolkit), including the public AI UI script/schema, runner, scheduler, verification economy, reliability checks, Windows automation, and evidence.
- [rust-makepad-tools-2](https://github.com/paulgreenbox-beep/rust-makepad-tools-2), including its experimental Remote adapter, native frame inspection, session binding, and desktop arbiter.

These projects serve different roles. Toolkit parity is the acceptance baseline. Official Makepad is an evolving application/runtime source. tools-2 contains experiments that are not accepted as production behavior.

## Build the workspace

The Desktop package uses Makepad from an exact upstream Git revision recorded in its Cargo manifest. Other module crates are placeholders. Cargo must be able to resolve the pinned revision and registry dependencies:

~~~powershell
cargo metadata --no-deps --format-version 1
cargo check --workspace --all-targets
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
