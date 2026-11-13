# Building MSS 0.1.0-preview.1

Build on native Windows x64 with Git, Rust's MSVC toolchain, the MSVC linker and the Windows SDK. The release checks used Rust 1.97.1. [MSS Desktop's Cargo manifest](MSS_Desktop/Cargo.toml) pins Makepad `130be1d0318adcf69453d925342607466353152c`. [Cargo.lock](Cargo.lock) pins the resolved workspace dependencies.

To use the published preview branch in a new source directory:

```powershell
git clone --branch release/0.1.0-preview.1 https://github.com/paulgreenbox-beep/makepad-sandstudio.git
Set-Location makepad-sandstudio
cargo metadata --format-version 1 --locked
cargo build --workspace --release --locked
```

Add `--offline` to Cargo commands when the pinned Git and registry caches are populated. The build produces `target\release\mss-desktop.exe` with the default Cargo target directory. Launching from that tree lets Desktop locate the workspace's Python router beside the source files. A relocated executable needs the runtime files in the installed layout described in [configuration](CONFIGURATION.md#1-choose-the-source-or-installed-layout).

Python 3.12+ and PowerShell 7.4+ are external runtimes for the MCP and launcher. The guest EXE and its compatible Makepad Remote client are external operator-supplied binaries. The Desktop build uses its own Makepad revision. Match the Remote client to the guest and qualify the commands the profile needs. The tested native guest profiles used Makepad `2271c0eb350cedd497c84373f17ad2b0b662cb72`. [Compatibility and revisions](doc/compatibility.md)

Run the source verification in [TESTING.md](TESTING.md). For the installed route, see the [WiX packaging notes](packaging/windows/README.md) and the [preview limitations](KNOWN_LIMITATIONS.md). The public preview branch distributes source. The local Windows MSI is a candidate pending resource and license qualification.
