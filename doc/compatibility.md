# Compatibility and source research

## How to read this file

The commit SHAs below identify source snapshots inspected for architecture on **2026-10-30**. They are not Cargo dependencies, do not imply functional compatibility, and must be refreshed before implementation. NOT_VERIFIED means there is no accepted cross-version proof.

## Source revisions

| Project | Branch/revision inspected | Relevant source evidence | Result |
|---|---|---|---|
| Official Makepad | dev at 130be1d0318adcf69453d925342607466353152c | [Cx](https://github.com/makepad/makepad/blob/130be1d0318adcf69453d925342607466353152c/platform/src/cx.rs), [app Remote](https://github.com/makepad/makepad/blob/130be1d0318adcf69453d925342607466353152c/platform/src/remote.rs), [Remote activity](https://github.com/makepad/makepad/blob/130be1d0318adcf69453d925342607466353152c/platform/src/remote_activity.rs), [hosted relay](https://github.com/makepad/makepad/blob/130be1d0318adcf69453d925342607466353152c/platform/src/hosted_relay.rs), [hosted Vulkan](https://github.com/makepad/makepad/blob/130be1d0318adcf69453d925342607466353152c/platform/src/os/linux/hosted_gpu.rs), [HostedView](https://github.com/makepad/makepad/blob/130be1d0318adcf69453d925342607466353152c/widgets/core/src/hosted_view.rs), [Remote guide](https://github.com/makepad/makepad/blob/130be1d0318adcf69453d925342607466353152c/docs/agents/app-remote.md) | Source inspected; MSS integration and compatibility NOT_VERIFIED |
| Rust Makepad Toolkit | main at 0b01942f1a7d1c276f130c9db03146cb96c1718a | [workspace manifest](https://github.com/paulgreenbox-beep/rust-makepad-toolkit/blob/0b01942f1a7d1c276f130c9db03146cb96c1718a/Cargo.toml), [public script model](https://github.com/paulgreenbox-beep/rust-makepad-toolkit/blob/0b01942f1a7d1c276f130c9db03146cb96c1718a/prototypes/ai-ui-test-tool-auto-probe/src/script.rs), [runner](https://github.com/paulgreenbox-beep/rust-makepad-toolkit/blob/0b01942f1a7d1c276f130c9db03146cb96c1718a/prototypes/ai-ui-test-tool-auto-probe/src/runner.rs), [operations](https://github.com/paulgreenbox-beep/rust-makepad-toolkit/blob/0b01942f1a7d1c276f130c9db03146cb96c1718a/prototypes/ai-ui-test-tool-auto-probe/operations.json), [reliability](https://github.com/paulgreenbox-beep/rust-makepad-toolkit/blob/0b01942f1a7d1c276f130c9db03146cb96c1718a/prototypes/ai-ui-test-tool-auto-probe/RELIABILITY.md), [Scheduler model](https://github.com/paulgreenbox-beep/rust-makepad-toolkit/blob/0b01942f1a7d1c276f130c9db03146cb96c1718a/prototypes/ai-ui-test-tool-auto-probe/scheduler/src/model.rs) | Acceptance baseline target; exact local Makepad source pin NOT_VERIFIED |
| rust-makepad-tools-2 | main at b521a6c475348fb73494abdbe6adaf3c2c43320d | [workspace metadata](https://github.com/paulgreenbox-beep/rust-makepad-tools-2/blob/b521a6c475348fb73494abdbe6adaf3c2c43320d/Cargo.toml), [Remote adapter](https://github.com/paulgreenbox-beep/rust-makepad-tools-2/blob/b521a6c475348fb73494abdbe6adaf3c2c43320d/crates/toolkit-windows-automation/src/makepad_remote/mod.rs), [protocol guards](https://github.com/paulgreenbox-beep/rust-makepad-tools-2/blob/b521a6c475348fb73494abdbe6adaf3c2c43320d/crates/toolkit-windows-automation/src/makepad_remote/protocol.rs), [semantic prototype](https://github.com/paulgreenbox-beep/rust-makepad-tools-2/blob/b521a6c475348fb73494abdbe6adaf3c2c43320d/crates/toolkit-windows-automation/src/makepad_remote/semantic.rs), [desktop arbiter model](https://github.com/paulgreenbox-beep/rust-makepad-tools-2/blob/b521a6c475348fb73494abdbe6adaf3c2c43320d/crates/toolkit-windows-automation/src/desktop_arbiter/model.rs) | Experimental source only; not verified as production or parity |

## Makepad dev findings

At the inspected revision, platform/src/remote.rs describes an app-embedded --remote localhost HTTP control surface. Its request threads enqueue commands for the Makepad event loop; input is dispatched through the app's Studio-message event path, and screenshot grabs use app renderer readback before PNG encoding. The control queue is polled from the Cx event-loop boundary. This makes it a candidate for app-addressed control and capture.

Cx owns a per-instance RemoteActivity ledger. Native input advances a user sequence and tracks a quiet period/held state; a scoped flag distinguishes synchronous Remote-injected dispatch from native input. The Remote can use this activity to refuse or report interference. This is useful per-app conflict detection, not caller authentication, an inter-process owner check, or an OS isolation boundary.

This is not by itself a secure MSS multi-agent channel. The inspected source does not establish per-agent authorization, a session-owner check, a stable app-side semantic API equivalent to every Toolkit operation, or independent postcondition proof. A successful remote reply is not proof that a requested state was reached.

The hosted paths are distinct:

- widgets/core/src/hosted_view.rs selects full or tile presentation of one resident app. It routes input only to the active face while keeping its resident views alive; it does not host multiple independent application processes.
- platform/src/os/linux/hosted_gpu.rs handles Linux hosted Vulkan swapchain requests and file-descriptor transfer. This is platform-specific descriptor plumbing, not a generic MSS frame API or proof of a cross-platform image stream.
- platform/src/hosted_relay.rs relays selected child operations through a host. It is not an MSS session/agent authorization contract.

## Rust Makepad Toolkit findings

The inspected Toolkit root workspace uses Rust edition 2024 and declares makepad-widgets as a path dependency at .deps/makepad/widgets, with version 2.0.0. The manifest does not provide a Git revision for that local path. Therefore the exact Makepad commit used by the inspected Toolkit checkout cannot be established from that public manifest and is NOT_VERIFIED; do not substitute an assumed SHA.

The source includes a public .aiui.json script model and schema, operation catalog, generic transport-based runner, reliability layer, Windows UI Automation and physical-input paths, Scheduler workers/leases/resource limits/retry policies, verification profiles, and structured evidence. The Toolkit operation catalog marks set_value as not requiring physical input, while input, click, and focus are physical-input operations. MSS must preserve these distinctions; a set_value implementation cannot be silently substituted for input or click.

The Toolkit's default Scheduler resource pool gives the interactive Windows desktop capacity one and marks physical or interactive-desktop jobs as requiring that shared resource. This existing behavior is part of the baseline contract; MSS must not pretend it already provides parallel independent desktop input.

## rust-makepad-tools-2 findings

The inspected tools-2 root workspace metadata records a Makepad revision of 71c9ddcbb9c01dd208f99621fdd71024a5d35c65. Its Remote adapter identifies itself as experimental and targets that pinned source. The adapter module states that it contains no Script runner, HTTP server, or Scheduler; process and transport ownership remain outside it.

The protocol code explicitly treats a remote reply as insufficient proof of effect and notes that the pinned protocol lacks keyboard focus and layout generation. The semantic contract is source-side composition only: its module states that it installs no app IPC/route and that native platform owners are unsupported until an authenticated producer and fixture policy exist. The native PNG inspector has bounded parsing and blank-image checks, but those tests do not prove live app capture. The desktop arbiter model is deterministic policy logic; its source says an arbiter is not a lock on human or foreign application input and requires a trusted native owner plus independent safe-point observations.

These mechanisms are useful research, not verified SandStudio features.

## Version and dependency policy for MSS

- The published workspace baseline before this documentation integration is commit b4556baae7b628e00322bb20bb9cc1d8221032fc. It has seven workspace members. Of their manifests, only [MSS_Desktop/Cargo.toml at that commit](https://github.com/paulgreenbox-beep/makepad-sandstudio/blob/b4556baae7b628e00322bb20bb9cc1d8221032fc/MSS_Desktop/Cargo.toml) declares an external dependency: makepad-widgets from https://github.com/makepad/makepad at exact revision 130be1d0318adcf69453d925342607466353152c. The manifest's version 2.0.0 is not the revision pin.
- The other six package manifests declare no direct dependencies. No Makepad SDK source is copied or vendored into MSS.
- The Makepad dev SHA is also the direct MSS_Desktop dependency pin; the Toolkit and tools-2 SHAs are research baselines, not MSS dependencies.
- The tools-2 Remote prototype's Makepad source target (71c9dd...) differs from inspected Makepad dev (130be1...). Cross-version compatibility is NOT_VERIFIED.
- The Toolkit local Makepad path has no recoverable exact commit in its public workspace manifest. Compatibility with either inspected Makepad revision is NOT_VERIFIED.
- Before adding a Makepad crate, record repository, exact commit SHA, license, feature flags, platform support, and an isolated compatibility test. Before upgrading, run the full unchanged Toolkit and MSS compatibility suites.
- A Makepad branch name, crate version, source tree resemblance, compile, or passing unrelated unit test is not a compatibility result.
