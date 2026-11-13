# MSS_SDK

**SCAFFOLD** in `0.1.0-preview.1`. The workspace builds [mss-sdk](Cargo.toml). Its [library](src/lib.rs) reports `NotImplemented` and declares no Cargo dependencies.

Guest applications integrate through the applicable Makepad Remote build and expose their own semantic tree, actions and any app services. [Configuration](../CONFIGURATION.md) describes operator admission for the guest executable and Remote client. The router applies the capabilities admitted for the selected guest.

The [SKLT declaration](mss_sdk.sklt) reserves a future typed Rust app contract. The current guest integration has no dependency on this crate. See [compatibility](../doc/compatibility.md).
