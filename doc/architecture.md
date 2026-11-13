# Windows preview architecture

MSS `0.1.0-preview.1` runs admitted external Makepad applications as independent hidden Windows processes. **Human View** is the tabbed Desktop workspace for people. **AI Direct** is the app-scoped path from a local MCP client to Makepad's app commands. Both paths use the same router policy and target an exact App ID. [Runtime maps](maps.md) · [Setup](../CONFIGURATION.md)

## What runs

| Component | Status | Implementation in this preview |
| --- | --- | --- |
| Desktop Human View | IMPLEMENTED | Rust Makepad UI, background worker and local stdio client. Tabs launch or attach, display guest pixels and expose profile-appropriate controls. [UI](../MSS_Desktop/src/main.rs) · [Client](../MSS_Desktop/src/remote_client.rs) |
| MSS MCP | IMPLEMENTED | Python stdlib router, input validation, explicit app/window selection, capabilities, observations and policy. Rust `mss-mcp` is a scaffold with a separate Windows stdio regression test for the Python server. [Router](../MSS_MCP/tools/mss_universal.py) · [Test](../MSS_MCP/tests/gui_tools.rs) |
| Profile/build admission | IMPLEMENTED | A local operator catalog, baseline build or explicitly admitted candidate, optional pinned launch configuration. Activation and rollback change future launches. [Profiles](../MSS_MCP/tools/mss_profiles.py) · [Builds](../MSS_MCP/tools/mss_builds.py) |
| Process launch/cleanup | IMPLEMENTED | PowerShell validates pins, starts an owned app and the official Remote client, retains process identity and writes the session receipt. Unresolved cleanup remains pending. [Launcher](../MSS_MCP/tools/Start-MakepadMcp.ps1) · [Identity](../MSS_MCP/tools/mss_process.py) |
| Sharing and mutation sequence | IMPLEMENTED | A per-data-root SQLite store tracks owners, explicit read/control participants and bounded per-app mutation ordering. Queue cancellation applies before dispatch. [Store](../MSS_MCP/tools/mss_shared.py) |
| Native capture and addressed controls | PARTIAL | The guest renders and returns native PNG pixels. Human View resizes and forwards input for admitted compatible profiles and geometry. Read-only guests can supply a preview. Acknowledgement and effect are separate. [Client](../MSS_Desktop/src/remote_client.rs) · [Input geometry](../MSS_Desktop/src/human_input.rs) |
| Recording and Codex analysis | PARTIAL | Desktop records selected Human View actions and evidence, exports a reviewed subset and can deliver it to an installed authenticated Codex CLI. Live model delivery has bounded dev-build evidence. [Recording](../MSS_Desktop/src/recording.rs) · [Handoff](../MSS_Desktop/src/codex_handoff.rs) |
| Rust Core/API/Remote/Render/SDK | SCAFFOLD | Workspace members retain structural boundaries. The current running process chain goes through the Python router and official Makepad client. [Workspace](../Cargo.toml) |
| Protected execution or additional platform qualification | PLANNED | Separate threat model, implementation and verification required. [Security](../SECURITY.md) |

`DEPRECATED` applies to the historical Toolkit-first workflow and old HTTP guest transport as guidance for this preview. [Initial design archive](history/initial-architecture/README.md) · [Compatibility](compatibility.md)

## Human View and AI Direct

Desktop starts its own local MSS MCP stdio connection through the Python interpreter. Its worker queues tab operations and binds replies to the active session and frame. Launching makes Desktop's connection the owner. To view an instance owned by a different connection, the owner shares it and the participant attaches using the exact App ID and the same data root and Windows session. An attached tab can detach without exiting the guest. The owning connection closes the process.

An agent starts from the MSS MCP catalog and uses `mss_ui_tree`, `mss_ui_find`, `mss_status`, `mss_grab` and admitted tools for the specific App ID. It gets node and window IDs from that app's latest observations. The native semantic window form differs from numeric window IDs used for capture and pointer operations. See exact schema in `tools/list`. Agent tools operate on the guest independently of Desktop tab selection. [Agent rules](../AGENTS.md) · [MCP guide](../MSS_MCP/README.md)

For a launch, the router selects a hash-pinned profile and EXE, materializes per-instance work/session directories and starts the pinned launcher with explicit arguments. The launcher sets hidden mode and runs the guest with `--remote`. After process identity checks, it reads the discovery file in a create-only directory under the current Windows user profile, separate from per-instance evidence. The guest and official Remote clients receive the same TEMP and TMP. The launcher validates the app, PID, loopback socket and discovery token, then requires official status to identify the owned window. It then brokers stdio to `makepad-remote mcp <pid>`. The router independently checks the launcher receipt, native status and Windows process identity. Attachments use the launcher receipt to bind their native MCP client to the same guest and discovery directory. Cleanup removes the launch-owned directory after confirmed app and launcher-owned Remote client exit. [Launcher](../MSS_MCP/tools/Start-MakepadMcp.ps1) · [Router](../MSS_MCP/tools/mss_universal.py)

## Frame and input flow

1. The guest's Makepad renderer supplies an addressed PNG via its native Remote capture. MSS binds the result to the App ID and window and checks the owned artifact and hash. Desktop checks the file/hash, decodes it and presents the texture in the selected tab.
2. Resize uses an explicit requested size in layout points. MSS checks the native reply against independent status, window geometry, DPI and matching pixel dimensions. A selected preview can refresh from an owned frame without granting input.
3. Human View translates pointer coordinates from the currently drawn image into guest layout points and checks the selected tab, window and frame geometry. It uses MSS MCP addressed tools for pointer, scroll, keyboard and text. Profile and sharing policy still apply. After dispatch, use a fresh tree, observed condition or matching pixels to substantiate the result.
4. Raw input may report `DISPATCHED` with effect `NOT_VERIFIED`. Explicit user-sequence guards refuse stale or unavailable activity before dispatch; Makepad's own guard still applies at dispatch. A lost or ambiguous mutation result stays `OUTCOME_UNKNOWN`. Stop mutations, inspect the operation and use a safe readback before recovery. [Input preflight](mss-user-sequence-preflight.md)

Frame delivery is bounded PNG capture and decode. Shared GPU surface transport, global desktop input and OS sandboxing are outside the verified preview. [Router capture and resize](../MSS_MCP/tools/mss_universal.py) · [Testing](testing.md)

## Lifecycle and recording

Each App ID is scoped to a specific launched app and owner connection. The runtime binds it to the launcher session, process PID/birth and executable identity. Application actions additionally address the correct window and where applicable the semantic node. The share mode is private until the owner chooses `read` or `control`. Attachment never transfers ownership. Shutdown attempts graceful app exit via official Remote and verifies the retained handle. Keep failed or uncertain receipts, including `FAILED_CLOSED`, `CLEANUP_PENDING` and owner loss, distinguishable from normal `CLOSED`. [Cleanup details](mss-cleanup-source-identity.md)

Recording stores session-bound action metadata and selected observations under the data root. Export selects evidence and content explicitly. A handoff validates the selected export and freezes the approved bytes. An explicit send invokes a bounded, read-only, ephemeral Codex CLI analysis and records delivery separately from app state. The package can include approved text and PNGs. Its CLI invocation disables MSS MCP, shell and web tools. Recovery checks the existing evidence when a send is uncertain. [Recording implementation](../MSS_Desktop/src/recording.rs) · [Delivery implementation](../MSS_Desktop/src/codex_handoff.rs)
