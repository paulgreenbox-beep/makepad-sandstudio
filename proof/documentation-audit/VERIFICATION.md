# Documentation verification

Source baseline: `04ea3c52d5777adcbd9e36f0bf18572836d1d120`. Checks ran on native Windows against that release's program source in an isolated documentation checkout.

| Check | Command or method | Result |
| --- | --- | --- |
| Published base and worktree | `git ls-remote origin refs/heads/release/0.1.0-preview.1`, local HEAD/status/diff and staging allowlist | PASS. Exact source base matched, and the final diff was limited to Markdown and SKLT descriptions. |
| Relative references | Check Markdown link targets and headings across all tracked, archived and audit Markdown, with source line anchors checked against file bounds | PASS. 306 relative references across 37 Markdown files, zero missing targets. External links were outside the full scan. |
| Current MCP catalog | Run `python -I -B MSS_MCP/tools/mss_universal.py` with a fresh data root. Exchange `initialize`, `tools/list`, `mss_server_info`, `mss_list_apps` over stdio and compare documented tool names. | PASS, exit 0. 35 unique tool names, empty profile catalog, matching server PID and frozen source capture. |
| CLI and native profile | `codex mcp add --help`, `codex mcp get --help`, `codex exec --help`. Official PowerShell 7.6.10 with `-NoLogo -NoProfile -NonInteractive -File <launcher> -Profile <profile> -ValidateOnly`. | PASS. CLI help accepted the documented form. The pinned launcher returned `VALIDATED`, exit 0. Session directory empty. |
| Cargo workspace inventory | `cargo metadata --format-version 1 --locked --offline` | PASS, exit 0. Seven workspace packages, 133 resolved packages. Existing Makepad duplicate-package warnings retained. |
| Rust format | `cargo fmt --all -- --check` | PASS, exit 0. |
| Rust stdio contract | `cargo test -p mss-mcp --test gui_tools --locked --offline`, with `MSS_TEST_PYTHON` set to standalone CPython 3.14.10 | PASS, exit 0. One test passed. |
| Python suite, first run | `python -I -B -m unittest discover -s MSS_MCP/tests -p 'test_mss_*.py'` with inherited TEMP | FAIL, exit 1. 190 ran, one teardown error `WinError 145` in `test_owner_pid_reuse_blocks_attach_and_dispatch`. |
| Python suite, isolated rerun | Same command and interpreter with a fresh, short task TEMP/TMP | PASS, exit 0. 190 passed. Existing `PurePath.is_reserved` deprecation warnings on Python 3.14 retained. |
| SKLT | Read-only Dungeon probe, baseline comparison outside descriptive fields | PASS. Eight objects/modules, no structural issues, zero GLIF. |
| Mermaid | Manual syntax and delimiter review of four new diagrams | Static review complete. Rendering with a Mermaid parser is NOT_RUN. |
| Full Cargo release and native acceptance | Original release receipts reviewed in [testing](../../doc/testing.md). | NOT_RUN for this documentation-only change. Full Cargo build, live guest, MSI install and model calls were outside the audit rerun. |

Raw local validation and release receipts remain private. The published record contains the checks, source revision and bounded results.
