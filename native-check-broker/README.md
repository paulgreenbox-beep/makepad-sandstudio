# MSS Native Windows Check Broker — protocol and native probe stage

This is a partial, reviewable implementation for Issue #8 and existing Draft
PR #9. It is **not a qualified repository-code executor**. The production
`mss-native-check-broker` entry point reads bounded typed dispatcher-v1 requests
and remains `BLOCKED`, including for valid JSON. It launches no Git/check
process and emits no receipts or `PASS` on stdout. Do not install this binary as
the dispatcher policy's qualified `check-broker.exe`.

The separate opt-in `native-probes` feature implements Windows supervisor
primitives and separate owner-controlled child/supervisor fixture images. It is not connected to stdin
requests. It must not be used to route model-provided code or argv into native
execution. See [the design, actual results and 15-category coverage matrix](../doc/native-check-broker.md).

At tested source `0932ba368e7cdd5d21cee03609cd36b7a0fcb62f`, metadata, formatting,
all-target checking and default tests passed: 17 protocol tests and three real
production-refusal tests. Feature all-target checking and 24 feature library
tests passed (17 protocol plus seven real OS primitive tests). The native
integration suite passed all ten active tests; the network/symlink cases remain
`NOT_RUN` (two existing ignored prerequisites). Dispatcher compatibility tests
passed 80 cases. See [current source-bound evidence](evidence/20261030-station-fix.json).
The earlier station error 183 / secondary EOF result (one passed, eight failed,
two ignored at `1a52fff0a894bdf19138ed1184c1d32b5ac94794`) remains preserved in
[historical development evidence](evidence/20261030-development.json).
Neither result qualifies production execution or full OS isolation.

## Implemented boundary

- Strict `mss-native-check-request-v1` parsing, canonical identifiers and exact
  binding to typed existing GOAL/catalog documents and a protected-context API.
- Probe-only restricted token with low integrity; token facts are queried rather
  than inferred from creation flags.
  RC/World/Users restricting SIDs are retained with a fresh per-Run nonce SID.
  Only the restricted token copy's DefaultDacl gains that nonce ACE for future
  objects; existing ACEs, the source token and station/foreign ACLs remain unchanged.
  A nonce marker is not an independently authenticated Windows identity.
  Synthetic ACL denials do not establish full neighboring-session isolation.
- Image digest/file identity and held non-reparse image/ancestor handles.
- Suspended process construction with explicit inherited handles, atomic Job
  assignment and observed Win32k mitigation. `DETACHED_PROCESS` avoids an extra
  console host while retaining the selected standard handles. The restricted
  child is separate from the supervisor and has no direct USER32/GDI32/WIN32U imports.
- A unique owned private desktop in the unchanged current window station,
  not a separate noninteractive station. Owner/nonce DACL and low label are read
  back; collisions are refused, `UOI_IO` is false and controlled close is proved
  by failed reopen. No station/desktop switching API or user Default desktop is used.
- Actual child startup `lpDesktop` and Win32k policy are checked. A NULL
  `GetThreadDesktop` query is recorded as unavailable (`child_connected_desktop`
  and `child_desktop_query_win32`), with actual USER32 association `NOT_VERIFIED`.
- Owned Job limits, real child file denials, inherited-handle exclusion,
  environment filtering, descendants, timeout/cancellation, peer Job survival,
  bounded output and controlled owned-tree/desktop cleanup. Supervisor-loss
  tests prove verified-child termination, not crash-desktop disappearance.
- A persistent create-new attempt-fence primitive. Its filesystem behavior does
  not authenticate the caller or qualify the future protected production journal.

The old create-only station blocker is resolved by creating only the owned
desktop in the unchanged current station. The pre-main `0xC0000142` failure is
resolved by the restricted copy's nonce DefaultDacl grant, without relaxing token
or mitigation checks. No `SetProcessWindowStation`, `SetThreadDesktop` or
`SwitchDesktop` call is used, and no existing station ACL is changed. Shared
station globals and hostile same-user processes remain outside the qualified
boundary. Production execution stays blocked for source, identity, profile,
filesystem, network and receipt prerequisites.

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
credentials or another session. Seven native primitive tests and ten active
integration tests do not establish complete secret isolation, Toolkit parity or
independent physical-runner qualification; these remain `NOT_VERIFIED`. No dispatcher,
Secrets, `MSS_CODEX_ENABLE`, `main` protection or merge setting is enabled here.

Dependencies: PR #5 (existing GOAL registry), PR #7 (disabled dispatcher), Issue #8.
Continue PR #9 rather than creating a competing implementation.
