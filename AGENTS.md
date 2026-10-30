# Agent instructions — MSS

Read README.md, SECURITY.md, doc/architecture.md, doc/compatibility.md, and doc/testing.md before changing contracts.

- Preserve all external repositories. No automatic writes to Makepad, Rust Makepad Toolkit or Rust Makepad Tools 2.
- No Docker, WSL, WSLC, VM or virtualized test worker.
- No installing dependencies, downloading executables or changing host configuration without operator permission.
- No fabricated runtime support, screenshots, benchmark numbers, PASS states, clean shutdown proofs or test results.
- Toolkit is the contract authority. Do not redefine operations, weaken assertions or skip required evidence. Record `UNSUPPORTED`, `NOT_RUN`, `UNKNOWN`, or `BLOCKED` accurately.
- Keep GUI sessions owner-scoped: exact process identity, generation, window/widget identity and per-session artifact paths. No foreign attach and no implicit fallback from remote input to global OS input.
- No blind replay after dispatch if outcome is unknown; fence mutations, observe and require explicit recovery.
- Mutations must be bounded, authorized and cancellation-aware. Forced containment is not a normal exit.
- Avoid accidental global key/mouse input; never block human work.
- Prefer small, reviewable commits with actual checks and recorded scope. Do not describe mock layers as production-ready.

## Dungeon structural declarations

Read [doc/dungeon.md](doc/dungeon.md) before modifying SKLT. Keep stable `object_id` values and explicit dependencies. SKLT is not executable proof; do not conflate architectural `BOUNDED` with OS sandbox security. GLIF/GLYF integration remains out of scope for now.
