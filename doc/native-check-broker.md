# Native Windows check broker: implemented stage and qualification gaps

## Scope and current decision

Issue [#8](https://github.com/paulgreenbox-beep/makepad-sandstudio/issues/8) is continued in existing Draft [PR #9](https://github.com/paulgreenbox-beep/makepad-sandstudio/pull/9), based on dispatcher PR #7. This stage adds strict protocol binding and real Windows supervisor probes. It does not qualify execution of repository or agent-generated code. The production binary remains fail-closed and the Codex Issue dispatcher remains disabled.

`src/main.rs` accepts no command-line arguments, reads at most 64 KiB from stdin, and emits only fixed refusal codes on stderr. Its stdout remains empty and it never produces a check receipt or `PASS`. A valid request still exits with `BLOCKED` because controller authority, protected source import and network restrictions have not been qualified. The opt-in `native-probes` code is a separate library/test path for owner-controlled fixture images; it is not a production authorization mechanism.

## Source and dependency baselines

| Source | Exact baseline | Meaning |
|---|---|---|
| GOAL registry, PR #5 | `9c0e867f8844a6bc7949c7705db5c2cbbb65ef1c` | Existing `mss-goal-v1`, index and check catalog. |
| Dispatcher, PR #7 | `d83520d931ab000574c5c02192b9f49da86a34ea` | Existing request/receipt contract, disabled policy and separated controller/worker/publisher. |
| Initial broker foundation, PR #9 | `76d21f9be8a367715ee1b39ca7b31e79109f3526` | The previous non-executing request parser; not native execution evidence. |
| `windows-sys` | `0.61.2`; crate VCS `32c3144490c016fe496a0aed769bce60987a2e9d` | Cached Windows bindings, MIT OR Apache-2.0. |
| `sha2` | `0.10.9`; crate VCS `82c36a428f8d6f05f3bfccdedb243e9d1f85359d` | Cached digest implementation, MIT OR Apache-2.0. |

The standalone Cargo lockfile records actual registry resolutions and package checksums, including the existing serde/serde_json dependencies. The current implementation and test evidence must identify their own exact source commit; the baseline SHAs above do not prove a later binary. No Makepad, Toolkit or Dungeon source is copied or modified.

## Protocol and trust model

The wire formats remain `mss-native-check-request-v1` and `mss-check-receipt-v1`. Input is deserialized directly into strict typed structures, so duplicate recognized keys and unknown fields are rejected at request/check level. Typed catalog, manifest and GOAL readers apply the same rule; converting through a generic JSON map first would lose that duplicate-key protection and must not be used.

The request requires canonical positive decimal run ID spelling, a nonzero 40-character lowercase source SHA, one canonical `MSS-XXX` ID, and a lexically full Windows drive path. Relative paths, device/UNC spellings, traversal, alternate streams, reserved names and trailing-dot/space aliases are rejected. These are lexical checks, not filesystem canonicalization, a reparse proof or caller authentication.

`bind_request` compares the request to an independently obtained protected execution binding, the existing manifest/GOAL document, exact check metadata and literal argv in the approved scope/catalog. It requires the selected GOAL to be `IN_PROGRESS` with the expected branch and owner. It does not create a new task registry or weaken required checks. The real catalog IDs `CORE_TEST` and `WORKSPACE_CHECK` are used; invented aliases are not accepted as equivalents. Selected `command:null` entries such as `WINDOWS_DESKTOP` and `TOOLKIT_PARITY` are blocked as manual obligations.

The public binding API does not authenticate whoever constructs its expected context. Copying stdin into an `ExecutionBinding` would prove nothing. Production still needs a protected launch authority that binds caller identity, GOAL, attempt, source, repository object store, permitted commands and ownership generation. The stdin protocol itself contains no caller credential or authenticated session nonce.

## Native probe supervisor

The feature-gated supervisor constructs a restricted version of its own token with disabled maximum privileges, a deny-only Administrators SID, restricting SIDs and low integrity. It queries token groups, elevation, integrity and enabled privileges. The intended child must be suspended while the supervisor reads its actual token and verifies Job membership and Win32k mitigation before resuming it. This uses [CreateRestrictedToken](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken) and [CreateProcessAsUserW](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessasuserw). Neither the token-creation flags nor `IsTokenRestricted` alone establish complete isolation.

The image is opened without write/delete sharing, hashed, and identified by its file identity. Non-reparse ancestor handles are retained without delete sharing through launch. This prevents replacement of a pinned fixture file/object within the tested handle lifetime; it is not an immutable repository checkout or an audit of every loaded DLL.

Process construction uses an explicit executable path and separately quoted argument vector without a shell. `PROC_THREAD_ATTRIBUTE_JOB_LIST` associates the new process with its owned Job at creation, while `PROC_THREAD_ATTRIBUTE_HANDLE_LIST` admits only null stdin and the selected output pipe handles. The Job handle is not a general inherited capability. The implementation requests Win32k system-call disable mitigation and checks the actual child policy. See Microsoft's [process attribute documentation](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute).

The Job is configured for kill-on-close, at most four active processes, 128 MiB per-process memory, 256 MiB total Job memory and a 10% CPU hard cap. No breakaway flag is permitted. The implementation records PID and process birth time and uses retained handles for its own process tree. A Job configuration query proves the kernel object contains those limits; it does not prove resource-exhaustion behavior, descendant membership, cancellation or cleanup. [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects) describe lifetime/accounting controls; [Job security](https://learn.microsoft.com/en-us/windows/win32/procthread/job-object-security-and-access-rights) does not replace per-process security.

The intended probe desktop belongs to a newly created noninteractive station with a protected descriptor. It never chooses the user's default desktop. Microsoft requires special care with restricted applications on a shared desktop and documents that nonadministrators cannot select a station name. With a null name, Windows derives a name from the logon session; `CWF_CREATE_ONLY` refuses an existing station instead of returning it. The observed collision is therefore an explicit launch blocker, not permission to reuse or modify that station. See [CreateWindowStationW](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-createwindowstationw).

Stdout and stderr are drained concurrently and retained up to 64 KiB each; overflow or read failure marks output incomplete. Timeout/cancellation paths target only the owned Job and verify observed process termination/accounting before reporting cleanup. An incomplete stream, uncertain termination or remaining child cannot be normalized to successful check acceptance. These process paths still require successful end-to-end probes on the qualified host.

A dedicated service account alone is not a demonstrated solution to station error 183: its logon session may already have the system-generated station. This probe path requires successful create-only ownership. A future station provisioning/ownership lease or different native design requires independent review; this stage supplies no qualified station handoff and never opens an existing station as a fallback.

## What local observations establish

Development checks are observations at the recorded working source, not independent release/security acceptance. The PR receipt must bind final results to an exact commit and executable identity.

| Check | Observed result | Practical limit |
|---|---|---|
| Protocol/catalog/GOAL unit tests | PASS, 17 tests | Pure validation/binding tests; no native child is started. |
| `effective_restricted_token_has_observed_privilege_and_integrity_limits` | PASS | Real token queries on a newly created restricted token; not a complete child or network boundary. |
| `os_access_checks_deny_private_fixture_reads_and_writes_under_restricted_token` | PASS | Real `ImpersonateLoggedOnUser` thread access checks: private/sibling synthetic sentinel reads and a private write return `ERROR_ACCESS_DENIED` (5); allowed fixture access succeeds. This is not a separately launched child. |
| `job_limits_are_read_back_from_the_real_kernel_object` | PASS | Real Job configuration and empty accounting readback, not limit-exhaustion or descendant proof. |
| `consumed_attempt_is_denied_by_create_new_before_and_after_handle_loss` | Pending final source-bound result | A persistent create-new file fence is implemented and tested against repeated opens. Production root ownership, controller authentication and crash/recovery policy remain unqualified. |
| Supervisor child launch | FAIL / subsequent paths BLOCKED | An initial named-station attempt returned access denied. The nonadministrator null-name/create-only path then returned `ERROR_ALREADY_EXISTS` (183). No fallback to the existing station/default desktop/elevation is allowed. |
| Independent image-pin test | Pending source-bound result | Can run without child launch; do not infer its result from token or parser checks. |
| WFP/network and symlink integration cases | NOT_RUN | Explicit unmet prerequisites, not passing skipped coverage. |

The local CIM snapshot identified GIGABYTE AERO X16 hardware, Windows 11 build 26300 and a nonadministrator context, with `HypervisorPresent=true`. That flag can have more than one interpretation and does not independently qualify a physical runner or establish that no guest environment exists. No container, WSL, VM or Hyper-V execution environment was created for this stage. Independent physical-host qualification remains `NOT_VERIFIED`.

## Coverage of the required negative categories

Each row preserves the user's original obligation. A parser refusal is not presented as an OS denial.

| # | Required category | Current coverage and status |
|---|---|---|
| 1 | Unknown commands | PASS in pure catalog/scope binding tests; only exact approved metadata/argv can bind. No arbitrary command is executed. |
| 2 | Shell injection | PASS for pure rejection of shell tool substitution/altered argv. The supervisor uses no shell; adversarial child-process command-line proof remains NOT_RUN behind the launch blocker. |
| 3 | Executable-path substitution | Image digest/file identity/held handles implemented; independent real-file pin/share-denial test result must be recorded separately. No production executable registry is qualified. |
| 4 | Checkout substitution after validation | BLOCKED: protected source import and immutable exact-commit materializer are not implemented. The agent worktree is never accepted as source evidence. |
| 5 | Symlink/junction/reparse attacks | Lexical alias rejection and image ancestor reparse checks implemented. The symlink OS integration case is NOT_RUN pending fixture privileges; junction/full checkout attacks remain unqualified. |
| 6 | Write outside admitted directory | PASS only for real restricted-token thread denial of an owned private synthetic fixture. Separately launched child coverage is blocked; broad host isolation is NOT_VERIFIED. |
| 7 | Read secrets | PASS only for OS denial of owned synthetic private/sibling sentinels under impersonation. No real secrets were read. Parent memory, credentials, user-profile and all handle channels are not fully qualified. |
| 8 | Network outside policy | BLOCKED / NOT_RUN: no WFP/network enforcement is supplied. The opt-in test requires a trusted positive control to an actually listening owned loopback endpoint and an OS access-denied result; a closed port is insufficient. |
| 9 | Child processes | Job assignment/limits implemented and queried. Descendant child tests are NOT_RUN/BLOCKED at private-station creation, so inheritance/escape behavior is not proven. |
| 10 | Timeout and cancellation | Owned-Job timeout/cancellation logic implemented; successful launched-child negative evidence remains NOT_RUN/BLOCKED. |
| 11 | Loss of supervisor | A real fixture test retains verified PID/birth/image handles before terminating its own supervisor, but this path is blocked at launch. NOT_RUN for child-lifetime acceptance. |
| 12 | Incomplete cleanup | Synthetic ACL fixture cleanup is observed within its test. Job/process-tree drain, incomplete output and abnormal teardown cases remain unqualified while launch is blocked. |
| 13 | Repeated attempt | Canonical run-ID/foreign expected-context rejection passes pure tests. A persistent create-new fence primitive is implemented; its independent final run result must be recorded. The protected production root, authenticated grant and recovery binding are not qualified; repeated execution is not enabled. |
| 14 | Receipt substitution/reuse | BLOCKED: production emits no receipts. Protected evidence storage/authenticity and independent retrieval/signing still need implementation and qualification; digest-shaped strings alone prove nothing. |
| 15 | Neighbor session resources | Real restricted-token thread denial is observed for an owned synthetic sibling file. Separate identities, profiles, process/memory handles and complete neighboring-session isolation remain NOT_VERIFIED. |

Low integrity is not a confidentiality boundary by itself. Microsoft's [Mandatory Integrity Control](https://learn.microsoft.com/en-us/windows/win32/secauthz/mandatory-integrity-control) documents separate mandatory policies; its default write restriction must not be advertised as proof that all higher-integrity data is unreadable. The restricting SID/DACL observations above cover only their declared synthetic objects.

## Source, replay and receipt work still required

The dispatcher invokes the broker before pushing the newly committed source. A normal protected remote mirror does not yet contain that commit. Production needs an authenticated, bounded object import into a protected store and then a broker-owned clean materializer that verifies the commit, trusted repository identity, tree/object integrity and resulting files. It must not execute Git using an agent-controlled `.git` configuration, hooks, filters, alternates or URL, copy untracked/ignored files, or reuse an agent-modified `target` directory.

The materialized tree must be protected against changes throughout checks, and each allowed logical tool name must resolve to a reviewed fixed executable identity. Its own controlled runtime/DLL dependencies require qualification. A later source mutation invalidates applicability of old receipts rather than changing or deleting historical evidence.

A persistent create-new attempt-fence primitive exists, but it is not connected to production execution. Its caller must supply a controller-owned private root; creating a file does not establish that root's authority. The production journal still needs authenticated GOAL/run/source binding, protection against concurrent callers, crash/recovery policy and explicit unknown outcomes. Stdin field shape is not freshness proof. The full control/worker identity handoff must be authenticated before any check is resumed; caller-provided paths and IDs cannot become authority by comparison to copies of themselves.

Only a qualified executor may produce `mss-check-receipt-v1`. Receipts must preserve exact GOAL/run/source/check/argv, runner identity, times, exit/result and verifiable evidence digests. `CORE_TEST` also requires the catalog's real test summary. The production broker must distinguish failed start, timeout, cancellation, truncated output, uncertain cleanup and unknown termination. It must not replay a potentially mutating check after an uncertain result.

Raw potential secrets, absolute private host paths and arbitrary model/check output must not be published. Evidence needs a protected ownership-bound store and verifiable content references; signatures or an equivalently qualified trusted transport must prevent substituted receipts. This stage does not implement that production store or receipt authenticator.

## Independent native qualification and safe continuation

1. Preserve PR #9 and its dependencies #5/#7. Review exact commits, lockfile, API usage and source-bound results; do not merge automatically.
2. Use an independently attested physical Windows runner with dedicated nonadministrator execution identity and profile, protected controller/broker/config namespaces and explicit permissions. Do not add an administrative child or reuse the personal desktop to bypass the station blocker.
3. Resolve the private noninteractive station/logon-session ownership design using separately reviewed provisioning. Existing station reuse, default-desktop fallback, Job breakaway and weaker tokens are not acceptable recovery paths.
4. Implement and qualify protected source import/materialization, authenticated invocation, durable replay fencing and immutable evidence. Do not promote probe output to production check receipts.
5. Provision and prove OS network restrictions separately. Test an actual listening owned endpoint with a positive trusted control and a denied restricted connection; preserve error codes. No network-policy acceptance comes from a parser, token, Job or connection-refused result.
6. Run every category above with real negative OS probes where the obligation is an OS boundary. Keep unmet prerequisites, failures and unexecuted cases explicit. No mock may replace those proofs.
7. Verify owned process birth/image/handle identity, inherited handle exclusion, caller/child credentials, native limits, descendants, cancellation, supervisor loss, output bounds and cleanup. Do not inspect or signal foreign processes.
8. Keep the dispatcher disabled. Do not install Secrets, change `MSS_CODEX_ENABLE`, alter main protection or spend model tokens as part of this stage. A later owner decision and independent qualification are required before connecting production checks.

No Docker, container, WSL/WSLC, VM, GLIF/GLYF or external-project modifications form part of this implementation or its proposed qualification path.
