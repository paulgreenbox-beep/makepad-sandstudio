# Makepad and runtime compatibility

## Windows preview pins

| Role | Revision or prerequisite | Scope |
| --- | --- | --- |
| MSS source preview | `release/0.1.0-preview.1`, baseline `04ea3c52d5777adcbd9e36f0bf18572836d1d120` | Windows developer preview. [Source baseline](https://github.com/paulgreenbox-beep/makepad-sandstudio/tree/04ea3c52d5777adcbd9e36f0bf18572836d1d120) |
| Desktop Makepad | `130be1d0318adcf69453d925342607466353152c` | Cargo pin for `makepad-widgets`; `2.0.0` is the crate version. [Manifest](../MSS_Desktop/Cargo.toml) · [Lockfile](../Cargo.lock) |
| Tested external RudraOffice guest and Remote | Makepad `work` revision `2271c0eb350cedd497c84373f17ad2b0b662cb72`, exact per-EXE SHA-256 in test evidence | External guest admission. Other builds, including AI CAD and optional workers, have separate profile/configuration contracts and coverage. [Native launcher](../MSS_MCP/tools/Start-MakepadMcp.ps1) · [Testing](testing.md) |
| Desktop build | Native Windows x64, MSVC, Windows SDK, tested Rust `1.97.1` | Build tooling. [Build instructions](../BUILDING.md) |
| Router and launcher | External CPython `3.12+`, PowerShell `7.4+` | Router uses the Python standard library. PowerShell and launcher are pinned in the profile catalog. The local MSI prerequisite candidate was exercised with standalone CPython `3.14.10` and PowerShell `7.6.10`. [Configuration](../CONFIGURATION.md) |
| Recording handoff | Operator-installed, authenticated Codex CLI | Optional. The dev delivery test used `0.167.0-alpha.4.1`; compatibility with other versions is unverified. [Handoff implementation](../MSS_Desktop/src/codex_handoff.rs) |

Desktop's Cargo pin and a guest's declared Makepad revision are separate. Match the native Remote executable to the guest that produced its discovery and protocol. A branch name, a crate version or a successful compile does not establish guest protocol or capability compatibility.

## Native guest transport

The active Windows launch starts the admitted guest with `--remote` and hidden mode. The guest provides per-session discovery with a loopback TCP address and token. MSS validates the receipt and discovery, calls the official `makepad-remote app <pid> status`, then uses the official client in `makepad-remote mcp <pid>` stdio mode. A directly attached participant uses the same native app and has a separate client. [Launcher](../MSS_MCP/tools/Start-MakepadMcp.ps1) · [Router](../MSS_MCP/tools/mss_universal.py) · [Pinned Makepad Remote source](https://github.com/makepad/makepad/blob/2271c0eb350cedd497c84373f17ad2b0b662cb72/libs/remote/src/carrier/unix.rs)

Earlier Makepad HTTP research and any Desktop-side test inspection endpoint describe different surfaces. The old HTTP guest path is historical guidance. Native capture sends guest-rendered PNGs for decoding by Desktop. Hosted child surfaces and Linux GPU sharing remain separate research paths. [Historical source research](history/initial-architecture/compatibility.md)

## Evidence and change policy

- Record source revision and app/Remote executable hashes when admitting a new guest. Verify discovery and identity, the advertised tool set, addressed input/resize where enabled, a real native frame and owned closure on that exact build.
- Record and independently test changes to pinned dependencies, declared features, supported operating systems, package assets or resource lookup. The original RC2 payload omits its font files; same-host runtime verification does not establish clean-machine portability. [Limitations](../KNOWN_LIMITATIONS.md)
- The earlier Toolkit, Script API and Scheduler research remains reference material. Current MSS verification uses its own regressions and applicable official Makepad UI tests. Full Toolkit parity remains unverified. [Current checks](testing.md) · [Historical test plan](history/initial-architecture/testing.md)
