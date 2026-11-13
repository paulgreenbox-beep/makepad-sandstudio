# MSS failed-launch reconciliation and loaded-source identity

> **Historical verification record.** The source-only scope and PR state below describe the original check. See the [current preview architecture](architecture.md) and [current verification commands](../TESTING.md).

## Source boundary

This Draft source change starts at main
`83ff50112fbbdc1cd2a43ccd2ac1650504394a67`. Main contained only the Rust MCP
placeholder. Therefore the first commit publishes the existing local connector
as an explicit prerequisite: five Python modules and the PowerShell launcher,
plus the original model-free tests for build, shared-state and transfer policy.
The next commit contains the lifecycle/identity repair and its tests.

This is deliberately **source-only**: it changes no live catalog, executable,
Makepad SDK, Codex configuration, MCP connection or application. It does not
implement popup selection. PRs #1–#5, #7 and #9–#14 are not rebased, overwritten,
merged or closed. In particular this connector is not an import of the disabled
dispatcher or Native Check Broker.

The prerequisite includes pre-existing GUI routing, build selection, shared
queue and Writer transfer logic because the router imports those helpers.
These are disclosed prerequisite sources, not newly accepted features. The
Python router currently orchestrates these calls itself instead of using the
planned MSS_API. Resolving that architectural boundary requires a separate PR;
the Rust placeholder continues to report `NotImplemented`.

## Lifecycle contract

The launcher retains the `Process.Start` handle. It obtains PID and creation
FILETIME using `GetProcessId`/`GetProcessTimes`, queries the image with
`QueryFullProcessImageNameW`, and allows at most 2000 ms for image readiness.
There is no `MainModule.FileName`, unbounded retry, name-based process lookup,
global desktop input or automatic mutation replay.

The receipt records the pinned intended EXE/SHA, actual image (or null if never
observed), PID, birth identity, launcher/session binding, child state and exit
proof from the same retained handle. A missing observation is not invented.

| State | Required meaning |
| --- | --- |
| `CLOSED` | Qualified startup, observed image, graceful app/client exit and complete log capture. |
| `FAILED_CLOSED` | Startup/admission/lifecycle failed, but retained-handle evidence confirms owned processes exited. This is not a GUI test PASS. |
| `CLEANUP_PENDING` | Exit, ownership or client cleanup remains unconfirmed or contradictory. Preserve the original failure. |

`mss_recheck_cleanup(app_id)` is observational with respect to processes: it
does not send quit, kill or repeat UI operations. It may append reconciliation
evidence for a previous launch in the operator-owned MSS evidence root. It
requires the exact generated App ID and consistent materialized profile,
session directory, receipt hashes and process binding. PID absence alone never
qualifies cleanup; a replacement process is not signalled. A still-live original
process or unavailable identity query remains pending. Rechecking an already
reconciled record is idempotent. Originals are preserved, including earlier
failure labels, and a sidecar records the effective classification.

The private, one-off legacy migration from the original development machine is
**not distributed**. There is no admitted legacy launcher hash in this source.
A pre-modern receipt without bound exit proof stays `CLEANUP_PENDING` with
`LEGACY_LAUNCHER_PROVENANCE_NOT_VERIFIED`. Copying an old script or cached
terminal label cannot authorize it. A separate operator-reviewed migration is
required; this PR does not grant general cross-installation cleanup authority.

Receipts and the shared SQLite index are trusted **local operator-owned files**,
not cryptographically signed OS attestations. Another process with the same
user's write access can alter them. Addressed input and retained handles do not
provide OS isolation, descendant containment or supervisor-loss guarantees.

## Loaded-source identity

Read-only `mss_server_info` returns the server PID/birth time, connection ID,
version, optional startup Git HEAD metadata, capture timestamp, per-file SHA-256
and aggregate SHA-256. Separate protocol fields report the actual negotiated
`initialize.protocolVersion`, supported versions and MCP `serverInfo.version`;
they are not confused with the MSS package version. Negotiation does not change
the frozen source manifest. It does not expose Remote secrets or document contents.

