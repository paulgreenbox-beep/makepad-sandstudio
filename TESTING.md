# Windows verification

Run in order from a fresh source checkout. Set `MSS_TEST_PYTHON` to a trusted absolute Python 3.12+ executable.

```powershell
cargo fmt --all -- --check
cargo check --workspace --all-targets --locked --offline
cargo test --workspace --all-targets --locked --offline
cargo clippy --workspace --all-targets --locked --offline -- -D warnings
cargo build --workspace --release --locked --offline
& $env:MSS_TEST_PYTHON -I -B -m unittest discover -s MSS_MCP/tests -p 'test_mss_*.py'
```

Run the retained process-identity test using PowerShell 7.4+, the exact launcher path and a new evidence directory. Native tests need separately admitted guest builds, owned hidden processes and independent semantic/PNG readback. Keep exact source, app/Remote pins, PID, window, exit code and cleanup receipts. [Detailed verification](doc/testing.md)
