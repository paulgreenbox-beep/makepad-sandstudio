# Product source follow-up: #10 foundation + repaired #11 + independent #12

## Included exact inputs

- Product integration #10: `8863cc326b99f8d76b2bf66725d87540aab79f02`.
- Remote follow-up #11: `6875f66daa6f5241a96a9bf741e7f72f132b95ba`.
- Boundary hardening #12: `61cbe626ae5601d9294ee07713b4b8f20438b60d`.

This is a combined review tree, not a merge to main and not a released runtime.
It preserves the source histories without rewriting or closing the existing PRs.
The README keeps #10's implemented logical-module state rather than replacing it
with #12's older main-based placeholder description.

## Corrections now present

Remote's NBSP/em-space regression uses real Rust Unicode escapes, with the old
assertions retained. Three additional public-interface tests cover every intent,
both submission methods, text payload preservation and authorization/cancellation
precedence. No native transport or execution outcome is fabricated.

The scope checker now rejects nested CWG implementation imports and declared
Cargo dependency aliases/paths/sources, including target/build/dev/workspace/patch
and lockfile entries. It prevents removing required equivalent native checks,
uses bounded strict input reads, validates graph containers and preserves history
without mutable aliasing. Original policy/input pins and old tests are unchanged.

MSS acceptance is independent of CWG dispatcher/Broker availability. It still
requires MSS-V00's independently reviewed native identity, file/network/process,
evidence and cleanup guarantees. No automatic developer worker, credential or
model service is installed. MSS_Core/API/Remote/Render/SDK/MCP/Desktop/Skills,
project goals and the full unchanged Toolkit contract remain MSS.

## Actual verification vs required verification

| Check | Result |
|---|---|
| Original Python scope tests | PASS: 14, preserved unchanged |
| Final Python scope/boundary suite | PASS: 37, zero failures/skips, Linux/Python 3.13.5 |
| Six pinned real master-plan inputs and effective-plan equality | PASS: 112 operations / 54 invariants / 68 checks preserved |
| Python compile and changed-file whitespace checks | PASS |
| Published file identities vs locally checked/tested source | Compared by Git blob hashes |
| New Remote Rust tests / rustfmt / Clippy / debug / release | NOT_RUN: toolchain absent |
| Complete combined workspace compilation and tests | NOT_RUN |
| Real Windows process/IPC/GPU/frame/cleanup | NOT_RUN / NOT_IMPLEMENTED |
| Toolkit full runtime parity | NOT_VERIFIED |

The expected Rust test inventory is **48**, not 48 observed passes: #10's 44,
#11's repaired existing regression and three new public-interface tests. Older
scope documentation's expected 45 predates those three additions. Preserve the
historical #11 FAIL and #10 PASS reports exactly; neither is a new combined result.

Detailed records: [Remote](cronica/pr11-remote-admission-followup.md),
[scope](cronica/pr12-scope-hardening.md). Python symlink/hardlink checks used Linux
fixtures, not Windows ACL qualification. The static guard is not exhaustive
malicious-code analysis and not a substitute for Cargo or native acceptance.

## Manual recheck sequence

Use an owner-approved, quiescent native Windows checkout and the existing locked
cache. Missing prerequisites are BLOCKED/NOT_RUN; do not install or weaken gates
implicitly. Run serially:

```powershell
python -m unittest discover -s scripts/tests -p "test_mss_scope*.py" -v
python scripts/mss_scope.py --source <extracted-reviewed-plan> --repo . --output <new-output.json>
cargo metadata --format-version 1 --locked --offline
cargo fmt --all -- --check
cargo test -p mss-remote --all-targets --locked --offline
cargo check --workspace --all-targets --locked --offline
cargo test --workspace --all-targets --locked --offline
cargo clippy --workspace --all-targets --locked --offline -- -D warnings
cargo build --workspace --locked --offline
cargo build --workspace --release --locked --offline
git diff --check
```

Record the exact tested commit, platform/toolchain, command exit codes, test
counts and log hashes. Never turn the expected inventory into observed results.
No workflow, scheduler, watcher or privileged executor is enabled by this change.

## Next implementation boundary

The next native work remains one trusted fixed Makepad application, an owned
process and a protected frame channel with source/process/session/epoch/sequence
checks, followed by two-session evidence. Code that merely labels a frame or
launches an unprotected loopback endpoint is not that proof. No blind UIA/global
input fallback, arbitrary app launch, container or VM is introduced here.

Stop/GO decisions must use actual native observations. A source-only check cannot
qualify process ownership, GPU readback, native focus or noninteractive execution.
