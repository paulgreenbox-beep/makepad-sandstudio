# Building MSS 0.1.0-preview.1

Build on native Windows x64 with the MSVC toolchain, Windows SDK, Git and Rust. The preview is tested with Rust 1.97.1. Cargo resolves Makepad at `130be1d0318adcf69453d925342607466353152c` and the remaining dependencies from `Cargo.lock`.

```powershell
cargo metadata --format-version 1 --locked
cargo build --workspace --release --locked
```

Add `--offline` when the pinned Git and registry caches are populated. Run the tests in [TESTING.md](TESTING.md). The Windows application uses Python 3.12+ and PowerShell 7.4+ as external runtimes. A guest and its compatible Makepad Remote are independently supplied by the operator. See [CONFIGURATION.md](CONFIGURATION.md).

The optional [WiX package](packaging/windows/README.md) stages the compiled application and the MSS MCP scripts with a per-user shortcut and MSI uninstall. Its input payload and notices must be reviewed before redistribution.
