# Developer and agent rules

MSS is in **Initial Architecture / Development**. Read this file, SECURITY.md, doc/architecture.md, doc/compatibility.md, doc/testing.md, and doc/dungeon.md before changing a public contract or structural declaration. The native Desktop shell is illustrative; do not describe it as a live viewer.

## Evidence and result handling

- Never weaken an assertion, postcondition, health check, failure classification, identity check, or cleanup requirement to obtain a green result.
- Never delete, skip, shorten, rename, or replace existing Rust Makepad Toolkit tests or .aiui.json scenarios to make MSS pass.
- Do not treat a command acknowledgement, successful HTTP response, captured frame, compilation, or static source inspection as proof of a completed user-visible action.
- Verify mutations with the declared postcondition, runtime health, and session-bound evidence. Preserve an uncertain outcome as OUTCOME_UNKNOWN; do not automatically replay a mutation.
- Use PASS, FAIL, BLOCKED, NOT_RUN, and NOT_VERIFIED for acceptance states as defined in doc/testing.md. Operational outcomes such as OUTCOME_UNKNOWN and UNSUPPORTED may be reported separately; never normalize them into PASS.
- Keep source review, compilation, unit checks, live application behavior, GUI acceptance, and release acceptance as separate evidence levels.

## Source and dependency discipline

- Do not modify the official Makepad repository, rust-makepad-toolkit, or rust-makepad-tools-2 as part of MSS work.
- Do not copy or vendor the Makepad SDK into this repository.
- Before adding or changing a dependency, record its exact repository and commit, inspect its public API and license, and evaluate compatibility with the pinned MSS baseline. A version string alone is not a commit pin.
- Do not call the different Makepad revisions used by the three source projects compatible until a focused compatibility suite passes.
- Retain the full Toolkit public operation and .aiui.json contract as the target. Changes to the baseline itself require a separate reviewed migration.
- Do not install dependencies, download executables, or change host configuration without operator authorization. A request to check the existing Cargo workspace authorizes resolving its declared, reviewed dependencies for that check; it does not authorize adding or upgrading dependencies.

## Ownership and input

- Never attach to, inspect, signal, or terminate a process unless MSS created it and still verifies its PID, process-birth identity, executable path, and session binding.
- Never target an app by process name, title, guessed port, or stale PID alone.
- Bind each application and test worker to one explicit session and one agent identity. Do not share mutable session state between agents.
- Send input only through an authenticated, session-addressed app channel. Do not silently replace semantic actions with SendInput, desktop focus, or another physical-input fallback.
- An input isolation mechanism inside Makepad is not full operating-system isolation. Do not describe MSS as a sandbox unless a separately reviewed OS security boundary is implemented and verified.

## Processes, retries, and cleanup

- Launch trusted executables with explicit argument arrays and a session-scoped working directory; do not construct shell command strings from agent input.
- Give each app and test execution its own process. Record process identity and creation evidence before accepting a session.
- No automatic retry after an uncertain mutation, timeout after dispatch, transport loss during dispatch, or worker loss. Require independent observation or explicit recovery policy.
- On close, release only resources acquired by that session. Verify process exit and resource release. Quarantine uncertain ownership instead of killing an unverified process.

## Changes and verification

- Map every change to an owner module and a row in doc/testing.md.
- Choose the cheapest check that can falsify the changed contract, then run every explicitly required higher-level gate. Do not claim live behavior from a Cargo check.
- Preserve the exact commands, source revisions, result, and evidence references needed to reproduce an acceptance claim.
- Keep Dungeon SKLT object IDs and declared dependencies stable. SKLT is structural documentation, not executable evidence or OS sandbox proof. GLIF/GLYF projection work is out of scope until separately requested.
- Do not introduce containers, WSL/WSLC, Hyper-V, virtual machines, or tests that require an interactive Windows desktop.
