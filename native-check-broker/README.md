# MSS Native Check Broker — initial fail-closed protocol foundation

This is **NOT** a qualified Windows check broker. It is a small Rust binary that
reads one bounded JSON request on stdin, rejects malformed or unapproved literal
check commands and **always exits without executing anything**. It does not
claim ownership of a native sandbox, mint check receipts, run Git/Cargo, or access
secrets.

It is intentionally **not** the installed `check-broker.exe` required by the
dispatcher. Do not install or configure it there. The executable target is named
`mss-native-check-broker` to prevent accidental promotion.

## Source checks

From the repository root:

```powershell
cargo test --manifest-path native-check-broker/Cargo.toml
cargo fmt --manifest-path native-check-broker/Cargo.toml -- --check
```

Dependencies are fetched by Cargo when not already available; no CI or native
runtime qualification has been performed in this publication.

## Requirements before enabling execution

A follow-up implementation must enforce exact catalog and selected GOAL
policy, canonicalize the Windows workspace under a trusted root, open a clean
checkout pinned to the exact SHA, resolve tools to reviewed absolute executable
paths, create a low-privilege restricted process token and OS-native process
lifetime boundary, prevent secret inheritance, enforce filesystem and network
policy, capture bounded evidence, and validate owner-scoped cleanup.

Windows Job Objects alone are **not** a filesystem/network security boundary.
No `PASS` can be emitted without independently verifiable source-bound evidence.
Physical Windows negative tests and separate owner approval are mandatory.

Dependencies: PR #5 (GOAL registry), PR #7 (disabled dispatcher), Issue #8.