At the actual stdio entry point, bytes of `mss_universal.py`, `mss_profiles.py`,
`mss_builds.py`, `mss_process.py` and `mss_shared.py` are captured before local
imports. The entry point executes its captured bytes, and a restricted loader
compiles helper imports from those same captured buffers. The saved manifest is
returned unchanged even if disk files later change. Each new connection gets
its own PID/connection identity and independent startup capture.

This is a runtime source measurement, not signed attestation or an atomic Git
tree snapshot. The initial capture wrapper, Python interpreter/stdlib/native
modules and external launcher/Remote/app executables are outside that manifest.
Launcher and executable admission use separate pins. Optional app-specific
bootstrap code is separately pinned, not included in these five core hashes.
Git HEAD is metadata and explicitly `commit_is_runtime_revision: false`.
An imported test context is marked `NOT_ATTESTED`. An old unversioned connection
cannot be retroactively identified by hashing current disk files; reconnecting
it is a separate operator action, never automatic in this PR.

## Operator-owned setup

Requirements: native Windows, an already approved Python runtime and PowerShell
7.4+, and separately admitted official Makepad Remote/app binaries when live
checks are authorized. No third-party Python dependency or installer is added.

For a **new isolated checkout**, copy `MSS_MCP/profiles/apps.example.json` to the
ignored `MSS_MCP/profiles/local.apps.json`. Set `pwsh_executable` to the approved
absolute local path. Do not copy this example over a live catalog. Hash the
approved PowerShell and launcher into `pwsh_sha256` and `launcher_sha256` before
adding any profile. There is no executable PATH fallback. Existing catalogs
without `pwsh_executable` retain their bundled-runtime layout; admission still
checks the PowerShell SHA before a launch.

```powershell
# Read-only hashes; write approved values into the new local catalog manually.
Get-FileHash -LiteralPath $approvedPwsh -Algorithm SHA256
Get-FileHash -LiteralPath ./MSS_MCP/tools/Start-MakepadMcp.ps1 -Algorithm SHA256
& $approvedPython -I -B ./MSS_MCP/tools/mss_universal.py
```

The example has no profiles and cannot launch an app. App catalogs, profile
templates, build roots, SHA pins and optional bootstrap are operator trust
inputs; they are not supplied by an MCP client. This PR neither supplies nor
activates RudraOffice/ONLYOFFICE/Todo profiles. Do not change pins merely to hide
a drift failure. Follow the existing launcher profile validation before live
execution. The local catalog and all runtime/evidence directories are ignored.

## Reproducible bounded checks

Use already approved runtimes; do not install/upgrade software. Choose an
ordinary writable task-only temporary root if Windows's restricted default temp
cannot support the filesystem negatives. Preserve a failed first attempt.

```powershell
$env:TEMP = $taskOnlyTemporaryRoot
$env:TMP = $taskOnlyTemporaryRoot
& $approvedPython -B -m unittest discover -s MSS_MCP/tests -p 'test_mss_*.py' -v
& $approvedPwsh -NoProfile -NonInteractive -File ./MSS_MCP/tests/Test-RetainedProcessIdentity.ps1 -Launcher ./MSS_MCP/tools/Start-MakepadMcp.ps1 -EvidenceRoot $taskEvidenceRoot
cargo fmt -p mss-mcp -- --check
cargo test -p mss-mcp --test gui_tools --locked --offline -- --test-threads=1
git diff --check
```

Set `MSS_TEST_PYTHON` to the approved Python path for the Rust stdio test. The
Python suite covers cleanup refusal/exit classification, repeat reconciliation,
neighbor preservation, original build/shared/transfer contracts, real copied
stdio startup identity and explicit operator runtime selection. The native
helper check spawns only its own fast-exit PowerShell fixture; the Rust check
starts a copied empty-profile MCP and sends negative contract requests. Neither
launches Makepad, reads a document, spends model tokens or changes live settings.

The complete launcher/Remote/app lifecycle, actual profiles, GUI/GPU capture,
popup behavior, crash containment, multi-agent OS security and full unchanged
Toolkit acceptance require separate evidence-backed gates. They remain
`NOT_RUN`/`NOT_VERIFIED` for this source-only publication, regardless of passing
policy and stdio tests. No production activation is requested.
