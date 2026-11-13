# Makepad SandStudio (MSS)

Makepad SandStudio 0.1.0-preview.1 is a Windows developer preview for running and observing independent hidden Makepad applications. It uses the guest's own Makepad Remote and renderer.

- **Human View** is the native Desktop viewer. It shows app frames, supports viewport resize and addressed input on admitted windows, and lets the operator take screenshots and record a demonstration. The preview includes tested RudraOffice workflows and a read-only AI CAD view.
- **AI Direct** is the local `mss` stdio server. Agents select an owned or explicitly shared App ID and inspect or control the guest directly. The router checks the connection's permissions and profile policy.
- **Codex handoff** submits a reviewed Human View recording to an authenticated local Codex CLI after the operator approves the send. The bounded package analysis and live AI Direct are separate flows.

## Get started

1. [Build from source or review the Windows MSI requirements](BUILDING.md). The installed preview requires external Python 3.12+ and PowerShell 7.4+ for the full app-launch flow. The current Windows binary package has unresolved clean-machine resource and notice checks.
2. [Configure a short local data root and admit a guest build](CONFIGURATION.md). The new catalog starts empty. Supply the guest EXE and the matching Makepad Remote with reviewed SHA-256 pins.
3. [Use the Desktop viewer](MSS_Desktop/README.md) or [connect an agent to `mss`](MSS_MCP/README.md). See [AGENTS.md](AGENTS.md) for ownership and verification rules.

## Project status

| Module | Preview status |
| --- | --- |
| [MSS_Desktop](MSS_Desktop/README.md) | IMPLEMENTED in the Rust binary. The library target is a scaffold. |
| [MSS_MCP](MSS_MCP/README.md) | IMPLEMENTED through Python and PowerShell. The Rust library is a scaffold. |
| [MSS_Core](MSS_Core/README.md), [MSS_API](MSS_API/README.md), [MSS_Remote](MSS_Remote/README.md), [MSS_Render](MSS_Render/README.md), [MSS_SDK](MSS_SDK/README.md) | SCAFFOLD Rust targets. Current runtime responsibilities are documented in each module. |
| [MSS_Skills](MSS_Skills/README.md) | IMPLEMENTED. Two repository-scoped Codex skills cover app control and MSS development. |

[Architecture and process flow](doc/architecture.md) · [Maps](doc/maps.md) · [Tests](TESTING.md) · [Compatibility](doc/compatibility.md) · [Security](SECURITY.md) · [Known limitations](KNOWN_LIMITATIONS.md) · [License audit](LICENSE_AUDIT.md) · [Third-party notices](THIRD_PARTY_NOTICES.md)

MSS source is distributed under the [MIT license](LICENSE). RudraOffice, AI CAD, the experimental DWG worker, guest Makepad Remote, Python, PowerShell and Codex are external components. The preview assumes a trusted local user and qualified guest builds. Full OS sandbox enforcement and unattended dispatcher qualification remain unverified.
