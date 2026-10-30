# PR #1–#4 integration and verification

The four modules form a compatible, tested **in-process Rust foundation** on
branch `integration/mss-core-api-remote-render`, targeting `main`. No native
multi-session Makepad runtime, sandbox or full Toolkit acceptance is claimed.
The integration is for Draft review, with no automatic merge or source-PR closure.

## Exact inputs and history

| Input | Included SHA | Base at inspection |
|---|---|---|
| main | `83ff50112fbbdc1cd2a43ccd2ac1650504394a67` | Architecture baseline |
| [PR #1 Core](https://github.com/paulgreenbox-beep/makepad-sandstudio/pull/1) | `6998cef53077eab021f129e583d4979e2e70e297` | main `83ff501...` |
| [PR #2 API](https://github.com/paulgreenbox-beep/makepad-sandstudio/pull/2) | `abcf43b08a13da5fbf70ba1b66ef16de512ebcb5` | Older Core `75e39070f0ac12ac314bff5e627da56675c55f99` |
| [PR #3 Remote](https://github.com/paulgreenbox-beep/makepad-sandstudio/pull/3) | `ad42653ac6e5b60c63262e48441a02607b0e5d83` | API `abcf43b...` |
| [PR #4 Render](https://github.com/paulgreenbox-beep/makepad-sandstudio/pull/4) | `de2d32ee44cbab5882a5f5bf359db89e565cd26f` | API `abcf43b...` |

GitHub heads were refreshed before work and rechecked before publication. Remote
and Render are siblings, not a chain. Ordered non-fast-forward integration
commits are `3ab9f7a06ca3a4aa52042d95e13e6e4b83aa49be`,
`703dd3d6158a67e3bc73a17a8b4bf78fb46c683e`,
`be96f3ba020a8671f3d48d1ee7aa419ba6b26464` and
`bc5a73a1539d19e51220506377ebec96395672c4`. Every original head is an
ancestor; no original commit/test was discarded. Merges had no source conflict.
Follow-up compatibility fixes exist only in the integration branch.

Exact tested code commit: **`352e2c317de74c67e61fa38371a99be54c606c10`**.
The later published HEAD adds documentation and development evidence only;
its Rust sources, manifests, lockfile and fixtures match that tested commit.

## Corrected incompatibilities

| Finding | Integration change |
|---|---|
| Local numeric agent/session IDs can alias in independent registries | Opaque IDs retain a nonreused process-local RegistryId. Consumers key by full ID, not `.get()`. Checked allocator exhaustion preserves state. |
| No shared cancellation boundary | API exposes a shared one-way token and auth-first admission checks; Remote reuses them. No in-flight cancellation or rollback is claimed. |
| Unknown operation names could invite a future implicit default | Exact four-class parser and authorized named dispatch reject unknown names. This is not a Toolkit operation/schema replacement. |
| Remote completed-sequence map was never populated | Removed misleading dead state. Valid requests remain NotDispatched; real transport must introduce replay/outcome tracking before side effects. |
| Bare-handle frame deletion bypassed owner checks | Live removal now requires API/context. Cleanup after logical close requires Core's immutable Closed Session receipt and exact incarnation. |
| Pixel removal reset sequence history | A bounded watermark survives live removal and is released only by exact closed-session cleanup. |
| Cache could grow across arbitrary sessions | Explicit aggregate encoded-byte, frame-count and watermark-count admission bounds, with no silent eviction. |
| PNG signature admitted junk and trusted declared dimensions | Restricted static PNG chunk/CRC/zlib/filter/pixel validation, decoded-dimension check, and malformed-input nonmutation tests. |
| PR manifests were not reflected in shared lockfile | Lockfile updated for MSS edges only; all 126 external package entries remain unchanged. |

Public Core lookup/selection/close signatures remain. Additive APIs are scoped ID
accessors, `try_new`, checked generation construction, named/cancellable API
admission, Remote cancellable admission and explicit FrameLimits. The intentional
breaking Render call change is `forget(handle)` -> `forget(api, context)` returning
an explicit result; a bare handle can no longer erase another caller's frame.

The PNG decoder/core/inflater are direct consumers of already resolved Makepad
crates at unchanged `130be1d0318adcf69453d925342607466353152c`. Licenses,
features, version differences and source references are in
[compatibility.md](compatibility.md). No SDK is copied and no upstream source is
changed. Admitted pixel caps do not promise exact peak RAM; temporary decoder
allocation also depends on the encoded-input bound and upstream best-effort
limit. General hostile-process memory containment is outside this slice.

## Executed checks

Every final command below passed at the tested SHA, serially on Windows using
Rust/Cargo1.97.1 and two build jobs. The build target is local to the integration
checkout. The Desktop app was compiled but never launched.

| Command | Result | Exit | Tests |
|---|---|---|---|
| `cargo metadata --format-version 1 --locked --offline` | PASS | 0 | N/A |
| `cargo fmt --all -- --check` | PASS | 0 | N/A |
| `cargo check --workspace --all-targets --locked --offline` | PASS | 0 | N/A |
| `cargo test --workspace --all-targets --locked --offline` | PASS | 0 | 44 passed, 0 failed, 0 ignored |
| `cargo clippy --workspace --all-targets --locked --offline -- -D warnings` | PASS | 0 | N/A |
| `cargo build --workspace --locked --offline` | PASS | 0 | N/A |
| `cargo build --workspace --release --locked --offline` | PASS | 0 | N/A |
| `git diff --check` | PASS | 0 | N/A |

Core16 + API6 + Remote5 + Render9 + composition8 = **44**. All19 original tests
and their acceptance assertions remain; 25 tests were added. Eight public
composition cases cover all12 requested scenarios in [testing.md](testing.md).
The earlier focused four-package run passed the same44 cases, not another44
distinct tests. Other members have zero behavioral tests.

The initial offline full metadata attempt was BLOCKED by two uncached existing
lockfile entries (`hilog-sys0.1.9`, `smallvec1.16.4`). Authorized `--locked`
resolution filled only that cache; versions did not change. A local collector
then failed to summarize empty successful format output; after fixing only that
collector, all final commands passed on identical code. These intermediate
outcomes and duplicate-package Cargo warnings are retained rather than erased.

[Development evidence](cronica/20261030-integration-pr1-4.json) records exact
argv, source tree, start/end times, exit codes, individual tests and SHA256 of
local logs. Raw host paths/logs are not public artifacts. This is an unmanaged
Cronica development record, not a production broker or native check receipt.
All8 Mermaid blocks had a second manual syntax review; parser/render execution
is NOT_RUN because no parser was installed.

## Available and unavailable functions

| Capability | Current status | Acceptance limit |
|---|---|---|
| Logical IDs/agents/generations/owner checks and close | IMPLEMENTED, TESTED | One process; not external identity or Windows process isolation |
| API authorization, operation classification, unknown refusal | IMPLEMENTED, TESTED | No network/MCP server or executor |
| Pre-dispatch cancellation | IMPLEMENTED, TESTED | No running work/rollback/uncertain mutation resolution |
| Remote typed intent/bounds/refusal | IMPLEMENTED, TESTED | Actual transport, WidgetId resolution, semantic capability and replay ledger NOT_IMPLEMENTED |
| Supplied PNG admission/latest/sequence/cleanup | IMPLEMENTED, TESTED | Narrow static8-bit profile; no renderer authenticity or GPU capture |
| Real independent app/agent/test processes | NOT_IMPLEMENTED here; NOT_VERIFIED | Requires native identity/lifecycle/cleanup evidence |
| Native Makepad Remote and Desktop frame viewer | NOT_IMPLEMENTED here; NOT_VERIFIED | No global input fallback or user desktop dependency permitted |
| `.aiui.json`, semantic UI, Invoke/SetValue/selection/spatial | MSS adapters NOT_IMPLEMENTED; parity NOT_VERIFIED | Preserve unchanged Toolkit semantics and full test baseline |
| Runtime health, postconditions, action evidence | NOT_IMPLEMENTED here; NOT_VERIFIED | An acknowledgement/frame cannot substitute for observed effects |
| Full unchanged Toolkit suite | NOT_RUN; parity NOT_VERIFIED | Source audit is not execution acceptance |

## Remaining gates

1. Independent review/acceptance of this logical integration and explicit handling
   of the original Draft PRs; none is auto-closed or merged.
2. Authenticated external agent/app channels, capability resolution and real
   Remote dispatch with bounded pending/completed/unknown outcome tracking.
3. Native owned-process creation, app/test separation, cancellation/worker loss,
   runtime health and OS resource cleanup without user-desktop input.
4. App-originated capture, actual Makepad encoder/profile compatibility,
   renderer reset/freshness and native Desktop delivery on each claimed platform.
5. Unchanged Toolkit Script/runner/adapters, all positive/negative/teardown
   scenarios, evidence and full parity acceptance in allowed environments.

These are blockers for native/product acceptance, not failures of the completed
Rust integration gates. Event isolation and separate processes are not full OS
isolation. Dispatcher stays disabled; no model/API canary, automatic merge or
GOAL VERIFIED assignment was performed. PR #5/#7/#9 are unchanged.

## Files changed relative to the main input

```text
Cargo.lock
README.md
SECURITY.md
MSS_Core/README.md
MSS_Core/src/lib.rs
MSS_API/Cargo.toml
MSS_API/README.md
MSS_API/src/lib.rs
MSS_Remote/Cargo.toml
MSS_Remote/README.md
MSS_Remote/src/lib.rs
MSS_Render/Cargo.toml
MSS_Render/README.md
MSS_Render/src/lib.rs
MSS_Render/tests/integration.rs
MSS_Render/tests/fixtures/rgba1x1.png.bin
MSS_Render/tests/fixtures/overlong-scanline.zlib.bin
doc/architecture.md
doc/testing.md
doc/compatibility.md
doc/maps.md
doc/integration-pr1-4.md
doc/cronica/20261030-core-pr1.json
doc/cronica/20261030-integration-pr1-4.json
```

The historical Core evidence file is inherited unchanged from PR #1. SKLT files,
object_ids and external repositories remain unchanged. This branch does not
import the separate GOAL/dispatcher/native broker implementations.
