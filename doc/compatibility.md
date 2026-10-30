# Compatibility and source research

## How to read this file

The source SHAs below identify architecture/contract snapshots inspected on **2026-10-30**. The Toolkit main SHA was refreshed through GitHub during the PR #1-#4 integration and is still `0b01942f1a7d1c276f130c9db03146cb96c1718a`. Source snapshots are distinct from Cargo dependencies and do not imply functional compatibility. NOT_VERIFIED means there is no accepted cross-version proof.

## MSS integration inputs

The integration preserves these input histories through sequential non-fast-forward merges. They identify provenance, not the final tested integration source; exact test commands/results and that source belong in [testing.md](testing.md) and its development evidence.

| Input | Exact SHA | Dependency/history note |
|---|---|---|
| Main architecture baseline | `83ff50112fbbdc1cd2a43ccd2ac1650504394a67` | Existing seven-member workspace, Desktop pin and architecture rules. |
| PR #1 Core | `6998cef53077eab021f129e583d4979e2e70e297` | Preserves earlier Core history and its tested logical-registry record. |
| PR #2 API | `abcf43b08a13da5fbf70ba1b66ef16de512ebcb5` | Originally based on older Core `75e39070f0ac12ac314bff5e627da56675c55f99`; that ancestry alone does not prove compatibility with the new integration. |
| PR #3 Remote | `ad42653ac6e5b60c63262e48441a02607b0e5d83` | Based on API `abcf43...`; command admission, no transport. |
| PR #4 Render | `de2d32ee44cbab5882a5f5bf359db89e565cd26f` | Based on API `abcf43...`; supplied-frame storage, no native capture. |

Scoped IDs and the new logical contracts are in-process integration changes. They do not make these revisions a verified Makepad/Toolkit runtime stack. No dispatcher, GOAL-execution, PR #7 or PR #9 implementation is imported by this integration.

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

### Actual source inspected for the integration

The following files were read at the refreshed exact Toolkit SHA, rather than treating its README as implementation evidence. This is source research only; no Toolkit suite, UIA action, model request or native GUI canary was executed.

