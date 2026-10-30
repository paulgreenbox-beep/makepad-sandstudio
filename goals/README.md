# Agent goals and verification ledger

This directory is the **reviewable source-of-truth for planned tasks and observed check states**. It is not a test executor, an authorization grant, nor a substitute for Dungeon SKLT structural objects.

- `manifest.json` indexes goals by stable IDs.
- `GOAL-*.json` records purpose, scope, acceptance conditions, check obligations and **reported** status.
- `checks/catalog.json` contains stable check IDs, commands and evidence requirements.
- `events/README.md` defines append-only attempt receipts. Raw binaries, screenshots, secrets and logs belong in an external evidence store, not Git.

## Status rules
Goal: `TODO → IN_PROGRESS → IN_REVIEW → VERIFIED`, or `BLOCKED` / `FAILED`. Only a verifier/reviewer may set `VERIFIED`, after comparing required checks to actual evidence tied to the exact source SHA. Agents can mark TODO/IN_PROGRESS/BLOCKED/IN_REVIEW, but not infer VERIFIED from CI green alone.

Checks: `NOT_RUN | PASS | FAIL | BLOCKED | UNKNOWN`. `PASS` requires a real command/result receipt; `NOT_RUN` is the initial value. Never silently skip a required check or turn UNKNOWN into PASS.

## Workflow
1. Read AGENTS.md, SECURITY.md, this README, and goals/manifest.json.
2. Select one goal, verify dependencies, compare target branch + base SHA, set IN_PROGRESS only through an authorized PR.
3. Make code changes in a topic branch; run checks. Append immutable evidence references and actual status.
4. Submit a PR and set IN_REVIEW. Reviewer confirms commit, checks, and acceptance. Do not auto-merge.
5. If source moves, previously recorded results are stale until re-qualified.

Use GitHub issue/PR links as coordination **references**, not replacement for this declared structure. Avoid concurrent direct edits to the same goal file; use branch/PR review and GitHub commit-SHA guards.
