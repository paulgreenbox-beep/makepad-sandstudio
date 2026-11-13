# Codex skills verification

Base [PR #17](https://github.com/paulgreenbox-beep/makepad-sandstudio/pull/17) at `cf20e996ab91e8b1bda1e224bb451914cbafd689`. The checks ran in an isolated Windows worktree using installed Codex CLI `0.167.0-alpha.4.1`.

| Check | Status | Observation |
| --- | --- | --- |
| Skill format and source references | PASS | UTF-8 without BOM, exact YAML `name` and `description`, directory names match. Thirteen relative links and all 19 cited app tool names checked against the 35-name router catalog. |
| Bundled Python validator | BLOCKED | Its interpreter could not import `yaml` (exit 1). The independent static check and installed Codex parser verified both files. |
| Codex discovery | PASS | `codex app-server --stdio`, then `initialize`, `initialized` and `skills/list` with repository `cwd` and `forceReload: true`. Exit 0, no discovery errors. Both exact project paths returned `scope: repo` and `enabled: true`. |
| Implicit model selection | PASS for selection | Two fresh `codex exec --ephemeral --json` explanation turns with no skill names in the prompts. Each attempted to read only the expected skill file. Both turns completed and exited 0. |
| Implicit loading and use | BLOCKED | Windows policy rejected both model file reads. The app answer fell back to AGENTS. The development answer did not provide verified exact test commands. |
| Explicit invocation and answer content | PASS | Two App Server `turn/start` requests used the documented `skill` input. Both model turns completed. The answers contained the skill-specific details below. |
| Explicit probe tool-free assertion | FAIL, exit 1 | The installed client exposed auxiliary tools despite disabling user MCP and shell tools for this probe. There were attempted document reads and resource listings. A read-only `mss_server_info` call was rejected by approval policy. There was no app attachment, window interaction, guest launch, or model-initiated edit/test run. |
| Documented test commands | PASS | Fresh, isolated TEMP/TMP and approved CPython. Focused `test_mss_shared_router.py`: 8 tests. Full `test_mss_*.py`: 190 tests. Rust `cargo test -p mss-mcp --test gui_tools --locked --offline`: one stdio contract test. All exit 0. |
| Native GUI and release | NOT_RUN | These scenarios check selection and instructions. The MSS router, launcher and Desktop sources are unchanged. |

## Real model scenarios

- **«Открой RudraOffice и проверь текст»** selected `mss-app-control`. The explicit answer described exact App ID discovery and attach, effective `read` and `control`, tree readback, composite semantic and numeric capture window IDs, `capture_kind: pixels`, unknown-outcome status and detach with `app_closed: false`. It kept the workflow in AI Direct and never attempted Desktop interaction.
- **«Исправь маршрутизацию MSS MCP и запусти тесты»** selected `mss-development`. The explicit answer located `MSS_MCP/tools/mss_universal.py`, named `MSS_MCP/tests`, gave the exact focused Python, full Python and Rust stdio commands in order, and kept launcher and native checks conditional.

Both prompts requested explanations only. Total: four real model turns, two implicit and two explicit.

## Evidence

| File or trace | SHA-256 |
| --- | --- |
| [mss-app-control SKILL.md](../../.agents/skills/mss-app-control/SKILL.md) | `172358b005a89389310344d43346b37e88359ea9e1d9e36ea1a16e7289b3480d` |
| [mss-development SKILL.md](../../.agents/skills/mss-development/SKILL.md) | `8336326131e14afc49fc76e68d147d5a511157dfe5fc6c2ed39d758881129f7c` |
| Implicit app turn JSONL | `f1150d99682f4e805b0755822d6ed5c789b86da92415be02dff7380467d2cc25` |
| Implicit development turn JSONL | `0643b3bca3a692a5faf7e44932188327b5c5b153b1107c133afc21fe0fa011eb` |
| Explicit App Server trace JSONL | `583e9dea74ca1d37923a2283a73d2a1fe5f61fc570bac3b57828cd75f6f1ad1f` |

Raw traces under local `proof/codex-skills/local-model/` contain machine-specific data and stay private. See [official skill format and discovery](https://learn.chatgpt.com/docs/build-skills) and [App Server skill invocation](https://learn.chatgpt.com/docs/app-server#skills).
