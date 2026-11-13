# Agent instructions audit

Reviewed release source: [04ea3c52d5777adcbd9e36f0bf18572836d1d120](https://github.com/paulgreenbox-beep/makepad-sandstudio/commit/04ea3c52d5777adcbd9e36f0bf18572836d1d120).

| Previous instruction or gap | Observed implementation | Correction |
| --- | --- | --- |
| The Desktop shell is illustrative | The [Desktop binary](../../MSS_Desktop/src/main.rs) decodes real guest PNGs, operates on a selected App ID, and captures Human View actions | Describe the live viewer and label guest-specific evidence |
| Toolkit, its Script API, and its Scheduler govern acceptance | The [router](../../MSS_MCP/tools/mss_universal.py) exposes native app tools, and [MSS tests](../../MSS_MCP/tests) cover Windows stdio and router contracts | Use MSS tests and pinned Makepad's native Rust test library for guest UI tests |
| MCP calls an implemented Rust MSS_API | Desktop launches the [Python router](../../MSS_Desktop/src/remote_client.rs), and [Rust MSS_MCP](../../MSS_MCP/src/lib.rs) reports a scaffold | Name the real process path and runtime owner |
| The agent can mistake Desktop tabs for application state | Agent routes have explicit App IDs; Desktop has a separate selected tab and view lifecycle | Keep AI Direct on the guest and document read/control sharing |
| Examples do not define recovery or export consent | The router queues mutations and tracks their outcomes; [handoff code](../../MSS_Desktop/src/codex_handoff.rs) requires a prepared package and launches a bounded CLI process | Preserve uncertain outcomes, distinguish close and detach, and separate explicit review/send from live tools |
| Tool names can drift from legacy examples | The router builds a versioned stdio tool catalog from its actual schemas | Document current names and get the current schema from `tools/list` |

[AGENTS.md](../../AGENTS.md) is the authority for operating rules. [MSS_MCP](../../MSS_MCP/README.md) is the protocol reference and [MSS_Skills](../../MSS_Skills/README.md) is the index. No agent instructions have been installed in Codex as part of this audit.
