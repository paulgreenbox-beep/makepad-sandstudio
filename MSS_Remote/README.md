# MSS_Remote

**SCAFFOLD** in `0.1.0-preview.1`. The workspace builds [mss-remote](Cargo.toml). Its [library](src/lib.rs) reports `NotImplemented` and declares no Cargo dependencies.

App control uses the pinned official Makepad `work` Remote client. The [launcher](../MSS_MCP/tools/Start-MakepadMcp.ps1) binds discovery and readiness to the process it started. The [router](../MSS_MCP/tools/mss_universal.py) addresses operations by App ID and window, and checks permissions and capabilities. On the verified Windows path the Remote client speaks stdio MCP to the router and uses token-authenticated loopback to the guest.

The [SKLT declaration](mss_remote.sklt) reserves a future Rust integration boundary. See [source and protocol compatibility](../doc/compatibility.md).
