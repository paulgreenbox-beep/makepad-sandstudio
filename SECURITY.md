# Security model

MSS `0.1.0-preview.1` is a trusted-local Windows developer preview. The implemented policy lives in the Python router, its local sharing store and the PowerShell launcher. It is an application-level boundary for admitted guests running under the local Windows user. OS sandboxing, protection against hostile same-user processes and production dispatcher qualification remain `NOT_VERIFIED`. [Architecture](doc/architecture.md) · [Limits](KNOWN_LIMITATIONS.md)

## Admission and identity

- Operators select a local profile, trusted PowerShell, launcher and the guest/official Remote executable pair. The router verifies profile/build policy, hashes and optional launch descriptors. Paths for controlled files must be local, canonical and non-reparse. The launcher rechecks and opens pinned executable files before it starts them. Agent tool arguments do not grant arbitrary executable or shell authority. [Configuration](CONFIGURATION.md) · [Profile admission](MSS_MCP/tools/mss_profiles.py) · [Launcher](MSS_MCP/tools/Start-MakepadMcp.ps1)
- An opaque App ID resolves to an owned app or explicit attachment. MSS binds this ID to the owner connection, launcher receipt/session, Windows session, PID, birth identity and executable. App commands then select the exact window and current semantic node where needed. A PID, title, port or window identifier alone grants no ownership. [Router](MSS_MCP/tools/mss_universal.py) · [Process identity](MSS_MCP/tools/mss_process.py)
- The owner keeps the app private or grants local `read` or `control`. Control remains subject to profile restrictions, native capabilities and current geometry/activity checks. The owner controls sharing and closure. Participants detach their own connections and cannot take over an owner-lost app. Revocation or detach cancels queued work as applicable. The local SQLite store is trusted same-user state, not a signed attestation. [Sharing](MSS_MCP/tools/mss_shared.py)

## Addressed commands and lifecycle

Native Windows guests use their own Makepad Remote loopback endpoint and a per-session discovery token. MSS uses the official Remote client over local stdio. Each launch owns a separate discovery directory under the Windows account profile. Receipt validation binds attached clients to that directory. Keep discovery files and tokens private. The guest token and an app-level permission check do not restrict other programs running with the same OS identity. Do not expose local endpoints to a network or bypass the router's policy. Independent processes and Makepad addressed input do not restrict guest filesystem, network or credential access.

MSS targets app/window-local input. Do not use foreground desktop focus, global keyboard/mouse injection or an unverified fallback. Human View input is bound to the selected drawn geometry. An ACK confirms dispatch only. Record independent state and health evidence to claim an effect. After transport loss or `OUTCOME_UNKNOWN`, preserve the receipt and never automatically replay a mutation. [Verification contracts](doc/testing.md)

Cleanup is owner-only and uses verified retained process identity. It attempts official Remote graceful exit and records observed process exit. Never terminate by process name or guessed PID. Uncertain exit, identity or legacy provenance remains `CLEANUP_PENDING`; use receipt reconciliation that does not signal the process. Crash-surviving containment, complete descendant cleanup and OS resource confinement remain unverified. [Cleanup scope](doc/mss-cleanup-source-identity.md)

## Artifacts, recording and Codex

Keep user files, live profile pins, discovery, logs, screenshots and internal paths out of public issues and commits. Preserve per-app artifact boundaries. Retain evidence with timestamps, source/process identity and file hashes. Treat local receipts and router startup hashes as scoped diagnostics. The frozen manifest covers the router's five Python modules, not interpreter provenance, full Git state or a signed attestation. [Startup identity](doc/mss-cleanup-source-identity.md)

Human View recording can contain sensitive text, trees and PNGs. Review the selected export and send only with explicit user approval. The handoff revalidates its manifest and uses the installed authenticated Codex CLI for bounded read-only analysis. The handoff invocation disables app MCP, shell and web access and does not forward `OPENAI_API_KEY`. Record the response and preserve uncertainty without retry. The same-user Codex execution still relies on its installed runtime and account. [Recording](MSS_Desktop/src/recording.rs) · [Handoff](MSS_Desktop/src/codex_handoff.rs)

Report security issues privately to the repository owner. Provide the source revision and a minimal sanitized reproduction.
