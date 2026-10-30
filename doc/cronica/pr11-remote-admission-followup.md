# PR #11: repair Unicode fixtures and extend addressed admission coverage

Parent source: `192b81ac83cfa3945318804430af25b3795609ad`.
Integration base: `8863cc326b99f8d76b2bf66725d87540aab79f02` (PR #10).

The previous regression used doubled backslashes, passing literal `\u{00a0}`
and `\u{2003}` characters rather than Unicode whitespace. The test expectation
was wrong. The fixture now uses Rust Unicode escapes, with the same original
assertions and test name. Known formatting defects in that added block are also
corrected manually; a real rustfmt run remains required.

No production execution path or error precedence changed. WidgetTarget's public
comment now documents the already-present leading/trailing whitespace refusal.
This local Remote contract is not a new restriction on Toolkit's authoritative
AutomationId schema and does not establish full parity.

Three public-interface regressions were added in `MSS_Remote/tests/address_contract.rs`:

- ASCII/NBSP/em/narrow-NBSP/ideographic padding is rejected for Read, Focus and
  Text through both normal and cancellable submission, without changing input.
- Valid text payloads retain their whitespace; literal backslash-u text is not
  mistaken for a Unicode whitespace character or silently normalized.
- Owner and generation errors precede address/sequence errors; authorized
  cancellation precedes validation; closed sessions still refuse.

All five pre-existing #10 Remote tests and their assertions are unchanged. The
sixth #11 test is repaired, not removed. New inventory: six library tests plus
three public-interface tests for Remote; 48 workspace tests are expected if no
other source changes. These are inventory counts, NOT observed Rust passes.

## Checks actually performed in this follow-up

- Reconstructed parent file matches Git blob `02dc05a295cc6d610e715751bbabccae55a42d03`.
- Exact preservation of the five prior test bodies/assertions: PASS (source comparison).
- Unicode literal spelling, UTF-8, final newlines and trailing-whitespace checks: PASS.
- Rust compilation, rustfmt, Clippy, debug/release builds and Rust/native tests:
  **NOT_RUN**. No Rust/Cargo toolchain or physical Windows host is available here;
  none was installed. The old Windows fixture/fmt FAIL is historical evidence,
  not reclassified as PASS by this source patch.

## Required rechecks on the exact combined source

Run serially, with the existing lockfile/dependency pins:

```powershell
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

No Makepad transport, process lifecycle, frame producer, native sandbox or Toolkit
runtime acceptance is claimed. Keep Draft and do not enable automation.
