# MSS_MCP

**IMPLEMENTED** as a trusted local Windows stdio server. The runtime is [the Python router](tools/mss_universal.py), [its helpers](tools) and [the PowerShell launcher](tools/Start-MakepadMcp.ps1). The [Rust library target](src/lib.rs) is a scaffold. The router checks local admission, connection ownership, sharing and operation state, then calls the pinned Makepad Remote client. See [AGENTS.md](../AGENTS.md) for operating rules and [Security](../SECURITY.md) for the trust boundary.

## Connect one local server

Follow [Configuration](../CONFIGURATION.md) for the runtime folder, data root, catalog and PowerShell pin. For Desktop and an AI client to share an app, use the same canonical data root and Windows user/session. Each stdio connection has its own ownership. A new connection may see an empty catalog when no profiles have been admitted.

With absolute operator-selected paths, register one server named `mss` in Codex. The variables below denote your Python executable, MSS program folder, data root and pinned PowerShell executable.

```powershell
$router = Join-Path $programRoot 'MSS_MCP\tools\mss_universal.py'
codex mcp add mss --env "MSS_DATA_ROOT=$dataRoot" --env "MSS_PWSH_EXE=$pwshExe" -- $pythonExe -I -B $router
codex mcp list
```

If `mss` is already registered, review its command and environment before changing it. Open a new local connection and call `mss_server_info` and `mss_list_apps` to confirm the active server and catalog. `codex mcp list` shows registration. [Codex stdio configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli#configure-with-the-cli)

Other local MCP clients use the same executable, arguments and environment with their own stdio settings. This is a local server. Keep its stdin/stdout reserved for MCP and leave existing user configuration under operator control.

## Tools at the release baseline

Use `tools/list` to get current argument types and tool annotations. The [router schemas](tools/mss_universal.py#L123) define the exact names.

| Area | Tools |
| --- | --- |
| Server identity | `mss_server_info` |
| Catalog and build admission | `mss_list_apps`, `mss_list_builds`, `mss_register_build`, `mss_activate_build`, `mss_rollback_build` |
| Instance lifecycle | `mss_launch_app`, `mss_find_app`, `mss_close_app`, `mss_recheck_cleanup` |
| Sharing | `mss_list_instances`, `mss_share_app`, `mss_attach_app`, `mss_detach_app`, `mss_app_participants` |
| App observation | `mss_status`, `mss_activity`, `mss_settled`, `mss_ui_tree`, `mss_ui_find`, `mss_ui_wait`, `mss_ui_snap`, `mss_ui_diff`, `mss_grab`, `mss_logs` |
| Addressed input and resize | `mss_ui_act`, `mss_ui_type`, `mss_ui_key`, `mss_ui_mouse`, `mss_ui_drop`, `mss_resize` |
| Operation tracking | `mss_operations_list`, `mss_operation_status`, `mss_cancel_operation` |
| App-specific transfer | `mss_transfer_fragment` for a private Writer fragment between eligible owned RudraOffice instances |

### Read one instance

1. Call `mss_list_apps({})` and choose an admitted profile, then `mss_launch_app({"profile":"rudraoffice"})` when the task calls for a new process. To inspect an existing explicitly shared instance, use `mss_list_instances({})` and `mss_attach_app({"app_id":"<app_id>"})`.
2. Call `mss_status({"app_id":"<app_id>"})`. Use the current app window from that reply. Use `mss_ui_tree({"app_id":"<app_id>"})` to discover semantic windows. Semantic actions and text replacement require the exact `trees[].window` string and `nodes[].id`. Raw input, resize and grabs use the numeric `mss_status.w[].i`. For example, call `mss_grab({"app_id":"<app_id>","w":0,"scale":1})` when the returned status identifies window 0.
3. For an authorized mutation, find a current node and use an advertised action on its owning window. Independently read the affected state. Treat a genuine `capture_kind=pixels` PNG as visual evidence and bind it to App ID, window and frame receipt. Read logs and operation status when qualifying a result.
4. Detach an attachment with `mss_detach_app`. Close an owned instance with `mss_close_app` and inspect its cleanup result. For lost or uncertain responses, follow [AGENTS.md](../AGENTS.md) and use metadata/independent observation before any recovery decision.

The owner selects sharing with `mss_share_app`. `read` allows supported observations, `control` allows admitted mutations, and `private` revokes sharing. The underlying profile still governs access. Cancellation applies to a queued operation and leaves already-running mutations to their own outcomes. Read-only AI CAD and semantic RudraOffice capabilities differ by exact guest build.

[MSS process identity and cleanup](../doc/mss-cleanup-source-identity.md) · [MSS verification](../TESTING.md)
