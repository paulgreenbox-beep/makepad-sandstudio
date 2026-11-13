# Structure audit

Source baseline [04ea3c52d5777adcbd9e36f0bf18572836d1d120](https://github.com/paulgreenbox-beep/makepad-sandstudio/commit/04ea3c52d5777adcbd9e36f0bf18572836d1d120), release `0.1.0-preview.1`. The published release checkout was clean. This documentation audit uses a separate checkout because the primary local checkout has unrelated changes and the portability checkout contains a distinct installer candidate.

## Discrepancies in the baseline

- The original architecture described Desktop as a frame placeholder. [The Desktop binary](../../MSS_Desktop/src/main.rs) already runs Human View. Its separate library target remains a status marker.
- The original SKLT files gave every module generic session inputs and outputs. Their `depends_on` edges expressed a proposed Rust design. The working connector uses local stdio, Python, PowerShell and the official Makepad Remote client.
- Earlier agent documents pointed to planned API/SDK and legacy test-script responsibilities. The actual tool schemas come from the [router catalog](../../MSS_MCP/tools/mss_universal.py). [AGENTS.md](../../AGENTS.md) is the operating guide.
- The [WiX source](../../packaging/windows/MSS.wxs) installs the Desktop, Python sources, launcher and documents. The package requires external Python and PowerShell and an operator-admitted guest and Remote client. The source-only [example catalog](../../MSS_MCP/profiles/apps.example.json) starts with no admitted profiles.

## Module inventory

Implementation status describes source, independently of acceptance on untested builds and hosts.

| Module | Status | Files and actual responsibility | Cargo and runtime | Historical SKLT edges |
| --- | --- | --- | --- | --- |
| [MSS_Core](../../MSS_Core/README.md) | SCAFFOLD | Status-only library and declaration. Process ownership and cleanup live in the router, process helper and launcher. | Workspace library without declared dependencies or runtime consumer. | — |
| [MSS_API](../../MSS_API/README.md) | SCAFFOLD | Status-only library and declaration. Tool schemas, permission, dispatch and outcomes live in the router. | Workspace library without declared dependencies or runtime consumer. | `mss.core` |
| [MSS_Remote](../../MSS_Remote/README.md) | SCAFFOLD | Status-only library and declaration. The router and launcher bind the owned guest and call the official external Remote client. | Workspace library without declared dependencies or runtime consumer. | `mss.core`, `mss.api` |
| [MSS_Render](../../MSS_Render/README.md) | SCAFFOLD | Status-only library and declaration. Router handles app-originated PNGs and receipts. Desktop verifies and displays the selected frame. | Workspace library without declared dependencies or runtime consumer. | `mss.core` |
| [MSS_SDK](../../MSS_SDK/README.md) | SCAFFOLD | Status-only library and declaration. Guests supply their own semantic UI and services through Makepad. | Workspace library without declared dependencies or guest consumer. | `mss.api` |
| [MSS_MCP](../../MSS_MCP/README.md) | IMPLEMENTED connector, SCAFFOLD Rust library | Five Python modules, PowerShell launcher, empty catalog example and tests. Owns profile and build admission, app binding, dispatch, sharing, queue and cleanup. | Workspace library has no declared dependencies. The [Windows Rust test](../../MSS_MCP/tests/gui_tools.rs) starts the Python connector. Runtime uses Python stdlib, PowerShell and pinned external guest and Remote executables. | `mss.api` |
| [MSS_Desktop](../../MSS_Desktop/README.md) | IMPLEMENTED binary, SCAFFOLD Rust library | Native viewer, stdio client, input mapping, recording and optional Codex CLI handoff. | Workspace binary and library. The sole direct dependency is Makepad Widgets at `130be1d0318adcf69453d925342607466353152c`. The binary starts the Python connector. | `mss.api`, `mss.render` |
| [MSS_Skills](../../MSS_Skills/README.md) | PARTIAL | README and SKLT. [AGENTS.md](../../AGENTS.md) provides operating rules. Installable skill packaging remains PLANNED. | Documentation outside Cargo and the executable runtime. | `mss.api`, `mss.mcp` |

## Runtime edges and evidence

The seven Cargo members have seven library targets, one Desktop binary and a Windows router integration test. The working path does not link any MSS library target. Desktop opens its own Python stdio connection and selects a guest by App ID. An agent can connect directly without Desktop. The router uses a PowerShell launcher for each owned guest and calls the official Makepad Remote client bound to the launched process and discovery record. A reviewed recording package can be sent using the separate installed Codex CLI handoff. See [architecture](../../doc/architecture.md), [testing](../../doc/testing.md) and the [connection audit](CONNECTION_AUDIT.md).

## Structural verification

A read-only Dungeon probe of the release returned `SKLT_ONLY`, 8 SKLT files, 8 objects, 8 modules, 0 GLIF and no issues. SKLT descriptions now identify the implemented or scaffolded role. Schema version, `object_id`, `id`, `level`, `git_scope`, `depends_on`, `isolation`, retention and document `state` are preserved. See [Dungeon project structure](../../doc/dungeon.md).
