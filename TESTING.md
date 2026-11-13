# Windows verification

Use a native Windows x64 checkout with the prerequisites in [BUILDING.md](BUILDING.md). Set `MSS_TEST_PYTHON` to an absolute path to trusted Python 3.12+. Run the commands in order from the repository root. Omit `--offline` when the exact locked Cargo dependencies are not already cached.

```powershell
cargo metadata --format-version 1 --locked --offline
cargo fmt --all -- --check
cargo check --workspace --all-targets --locked --offline
cargo test --workspace --all-targets --locked --offline
cargo clippy --workspace --all-targets --locked --offline -- -D warnings
cargo build --workspace --release --locked --offline
& $env:MSS_TEST_PYTHON -I -B -m unittest discover -s MSS_MCP/tests -p 'test_mss_*.py'
```

Run the [retained process test](MSS_MCP/tests/Test-RetainedProcessIdentity.ps1) with trusted PowerShell 7.4+. Set `MSS_PWSH_EXE` to its absolute path. The test creates its own subdirectory under the evidence root.

```powershell
$evidence = Join-Path (Get-Location) 'proof/retained-process-check'
New-Item -ItemType Directory -Path $evidence -Force | Out-Null
& $env:MSS_PWSH_EXE -NoProfile -NonInteractive -File MSS_MCP/tests/Test-RetainedProcessIdentity.ps1 -Launcher MSS_MCP/tools/Start-MakepadMcp.ps1 -EvidenceRoot $evidence
```

Use admitted owned hidden processes for native guest checks. Start from [configuration](CONFIGURATION.md) and bind every test to the exact app and Remote pins, PID/birth identity, window and observed outcome. For a guest source workspace that supports the official harness, use its existing `libs/makepad_test` crate and `#[makepad_test]`. For example, in a compatible Makepad workspace with the Todo tests:

```powershell
cargo test --release -p makepad-example-todo --test ui -- --test-threads=1
```

Use an isolated test data root and retain receipts and evidence. Keep model delivery and GUI/runtime verification separate from the default regression suite. [Contracts and observed results](doc/testing.md)
