# PR #12: source boundary and plan-validator hardening

Parent: `4a9d221c253abaf081e1b9523f66e7ab5ae29ba0`.
No Rust product code, manifests, lockfile, scope policy, historical evidence or original tests are changed by this follow-up.

## Defects reproduced before the fix

The exact original Python script accepted a nested `tools/CWG_Core` path, nonfinite JSON `NaN`, and an empty `equivalent_checks_from` list. Its returned invariant objects also shared mutable references with the historical input. These four behaviors were exercised against the original Git-blob-matched script, not inferred from a hypothetical implementation.

## Corrections and additions

- Refuse CWG implementation directories even when nested; reject noncanonical paths, Windows-style separators and case-colliding tracked filenames.
- Inspect declared Cargo dependency names, package aliases, path/Git sources, target/build/dev/workspace dependencies, patches, replacements and lock packages without invoking Cargo. Project GOAL data, MSS_MCP and documentary CWG links remain allowed.
- Retain the exact nine required equivalent native checks. Empty/reduced/duplicated lists and duplicated invariant obligations are refused.
- Bound source reads before parsing; refuse observed symlinks/reparse points, special files, hardlinks and file identity drift. This is for a quiescent owner-controlled source tree, NOT a race-free OS sandbox against hostile same-user processes.
- Enforce UTF-8 JSON, reject nonfinite/overflow numbers and lone surrogates, validate graph containers and bounds, and return independent copies of preserved history.
- Git inventory inspection has a timeout and post-read size gate. It is a repository hygiene check, not a native process/memory isolation boundary.

## Verification actually executed

Python 3.13.5 on Linux:

- Original 14 tests: PASS before changes; all original test bytes remain unchanged.
- `python -m unittest discover -s scripts/tests -p 'test_mss_scope*.py' -v`: **37 PASS, 0 fail, 0 skipped** (14 original + 23 new).
- Six hash-pinned real master-plan inputs: PASS. Effective JSON equals the prior independent plan by value, including every preserved assertion/status: 112 operations, 54 invariants and 68 proposed checks.
- Python compile checks: PASS.
- `git diff --check` against an actual temporary Git index of reconstructed changed files: PASS, exit 0. This is not a full remote checkout/build.
- Symlink/hardlink fixtures ran on Linux. Windows reparse/ACL, native GUI/GPU, Rust compilation/format/test/Clippy/build: **NOT_RUN**. No Rust toolchain or physical Windows host is available; none was installed.

The first ad-hoc no-index whitespace harness expected exit 0, but ordinary differences yield exit 1 in no-index mode. It was replaced with a real temporary Git index and `git diff --check`, exit 0. No product test failure was suppressed.

## Tested source hashes

- `scripts/mss_scope.py` SHA-256: `54a394faee1116a734f60ca9f3ff0144fc7a8a6344134ca56ce28781c10c0c5b`.
- `scripts/tests/test_mss_scope_hardening.py` SHA-256: `bfaf90446267b37121efacf7921e2e3d15a350645b38f5d4a1efafd5ecb0919f`.
- Unchanged original tests SHA-256: `039ee42974b00e61533115417b5002d7cc60103007348170a455574334ff926c`.
- Final 37-test stderr log SHA-256: `4a13c24a5b7558f98362b5f840dfb4875cc2c90f0525f1834b3defcfff94b4c0`.
- Real plan-projection stdout SHA-256: `ddd3ce09a729edeef19b8b06687b2372a7a00649f71fa27596c361a020bb7800`.

Keep Draft. This change does not install CWG, a broker, a workflow, a model client or new dependencies. It neither removes MSS native verification obligations nor grants acceptance. Run the complete resulting checkout and Rust gates after combining with #10/#11.
