# MSS Native Windows Check Broker — protocol and native probe stage

This is a partial, reviewable implementation for Issue #8 and existing Draft
PR #9. It is **not a qualified repository-code executor**. The production
`mss-native-check-broker` entry point reads bounded typed dispatcher-v1 requests
and remains `BLOCKED`, including for valid JSON. It launches no Git/check
process and emits no receipts or `PASS` on stdout. Do not install this binary as
the dispatcher policy's qualified `check-broker.exe`.

The separate opt-in `native-probes` feature implements Windows supervisor
primitives and an owner-controlled probe image. It is not connected to stdin
requests. It must not be used to route model-provided code or argv into native
execution. See [the design, actual results and 15-category coverage matrix](../doc/native-check-broker.md).

At tested source `1a52fff0a894bdf19138ed1184c1d32b5ac94794`, required formatting,
all-target checking and default tests passed: 17 protocol tests and three real
production-refusal tests. Feature all-target checking passed, and the feature
library tests passed 21 cases (17 protocol plus four real OS primitive tests).
The complete native integration suite **failed**: one image-pin test passed,
eight child-path tests failed behind station creation/secondary EOF blockers,
and the network/symlink cases were `NOT_RUN` (two ignored prerequisites).
Dispatcher compatibility tests passed 80 cases. See the
[source-bound development evidence](evidence/20261030-development.json);
none of these results qualifies production execution.

## Implemented boundary

- Strict `mss-native-check-request-v1` parsing, canonical identifiers and exact
  binding to typed existing GOAL/catalog documents and a protected-context API.
- Probe-only restricted token with low integrity; token facts are queried rather
  than inferred from creation flags.
  Its RC/World/Users restricting SIDs are common SIDs, not per-session principals.
  Synthetic ACL denials do not establish full neighboring-session isolation.
- Image digest/file identity and held non-reparse image/ancestor handles.
- Suspended process construction with explicit inherited handles, atomic Job
  assignment, Win32k mitigation and a private noninteractive station/desktop.
- Owned Job limits, bounded output, timeout/cancellation and owned-tree cleanup
  logic. These implementation paths are not equivalent to successful child-process
  integration tests.
- A persistent create-new attempt-fence primitive. Its filesystem behavior does
  not authenticate the caller or qualify the future protected production journal.

The observed child-launch probe currently refuses to reuse an existing system
logon station (`ERROR_ALREADY_EXISTS`, 183). It does not fall back to the user
desktop, an existing station, breakaway, elevation or a weaker token. Production
execution remains blocked for additional source, identity and network reasons.

## Checks

The crate is standalone, so these commands do not build the Makepad workspace:

```powershell
cargo fmt --manifest-path native-check-broker/Cargo.toml -- --check
cargo check --manifest-path native-check-broker/Cargo.toml --all-targets
cargo test --manifest-path native-check-broker/Cargo.toml
```

The cheapest protocol proof is:

```powershell
cargo test --manifest-path native-check-broker/Cargo.toml --lib protocol::tests --offline
```

On an independently approved Windows host, the opt-in native checks are:

```powershell
cargo test --manifest-path native-check-broker/Cargo.toml --features native-probes --lib native::tests --offline -- --nocapture
cargo check --manifest-path native-check-broker/Cargo.toml --features native-probes --all-targets --offline
cargo test --manifest-path native-check-broker/Cargo.toml --features native-probes --test native_windows --offline -- --test-threads=1
```

These are real OS tests using only owned images, processes, synthetic sentinels
and temporary directories. Preserve failures. The WFP/network and symlink cases
declare unmet prerequisites and are `NOT_RUN`; do not use `--ignored` or change
host security settings merely to obtain a green suite. Detailed results and their
limits must accompany the exact source SHA in the PR evidence.

## Remaining production prerequisites

Caller authentication, a protected launch grant and durable replay authority,
safe import of the new source commit, an immutable clean checkout materializer,
separate execution identity/profile, network enforcement, protected evidence and
receipt authenticity are not qualified. The existing `mss-check-receipt-v1`
format is unchanged, but this production entry point does not mint receipts.

Restricted tokens and Jobs do not by themselves isolate filesystem, network,
credentials or another session. Local kernel probes do not establish complete
secret isolation or independent physical-runner qualification. No dispatcher,
Secrets, `MSS_CODEX_ENABLE`, `main` protection or merge setting is enabled here.

Dependencies: PR #5 (existing GOAL registry), PR #7 (disabled dispatcher), Issue #8.
Continue PR #9 rather than creating a competing implementation.
