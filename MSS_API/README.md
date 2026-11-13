# MSS_API

**SCAFFOLD** in `0.1.0-preview.1`. The workspace builds [mss-api](Cargo.toml). Its [library](src/lib.rs) reports `NotImplemented` and declares no Cargo dependencies.

The executable interface is local stdio MCP. The [Python router](../MSS_MCP/tools/mss_universal.py) defines tool schemas, validates requests, applies owner and participant permissions and classifies outcomes. Desktop uses the same interface through its [MCP client](../MSS_Desktop/src/remote_client.rs).

The [SKLT declaration](mss_api.sklt) reserves a future typed Rust boundary. See the [current architecture](../doc/architecture.md).