| Contract surface | Actual source and finding |
|---|---|
| Public scripts and schema | [script.rs](https://github.com/paulgreenbox-beep/rust-makepad-toolkit/blob/0b01942f1a7d1c276f130c9db03146cb96c1718a/prototypes/ai-ui-test-tool-auto-probe/src/script.rs), [version-1 schema](https://github.com/paulgreenbox-beep/rust-makepad-toolkit/blob/0b01942f1a7d1c276f130c9db03146cb96c1718a/prototypes/ai-ui-test-tool-auto-probe/ai-ui-test-script.schema.json): application/options/variables, setup/steps/teardown, cases, dependencies, expected errors, metadata and redaction. |
| Public transport and runner | [api.rs](https://github.com/paulgreenbox-beep/rust-makepad-toolkit/blob/0b01942f1a7d1c276f130c9db03146cb96c1718a/prototypes/ai-ui-test-tool-auto-probe/src/api.rs), [runner.rs](https://github.com/paulgreenbox-beep/rust-makepad-toolkit/blob/0b01942f1a7d1c276f130c9db03146cb96c1718a/prototypes/ai-ui-test-tool-auto-probe/src/runner.rs): generic Transport/AiUiClient, ordered script execution, cleanup failure reporting, input-lock handling, redaction and portable artifact references. |
| Operation distinctions | [operations.json](https://github.com/paulgreenbox-beep/rust-makepad-toolkit/blob/0b01942f1a7d1c276f130c9db03146cb96c1718a/prototypes/ai-ui-test-tool-auto-probe/operations.json): required arguments, target capabilities, mutation/idempotency and physical-input classification. `set_value` is nonphysical; `input`, `click`, `focus`, `select` and keyboard operations have physical-input declarations. These flags are not permission to invoke a prohibited desktop path. |
| Windows semantic/native mechanisms | [windows_backend.rs](https://github.com/paulgreenbox-beep/rust-makepad-toolkit/blob/0b01942f1a7d1c276f130c9db03146cb96c1718a/crates/toolkit-windows-automation/src/platform/windows_backend.rs): AutomationId retrieval, UIA InvokePattern, ValuePattern and SelectionItemPattern, plus separately reported SendInput paths. MSS has no adapter for these mechanisms. |
| Verified effects and health | [reliability.rs](https://github.com/paulgreenbox-beep/rust-makepad-toolkit/blob/0b01942f1a7d1c276f130c9db03146cb96c1718a/prototypes/ai-ui-test-tool-auto-probe/src/reliability.rs), [RELIABILITY.md](https://github.com/paulgreenbox-beep/rust-makepad-toolkit/blob/0b01942f1a7d1c276f130c9db03146cb96c1718a/prototypes/ai-ui-test-tool-auto-probe/RELIABILITY.md): value readback before/after settle, explicit click postcondition polling, process/runtime-error health and outcome classification. |
| Spatial contract | [spatial.rs](https://github.com/paulgreenbox-beep/rust-makepad-toolkit/blob/0b01942f1a7d1c276f130c9db03146cb96c1718a/prototypes/ai-ui-test-tool-auto-probe/src/spatial.rs): finite relative coordinates/regions, actionable bounds and DPI metadata. Frame dimensions are not equivalent to this target-resolution contract. |
| Evidence | [automation evidence.rs](https://github.com/paulgreenbox-beep/rust-makepad-toolkit/blob/0b01942f1a7d1c276f130c9db03146cb96c1718a/crates/toolkit-windows-automation/src/evidence.rs) records bounded ordered entries with request/result, execution method, resulting state and screenshot references. Reliability export/validation and runner artifact references are separate source paths; an encoded frame cache is not an evidence bundle. |

### Current source coverage versus Toolkit

`IMPLEMENTED` means the narrow MSS source mechanism exists. `TESTED` is reserved for an exact-source executed check recorded in [testing.md](testing.md); no TESTED claim is inferred here from a test function. `NOT_IMPLEMENTED` means the MSS mechanism is absent. `NOT_VERIFIED` means the broader behavior/parity has no accepted proof. All Toolkit execution/parity checks for this integration remain NOT_RUN/NOT_VERIFIED.

| Toolkit surface | Current narrow MSS coverage | End-to-end gap and status |
|---|---|---|
| Semantic UI/tree | Session/agent authorization is IMPLEMENTED logical policy, not a semantic tree. | App semantic producer, inspect/read adapter and widget states NOT_IMPLEMENTED; parity NOT_VERIFIED. |
| AutomationId | Remote target string shape/bounds validation is IMPLEMENTED. | Mapping to an actual app/widget identity and approved capability NOT_IMPLEMENTED; target resolution NOT_VERIFIED. |
| Invoke | No current native dispatch. | UIA/Makepad Invoke action and observed effect NOT_IMPLEMENTED; parity NOT_VERIFIED. |
| SetValue | Text intent validation exists and refuses dispatch. | Toolkit `set_value`, its distinct input mechanism and stable readback NOT_IMPLEMENTED; parity NOT_VERIFIED. |
| Selection | Scoped logical session selection exists; it is not widget selection. | Toolkit selection/toggle/choose state and operations NOT_IMPLEMENTED; parity NOT_VERIFIED. |
| Keyboard/mouse | No global input fallback is installed; Remote refusal is explicit. | Addressed app keyboard/pointer actions and equivalence proof NOT_IMPLEMENTED/NOT_VERIFIED. |
| Spatial | Encoded frame metadata is not a widget coordinate model. | Bounds/DPI/interactability/spatial target adapter NOT_IMPLEMENTED; parity NOT_VERIFIED. |
| RuntimeHealth | No app process is started or observed by these four logical modules. | Process liveness, stderr classification and app health NOT_IMPLEMENTED; parity NOT_VERIFIED. |
| Postconditions | Local authorization, stale sequence and invalid-frame errors are not GUI postconditions. | Waits, independent state readback, settle and failure evidence NOT_IMPLEMENTED; parity NOT_VERIFIED. |
| Evidence | Source-bound development checks can be recorded separately; supplied PNG storage is not renderer evidence. | Toolkit action/bundle exporter, provenance/redaction and validation adapter NOT_IMPLEMENTED; parity NOT_VERIFIED. |
| `.aiui.json` | Existing Toolkit schema/runner remains the unchanged acceptance target. | MSS schema/runner adapter and unchanged scenario execution NOT_IMPLEMENTED/NOT_RUN; full parity NOT_VERIFIED. |

## rust-makepad-tools-2 findings

The inspected tools-2 root workspace metadata records a Makepad revision of 71c9ddcbb9c01dd208f99621fdd71024a5d35c65. Its Remote adapter identifies itself as experimental and targets that pinned source. The adapter module states that it contains no Script runner, HTTP server, or Scheduler; process and transport ownership remain outside it.

The protocol code explicitly treats a remote reply as insufficient proof of effect and notes that the pinned protocol lacks keyboard focus and layout generation. The semantic contract is source-side composition only: its module states that it installs no app IPC/route and that native platform owners are unsupported until an authenticated producer and fixture policy exist. The native PNG inspector has bounded parsing and blank-image checks, but those tests do not prove live app capture. The desktop arbiter model is deterministic policy logic; its source says an arbiter is not a lock on human or foreign application input and requires a trusted native owner plus independent safe-point observations.

These mechanisms are useful research, not verified SandStudio features.

## Version and dependency policy for MSS

- Historical scaffold `b4556baae7b628e00322bb20bb9cc1d8221032fc` had seven workspace members and six dependency-free non-Desktop packages. This statement describes that historical tree, not the current integration.
- The current logical dependency edges are API -> Core, Remote -> API/Core, and Render -> API/Core. Render also has a dev-only Remote dependency for composition tests. These owned path edges do not establish transport/backend integration. Core is std-only; SDK/MCP remain dependency-free placeholders.
- [MSS_Desktop/Cargo.toml at the main input](https://github.com/paulgreenbox-beep/makepad-sandstudio/blob/83ff50112fbbdc1cd2a43ccd2ac1650504394a67/MSS_Desktop/Cargo.toml) pins makepad-widgets from https://github.com/makepad/makepad at `130be1d0318adcf69453d925342607466353152c`, version `2.0.0`, with `default-features = false`. The version is not the revision pin. No Makepad SDK source is copied or vendored into MSS.
- Render directly uses `makepad-zune-png` `0.5.2`, `makepad-zune-core` `0.5.1` and `makepad-zune-inflate` `0.2.54`, all from the same unchanged Makepad Git SHA `130be1d0318adcf69453d925342607466353152c`. Each declaration disables default features; inflate explicitly enables `zlib`. These packages were already resolved in the shared Desktop lockfile; adding direct consumers does not upgrade their source revisions. Cargo workspace feature unification can still enable features through another member, so these declarations alone do not prove globally disabled features.
- The pinned [PNG manifest](https://github.com/makepad/makepad/blob/130be1d0318adcf69453d925342607466353152c/libs/zune/zune-png/Cargo.toml), [core manifest](https://github.com/makepad/makepad/blob/130be1d0318adcf69453d925342607466353152c/libs/zune/zune-core/Cargo.toml) and [inflate manifest](https://github.com/makepad/makepad/blob/130be1d0318adcf69453d925342607466353152c/libs/zune/zune-inflate/Cargo.toml) were inspected. All declare `MIT OR Apache-2.0 OR Zlib`; PNG declares Rust `1.87.0`. This is that package's declared minimum, not an independently tested workspace MSRV. Render uses public `PngDecoder` header/dimensions/output-size/decode APIs and checksum-confirming `DeflateDecoder::decode_zlib` with requested limits; the best-effort inflater limit is not an exact peak-RAM boundary. No decoder source is copied into MSS. The narrow static-PNG profile and allocation limits are described in [architecture.md](architecture.md), and do not establish native-renderer or general Toolkit-image compatibility.
- The Makepad dev SHA is also the direct MSS_Desktop dependency pin; the Toolkit and tools-2 SHAs are research baselines, not MSS dependencies.
- The tools-2 Remote prototype's Makepad source target (71c9dd...) differs from inspected Makepad dev (130be1...). Cross-version compatibility is NOT_VERIFIED.
- The Toolkit local Makepad path has no recoverable exact commit in its public workspace manifest. Compatibility with either inspected Makepad revision is NOT_VERIFIED.
- Before adding a Makepad crate, record repository, exact commit SHA, license, feature flags, platform support, and an isolated compatibility test. Before upgrading, run the full unchanged Toolkit and MSS compatibility suites.
- A Makepad branch name, crate version, source tree resemblance, compile, or passing unrelated unit test is not a compatibility result.
