# Makepad SandStudio

## What is Makepad SandStudio?

## What is Makepad SandStudio?

Makepad SandStudio (MSS) runs, inspects, and automates native Makepad applications through the official Makepad Remote and the Model Context Protocol (MCP). One local MCP registration gives Codex a catalogue of admitted application profiles. Each launch returns an app ID for a separate native process.

## Features

- **Working connector.** List profiles, launch an owned process, read its semantic UI tree, invoke supported UI actions, capture native PNG frames, read logs, and close the app. The connector scopes app IDs to their MCP connection and records process and cleanup receipts.
- **Experimental Windows qualification.** The local connector has been exercised with the pinned Makepad Todo and Counter fixtures. The two-session Codex test checks distinct app instances, independent UI state, and rejection of a peer's app ID.
- **Project structure.** The Rust workspace includes a prototype Desktop shell and crates for future lifecycle, API, remote, rendering, SDK, and MCP work. The local connector is implemented in `MSS_MCP/tools/`. Production isolation and the complete Toolkit compatibility target remain planned.

## Architecture

```text
Codex → MSS MCP → app ID → owned Makepad process → Makepad Remote
```

MSS uses Makepad's native semantic tree and frame capture. The launcher pins the executable bytes, starts the app in its own working and temporary directories, and binds the official `makepad-remote mcp` connection to the created process. The MCP router forwards calls to that connection. Makepad renders the application and provides its PNG frames.

## Getting started

Use native Windows, Git, a current Rust MSVC toolchain with 2024 edition support, PowerShell 7.4 or newer, and Python 3.11 or newer. Install the MSVC C++ build tools and Windows SDK through Visual Studio Installer. For the Codex integration, install the Codex CLI and open a new local chat after registration.

One Windows tool installation option uses these commands in PowerShell. Install only the tools you need, then open a fresh PowerShell 7 session.

```powershell
winget install --exact --id Git.Git
winget install --exact --id Microsoft.PowerShell
winget install --exact --id Python.Python.3.12
winget install --exact --id Rustlang.Rustup
rustup toolchain install stable-x86_64-pc-windows-msvc
```

With Node.js and npm available, the Codex CLI can be installed with `npm install -g @openai/codex`. [Codex CLI installation](https://developers.openai.com/codex/cli/)

Clone this repository and build the MSS Rust workspace from the repository root.

```powershell
git clone --branch release/mss-source-20261106 --single-branch https://github.com/paulgreenbox-beep/makepad-sandstudio.git
Set-Location makepad-sandstudio
cargo build --workspace --locked
```

The Desktop prototype uses the official Makepad Git dependency pinned in its Cargo manifest at `130be1d0318adcf69453d925342607466353152c`. The connector uses a separate official Makepad source checkout. Check out the exact supported revision and build only the Remote executable and sample apps. The included fixture lockfile records the dependency resolution used for this publication.

```powershell
git init makepad-work
git -C makepad-work config core.longpaths true
git -C makepad-work remote add origin https://github.com/makepad/makepad.git
git -C makepad-work fetch --depth=1 --no-tags origin 2271c0eb350cedd497c84373f17ad2b0b662cb72
git -C makepad-work checkout --detach FETCH_HEAD
Copy-Item MSS_MCP/dependencies/makepad-2271c0e.lock makepad-work/Cargo.lock
cargo build --manifest-path makepad-work/Cargo.toml --release --locked --target-dir makepad-work-target -p makepad-remote -p makepad-example-todo -p makepad-example-counter --bin makepad-remote --bin makepad-example-todo --bin makepad-example-counter
pwsh -NoProfile -File MSS_MCP/tools/Initialize-MakepadProfiles.ps1
```

The pinned Makepad checkout does not ship a root Cargo lockfile. Its first build resolves a local lockfile. Keep that lockfile and use `--locked` for repeat builds with the same dependency resolution. If you build with a different `CARGO_TARGET_DIR` or `--target-dir`, pass that same directory to the profile initializer with `-TargetDirectory`.

Register the generated local setup with Codex. Use the absolute paths resolved in this shell. If you already have an MCP server named `mss`, inspect that entry before replacing it.

```powershell
$python = (Get-Command python.exe -ErrorAction Stop).Source
$entry = (Resolve-Path MSS_MCP/tools/mss_universal.py).Path
codex mcp add mss -- $python -I -B $entry
codex mcp get mss --json
```

The stdio command used by the MCP client is `& $python -I -B $entry`. In a new local Codex chat, call `mss_list_apps({})`, then `mss_launch_app({"profile":"todo"})`. Use the returned `app_id` for `mss_ui_tree`, `mss_ui_act`, `mss_grab`, and `mss_close_app`. [Complete Todo example and profile setup](doc/mss-universal-mcp.md)

## Testing

Run the normal Rust workspace tests with `cargo test --workspace --locked`. The connector also has PowerShell profile and native GUI tests, plus a model-free Codex App Server probe. These tests are separate from the Rust workspace. [Test commands and their scope](doc/mss-universal-mcp.md#testing)

Use Makepad's `#[makepad_test]` and standard Cargo integration tests to exercise application behavior. The pinned Makepad Todo example includes an upstream `ui` integration-test target. Run it in the separate Makepad checkout. [Upstream test command](doc/mss-universal-mcp.md#testing)

## Limitations

The connector is for trusted local development on native Windows. Profile admission and separate app processes provide a routing boundary within each MCP connection. OS sandboxing, crash containment, and support for arbitrary Makepad revisions require separate qualification.

The tested configuration uses independent MCP connections per chat. Keep Codex MCP connection sharing disabled when chat-level separation is required. The pinned fixture results apply to those executables and their supported semantic actions. Each additional app requires its own reviewed profile and compatibility check.

The generated profiles, tool configuration, SDK checkout, build outputs, and runtime evidence live on the local machine.

[Architecture](doc/architecture.md) · [Security](SECURITY.md) · [MIT license](LICENSE)
