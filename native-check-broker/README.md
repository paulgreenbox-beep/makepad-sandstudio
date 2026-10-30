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

At tested source `d8decfd362c107f28fed552bc779ce2d4d2f4c9f`, metadata, formatting,
all-target checking and default tests passed: 17 protocol tests and three real
production-refusal tests. Feature all-target checking and 24 feature library
tests passed (17 protocol plus seven real OS primitive tests). The native
integration suite passed all ten active tests; the network/symlink cases remain
`NOT_RUN` (two existing ignored prerequisites). Dispatcher compatibility tests
passed 80 cases. All ten final check commands passed. See
[current source-bound evidence](evidence/20261030-crash-user32.json).
The earlier passing `0932ba368e7cdd5d21cee03609cd36b7a0fcb62f` results remain in
[historical station-fix evidence](evidence/20261030-station-fix.json).
The earlier station error 183 / secondary EOF result (one passed, eight failed,
two ignored at `1a52fff0a894bdf19138ed1184c1d32b5ac94794`) remains preserved in
[historical development evidence](evidence/20261030-development.json).
These results do not qualify production execution or full OS isolation. Two
intermediate uncommitted full-suite runs failed descendant fixture cleanup,
including one Windows error 5. These outcomes are recorded in development notes;
retained fixtures were left untouched, without deletion retries. The final fix adds real retained-process termination waits;
no cleanup assertion is weakened, and no exact failing-file cause is claimed.

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
  back and their creation SDDL hash pinned; collisions are refused, `UOI_IO` is false and controlled close is proved
  by failed reopen. No station/desktop switching API or user Default desktop is used.
- Actual child startup `lpDesktop` and Win32k policy are checked. The follow-up
  validates actual READY PID/TID and token/Job facts, retains the primary thread,
  and checks liveness/Win32k/parent context before and after an external query.
  READY is limited to an eight-KiB first line and a five-second wait. The borrowed
  post-READY `GetThreadDesktop` query occurs only in the disposable crash supervisor, never
  a long-lived test parent. After READY it still returns NULL/error 0:
  `MSS_USER32_QUERY status=QUERY_UNAVAILABLE win32=0 association_required_result=BLOCKED`.
  Actual USER32 association remains `NOT_VERIFIED`; correct refusal is not
  association PASS. No forced GUI connection or mitigation relaxation is used.
- Owned Job limits, real child file denials, inherited-handle exclusion,
  environment filtering, descendants, timeout/cancellation, peer Job survival,
  bounded output and controlled owned-tree/desktop cleanup. Retained member
  read/query-and-synchronize handles are verified against the exact Job, waited
  together with the primary within a shared three-second deadline, then accounting
  must be zero. The descendant test requires at least two signalled handles;
  no enumerated PID becomes a kill target. Arbitrary new-spawn races remain unqualified.
- Crash cleanup now proves the exact private desktop existed in the unchanged
  current station, with pinned owner/DACL/label hash and `UOI_IO=false`, then
  disappeared after supervisor/child death and explicit noninherited observer
  witness release: `MSS_CRASH_DESKTOP before_exists=true after_absent=true`.
  The child has a fixed twenty-second hold independent of EOF; kill begins below
  ten seconds, supervisor/child waits are bounded to five seconds each, and child
  death must precede its natural exit. After witness close, a three-second
  `OpenDesktop` poll accepts only error 2 as absence. This is a bounded owned
  fixture proof, not instantaneous destruction while observers hold handles or
  complete production crash-recovery qualification.
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
