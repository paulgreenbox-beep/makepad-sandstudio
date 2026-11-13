# MSS_Render

**SCAFFOLD** in `0.1.0-preview.1`. The workspace builds [mss-render](Cargo.toml). Its [library](src/lib.rs) reports `NotImplemented` and declares no Cargo dependencies.

Makepad Remote captures guest pixels. The [router](../MSS_MCP/tools/mss_universal.py) records the capture kind, app and window, dimensions and digest. The [Desktop client](../MSS_Desktop/src/remote_client.rs) verifies its app and window binding and decodes the PNG for the selected tab. AI Direct can request a guest capture independently.

The [SKLT declaration](mss_render.sklt) reserves a future Rust frame-delivery boundary. The preview uses app-originated PNGs. Shared GPU textures, hosted-child composition and a dedicated Rust frame API are outside this path. See the [current architecture](../doc/architecture.md) and [verification](../doc/testing.md).
