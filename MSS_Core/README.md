# MSS_Core

**SCAFFOLD** in `0.1.0-preview.1`. The workspace builds [mss-core](Cargo.toml). Its [library](src/lib.rs) reports `NotImplemented` and declares no Cargo dependencies.

[MSS_MCP](../MSS_MCP/README.md) owns the preview's application lifecycle. The Python router binds the App ID to an owning connection and launch receipt. The Windows process helper checks PID, birth and executable identity. The PowerShell launcher retains the owned process handle and records exit evidence.

The [SKLT declaration](mss_core.sklt) reserves a future Rust session-supervision boundary. See the [current architecture](../doc/architecture.md) and [security model](../SECURITY.md).
