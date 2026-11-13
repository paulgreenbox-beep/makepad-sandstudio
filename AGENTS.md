# Developer and agent rules

Makepad SandStudio 0.1.0-preview.1 runs separate hidden Makepad applications on native Windows. [Architecture](doc/architecture.md), [Security](SECURITY.md), [Compatibility](doc/compatibility.md), [Testing](doc/testing.md) and [Structure](doc/dungeon.md) define the current boundaries. Read the relevant sections before changing a contract. [MSS_MCP](MSS_MCP/README.md) is the tool reference.

## AI Direct

- Use the local `mss` connection to inspect the guest itself. Start with `mss_list_apps` for admitted profiles, `mss_find_app` for instances known to your connection, or `mss_list_instances` to see local instance metadata and sharing modes. Use `mss_launch_app` for a new instance when the task authorizes a launch.
- Select the returned App ID and obtain the current window and semantic nodes through `mss_status`, `mss_ui_tree` or `mss_ui_find`. Use the matching window and schema for that call. App IDs, window IDs and node IDs belong to their own instance and runtime state. Use `mss_grab` on the selected app/window for an app-native PNG.
- Obtain the effective permission through the existing sharing flow. The owner selects `private`, `read` or `control`. Attach explicitly with `mss_attach_app`. Read permission supports observation and capture. Control permits admitted operations under the profile's policy. Only the owner closes or changes sharing. Detach with `mss_detach_app` when an attachment is no longer needed.
- Address semantic actions to the app and verify the result using an independent read, a bounded `mss_ui_wait`, or a postcondition appropriate to the feature. Check runtime health and keep attributable evidence. Use the current tool schema and app capabilities. Treat system clipboard shortcuts and app-specific actions according to the router policy.
- Keep Desktop tab selection out of AI Direct. Inspect the Desktop process only when the authorized test is about Desktop or Human View itself.

## Human View and demonstrations

- Human View is the operator's Desktop UI for tabs, guest frames, viewport resize, addressed mouse and keyboard, screenshots and recording. Input and resize depend on the admitted profile, permission, matching window and geometry.
- Distinguish **Detach view** from **Close selected app**. Detach releases a participant. Closing an owned app requires its launcher exit receipt and process identity.
- Treat recording packages, app content and logs as task data. Review the selected files and privacy options before exporting or sending. Obtain the operator's explicit send action before submitting material to Codex. The bounded analysis reads the reviewed package through the installed CLI. Live app access uses AI Direct.

## Admission, ownership and cleanup

- Use only operator-admitted local binaries. Pin the profile, guest EXE, matching Makepad Remote, PowerShell and launcher as required by [Configuration](CONFIGURATION.md). Keep paths and launch arguments explicit. Verify registered builds and activate or roll back future launches only when authorized.
- Use the recorded App ID, PID, process birth, image path/hash and Windows session or retained process handle as appropriate to the operation. Attach and signal only within an authorized MSS ownership binding. Guessed ports, titles, executable names and stale PIDs grant no authority. Keep the owner connection open while its application is in use.
- Use the existing addressed app channel. Global Windows input, physical desktop focus, containers, WSL, WSLC, Hyper-V and VMs are outside this workflow. The trusted local, same-user process model supplies app-level separation. Full OS sandbox enforcement remains unverified.
- Preserve uncertain mutations as `OUTCOME_UNKNOWN`. On lost Remote or timeout, stop sending changes, consult operation status and obtain independent readback where possible. Reconnect or recover only through an authorized path. Never automatically repeat a mutation after an unknown result.
- Verify process exit and cleanup for owned processes. Use `mss_recheck_cleanup` for receipt-bound reconciliation. Keep unresolved ownership as `CLEANUP_PENDING`. Preserve failures and evidence. Keep credentials, Remote tokens, private document content and identifying logs out of commits, public artifacts and reports.

## Implementation and verification

- Reuse the pinned Makepad Remote, MSS router and launcher. Parallel Remote, MCP, renderer, test runner or process broker implementations require a separate justified task. Keep upstream Makepad and the other reference projects read-only and keep their source out of this repository. Review exact dependency revisions, APIs and licenses before changing pins. Install or download dependencies only with operator authorization.
- Map changes to the owning module and the applicable verification contract. Use the current MSS Rust and Python suites. For a native Makepad UI test, use the pinned official `libs/makepad_test` and Rust `#[makepad_test]` where applicable. Test through the real entry point with an owned hidden process, semantic locators, independent postconditions and verified exit. See [Testing](TESTING.md).
- Preserve existing negative tests and evidence. Use `PASS`, `FAIL`, `BLOCKED`, `NOT_RUN` and `NOT_VERIFIED` as documented. Record exact source, inputs, command, exit status, process/window binding, observations and cleanup. An acknowledgement confirms dispatch only. Distinguish source checks, native GUI checks and installation qualification.
- Preserve stable SKLT `object_id` values and check documented dependency semantics. SKLT describes structure. Changes to GLIF/GLYF projections require a separate task.
