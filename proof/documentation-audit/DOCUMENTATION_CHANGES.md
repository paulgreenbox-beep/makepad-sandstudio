# Documentation changes

This audit updates the Windows source preview at [04ea3c52d5777adcbd9e36f0bf18572836d1d120](https://github.com/paulgreenbox-beep/makepad-sandstudio/commit/04ea3c52d5777adcbd9e36f0bf18572836d1d120). The release branch was clean at intake. The older local workspace and the detached MSI-prerequisite checkout had separate changes. The audit uses a clean worktree of the published release source.

| Area | Change and rationale |
| --- | --- |
| Agent entry point | [AGENTS.md](../../AGENTS.md) defines the rules. [MSS_Skills](../../MSS_Skills/README.md) points to them and [MSS_MCP](../../MSS_MCP/README.md) supplies the actual tool catalog and client setup. |
| Runtime architecture | [Architecture](../../doc/architecture.md) and [maps](../../doc/maps.md) follow Desktop and agent stdio through the Python router to the pinned launcher and official Remote. The initial proposal lives in [the marked archive](../../doc/history/initial-architecture/README.md). |
| Module layout | [Structure audit](STRUCTURE_AUDIT.md) separates seven Cargo libraries, the Desktop binary and the running Python/PowerShell connector. All eight SKLT object IDs, dependencies and structural policies are preserved. Their descriptions identify the actual source/runtime role. |
| Verification and safety | [Verification](../../doc/testing.md) separates contract, owned native GUI, MSI and model evidence. [Security](../../SECURITY.md) records same-user trust, permissions, explicit send, cleanup and unknown outcomes. Two dated source notes carry a historical label. |
| Onboarding and packaging | [Configuration](../../CONFIGURATION.md), [building](../../BUILDING.md), [Windows packaging](../../packaging/windows/README.md) and [limitations](../../KNOWN_LIMITATIONS.md) describe source and installed layouts, exact profiles and build pins, Human View and AI Direct, and the long TEMP/discovery limitation. The installer prerequisites tested on a local candidate are distinguished from RC2. |
| Notices | The [license audit](../../LICENSE_AUDIT.md) records what was found in exact RC2 and what blocks public binary redistribution. |

[Structure audit](STRUCTURE_AUDIT.md) · [Architecture audit](ARCHITECTURE_AUDIT.md) · [Agent instructions audit](AGENT_INSTRUCTIONS_AUDIT.md) · [Connection audit](CONNECTION_AUDIT.md) · [Validation record](VERIFICATION.md)

The change set contains Markdown and descriptive SKLT fields. Runtime sources, Cargo manifests, lockfile, WiX source, live configuration, and existing Cronica remain outside the diff.
