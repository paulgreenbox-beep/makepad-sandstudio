# Makepad SandStudio (MSS)

The disabled [GitHub Issue to Codex integration](doc/codex-issue-runner.md) is proposed for owner review. Its model-free checks do not qualify native runner isolation or live inference.

Native multi-session GUI laboratory for Makepad applications and AI agents.

**Status: architecture scaffold. No runtime or GUI parity is claimed.**

## Requirements
- No containers or virtual machines (including Docker, WSL/WSLC, Hyper-V guests).
- Each tab maps to an independently owned application process, agent, test run, and evidence namespace.
- Do not take over the user's active Windows desktop for background tests.
- Target **identical public operation and verification coverage** to [Rust Makepad Toolkit](https://github.com/paulgreenbox-beep/rust-makepad-toolkit); never translate an unsupported operation into an apparent PASS.
- All state-changing actions require explicit authorization, stable identity and independent postcondition evidence.

## Components
| Component | Purpose |
|---|---|
| [MSS_Core](MSS_Core/README.md) | Session supervisor, lifecycle, ownership |
| [MSS_Remote](MSS_Remote/README.md) | Addressed app input and observations |
| [MSS_Render](MSS_Render/README.md) | Capture and transport frames |
| [MSS_SDK](MSS_SDK/README.md) | Application integration contract |
| [MSS_API](MSS_API/README.md) | Common typed tools boundary |
| [MSS_MCP](MSS_MCP/README.md) | MCP adapter for compatible clients |
| [MSS_Desktop](MSS_Desktop/README.md) | Makepad viewing interface |
| [MSS_Skills](MSS_Skills/README.md) | Agent guidance |

## Research baselines
- [Official Makepad](https://github.com/makepad/makepad), dev branch: app remote, host/child rendering, event paths.
- [Rust Makepad Toolkit](https://github.com/paulgreenbox-beep/rust-makepad-toolkit): source of public verification contracts, operations, runner and evidence.
- [Rust Makepad Tools 2](https://github.com/paulgreenbox-beep/rust-makepad-tools-2): experimental reference only; **do not** import its container/VM pathways.

## Next gates
1. Freeze exact dependency revisions and inventory all Toolkit public operations.
2. Prove Windows hosted-frame or Remote-frame visibility without physical focus.
3. Prove 2 independent child processes with isolated addressed input and cleanup.
4. Run the *same* Toolkit tests through the MSS adapter; record pass/fail/unsupported without weakening criteria.
5. Validate privilege, file/network, and failure containment boundaries.

See [architecture](doc/architecture.md), [maps](doc/maps.md), [compatibility](doc/compatibility.md), [testing](doc/testing.md), [security](SECURITY.md), and [agent instructions](AGENTS.md).

## Native Desktop prototype

The initial native Makepad Desktop binary is in [MSS_Desktop/src/main.rs](MSS_Desktop/src/main.rs), pinned to upstream Makepad dev commit `130be1d0318adcf69453d925342607466353152c`. It renders an illustrative three-slot session sidebar, status labels and a last-frame placeholder. **It is not connected to live sessions, render transfer or Toolkit tests.** To build in a prepared Rust environment: `cargo run -p mss-desktop` (native acceptance NOT_RUN).

MSS module declarations are in [SKLT](doc/dungeon.md); GLIF/GLYF projections deferred.
