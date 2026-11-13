# Architecture audit — Windows source preview

Baseline reviewed `04ea3c52d5777adcbd9e36f0bf18572836d1d120` (`release/0.1.0-preview.1`). Implementation status describes the source. Verification status describes a named test and its exact fixture.

## Findings before edits

| Active document | Observed discrepancy | Evidence and correction |
| --- | --- | --- |
| `doc/architecture.md` and `doc/maps.md` | Lead with a Rust API/Core supervisor, Toolkit jobs and hypothetical frame delivery. Describe Desktop as an illustrative shell without live frames. | [Desktop's stdio client](../../MSS_Desktop/src/remote_client.rs), [Python router](../../MSS_MCP/tools/mss_universal.py) and [launcher](../../MSS_MCP/tools/Start-MakepadMcp.ps1) form the implemented process and frame path. Keep the old design in a marked archive. |
| `doc/compatibility.md` | Treats the real Makepad Cargo pin as source research only. Its old HTTP discussion can be mistaken for the active native guest transport. | [Desktop pin](../../MSS_Desktop/Cargo.toml), [lockfile](../../Cargo.lock) and the pinned guest work revision establish separate roles. Native Windows guest launch uses `--remote`, per-session discovery and the official client in MCP stdio mode. |
| `doc/testing.md` | Uses Toolkit regression as mandatory release acceptance and says no behavioral test ran. | Model-free MSS checks, retained-handle fixtures, hidden dev/portable/installed Windows runs and separate approved Codex delivery have distinct scopes. Record open failure and portability gates. |
| `SECURITY.md` | Says there is no permission enforcement or process supervisor. Describes an old local HTTP surface as the generic endpoint. | [Shared store](../../MSS_MCP/tools/mss_shared.py) and [launcher](../../MSS_MCP/tools/Start-MakepadMcp.ps1) enforce application-level ownership, admission, sharing and retained-handle cleanup. The same-user trust assumptions and absent OS sandbox remain. |
| `TESTING.md` | Gives a general regression list, but omits the retained-handle command and does not distinguish harness, native fixture and release evidence. | [PowerShell test](../../MSS_MCP/tests/Test-RetainedProcessIdentity.ps1), [Rust stdio test](../../MSS_MCP/tests/gui_tools.rs) and native fixtures have different prerequisites and assertions. Document the official upstream Makepad harness for compatible guest projects. |

## Source and verification boundaries

- `IMPLEMENTED`: native Desktop, guest-pixel capture and decode, Python MCP, admitted launch, per-App ID policy, shared attach/detach and explicit closure, profile and build policy, recording export.
- `PARTIAL`: addressed resize/input depend on guest/profile permissions, cleanup qualification is bounded, Codex CLI delivery was observed with a separate development build. Experimental/optional guests remain external. Installed release portability has a same-host result and open clean-host and redistribution gates.
- `SCAFFOLD`: Rust policy/transport/render/SDK APIs and the Rust MCP library are absent from the active Python guest runtime. `PLANNED`: any future Rust consolidation or protected execution remains separately scoped. `DEPRECATED`: the historical HTTP-as-guest-path and Toolkit-first design are retired guidance.

The review cross-checked the local release evidence named in [testing](../../doc/testing.md). The runtime evidence directory from prior runs stays outside this documentation checkout. Current edits only change documentation. [Historical design](../../doc/history/initial-architecture/README.md) and [Cronica](../../doc/cronica/0001-native-ui-scaffold.md) retain the original provenance.
