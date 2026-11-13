# Connection audit

Reviewed release base `04ea3c52d5777adcbd9e36f0bf18572836d1d120`. The release source, older dirty workspace and detached portability checkout have distinct provenance. This audit takes code and packaging behavior from the release base and test scope from the corresponding exact artifact receipts.

| Finding before the edit | Verified behavior | Documentation decision |
| --- | --- | --- |
| The preview setup compressed source and installed layouts into one paragraph. | Desktop resolves its adjacent scripts or the Cargo checkout. Its default installed data root is LocalAppData. A standalone router defaults to the program root unless it receives `MSS_DATA_ROOT`. | Separate layouts and require one explicit shared data root for cross-connection examples. |
| External runtimes were listed without their selection order and packaging status. | Desktop can use an absolute Python override, PATH or the Codex cache fallback. The PowerShell launcher path comes from an override, catalog or legacy sibling layout and is hash-checked. RC2 has no install-time version gate. | Document explicit independent runtimes, distinguish the unpublished gate candidate and keep installed acceptance bounded. |
| The empty catalog was the only setup example. | Native profiles and configured builds use distinct pinned fields and are validated before launch. The launcher offers `-ValidateOnly`; it cannot demonstrate a live guest. | Document the required template fields, catalog entries, exact registration/promote/rollback tools and evidence. |
| Desktop and AI Direct described an instance without an ownership example. | The owner can grant `read` or `control`. An attached Desktop participant cannot close the owner process. Human View input and viewport resize are enabled only for admitted RudraOffice control. | Begin the same-instance example with the MCP owner, then share and attach Desktop. Use the fixed tabs for Desktop-owned launch. |
| Long discovery filename suggested an unspecified Windows limit. | On the same EXEs, a long data root failed Remote discovery. Controlled `TEMP/TMP` variation reproduced the failure, a long `session_root` independently worked, and discovery lengths above 260 also worked under other conditions. | Describe the observed factor and keep the exact limit and fallback location `NOT_VERIFIED`. |
| Codex package delivery could be read as a live connection. | The Desktop starts a bounded authenticated Codex CLI with `mcp_servers={}` and requires a matching result receipt. | Explain the human review step and separate analysis from AI Direct. |

## Source anchors

- [Desktop runtime resolution](../../MSS_Desktop/src/runtime_paths.rs), [fixed tabs and controls](../../MSS_Desktop/src/main.rs), [Desktop MCP client](../../MSS_Desktop/src/remote_client.rs), [Codex CLI handoff](../../MSS_Desktop/src/codex_handoff.rs).
- [MCP router and tool schemas](../../MSS_MCP/tools/mss_universal.py), [catalog and launch descriptor](../../MSS_MCP/tools/mss_profiles.py), [build registry](../../MSS_MCP/tools/mss_builds.py), [launcher](../../MSS_MCP/tools/Start-MakepadMcp.ps1), [RC2 packaging source](../../packaging/windows/MSS.wxs).
- [Updated configuration](../../CONFIGURATION.md), [source build](../../BUILDING.md), [installer](../../packaging/windows/README.md), [limitations](../../KNOWN_LIMITATIONS.md).

## Evidence separation

Existing local receipts under `proof/release-readiness` include the exact RC2 smoke, `path-matrix-7c3d1f4e/results.json`, and `run-installed-standalone-03/results.json`. The standalone-runtime receipt belongs to local MSI SHA-256 `81a5da3e62812f138d3f2ecead661132e50a7aad282240c72c18cc04fbef93cd`. It recorded seven checks with an external RudraOffice, install/test/uninstall exit codes `0/0/0`, and a real guest PNG. The Makepad resources audit recorded 223 embedded SVGs, a manifest referencing nine fonts, and no standalone font files in the RC2 CAB. A Windows host without access to the build checkout remains `NOT_RUN`.

The local development handoff receipt under `proof/codex-demonstration-handoff` records one completed model turn that read the approved demonstration. It does not qualify the installed MSI, live AI Direct or an independent retest of the demonstration. During the documentation audit, Codex CLI usage was checked via help for the stdio `mcp add` and `mcp get` commands and the handoff's `exec` options. No model call, install, app launch or program change is required by these documentation edits.

## Checks performed for this audit

- The pinned release launcher accepted the isolated native profile with PowerShell 7.6.10 using `-NoLogo -NoProfile -NonInteractive -File <launcher> -Profile <profile> -ValidateOnly`. Exit `0`, `status=VALIDATED`, exact Makepad guest revision `2271c0eb350cedd497c84373f17ad2b0b662cb72`, and the session directory stayed empty. Guest runtime launch was `NOT_RUN` in this check.
- A Python AST and relative-link check passed for these five files. It resolved 45 links, including section anchors, and matched all 12 documented tool names against the 35 declarations in the release router. The isolated receipt and command output are retained locally.
