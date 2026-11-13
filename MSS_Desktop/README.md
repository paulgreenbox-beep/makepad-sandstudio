# MSS Desktop

**IMPLEMENTED** Windows preview. The [binary](src/main.rs) is the Makepad Human View. The workspace also builds a separate [library target](src/lib.rs) that remains **SCAFFOLD**. The [Cargo manifest](Cargo.toml) pins Makepad Widgets. The [Desktop client](src/remote_client.rs) starts the [MSS Python connector](../MSS_MCP/README.md) over stdio.

- Select a named tab to launch its configured profile. **Shared app** and **Find shared apps** discover instances made available by their owner. **Attach App ID** connects the view. **Detach view** leaves the guest running. **Close selected app** closes a Desktop-owned instance.
- An admitted RudraOffice control view can resize the selected guest to its measured viewport and send mouse and keyboard input when the preview has focus. Read attachments and the AI CAD view are view-only. AI Direct addresses the guest App ID independently of tab selection.
- **Screenshot** saves a guest PNG. Human View records addressed actions and optional frame and semantic observations. Stop recording, choose the data to include and use **Prepare for Codex** and **Review files**. **Send to Codex** invokes the installed CLI after explicit selection. A matching completed model receipt is required for `RECEIVED`.

[Runtime paths](src/runtime_paths.rs), [input mapping](src/human_input.rs), [recording](src/recording.rs) and [Codex handoff](src/codex_handoff.rs) belong to the binary. The [SKLT edges](mss_desktop.sklt) describe the historical logical design. See [building](../BUILDING.md), [configuration](../CONFIGURATION.md), [verification](../doc/testing.md) and [limitations](../KNOWN_LIMITATIONS.md).
