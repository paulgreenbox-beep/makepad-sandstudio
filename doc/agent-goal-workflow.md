# GitHub and agent goal workflow

The agent workflow uses existing GitHub PR review, stable Dungeon object IDs and a small goal/check registry. This is **not** an alternative test runner.

```mermaid
flowchart LR
  Index["goals/manifest.json"] --> Goal["GOAL document"]
  Goal --> SKLT["Dungeon object_id"]
  Goal --> PR["GitHub topic PR"]
  PR --> Checks["Existing Toolkit / Cargo tests"]
  Checks --> Receipt["Immutable check receipt / evidence"]
  Receipt --> Review["Reviewer validates commit and postconditions"]
  Review --> Status["Goal status update"]
```

Agent updates are proposed through PRs. Reviewer may mark VERIFIED only with actual source-bound execution evidence and passing required checks. Unknown/blocked requirements never silently become success. On new commits invalidate currency of prior receipts. No auto-merges, no cross-agent ownership inheritance, no container/VM runtime.

Relevant references: [Dungeon System](https://github.com/paulgreenbox-beep/dungeon-system), [Rust Makepad Toolkit](https://github.com/paulgreenbox-beep/rust-makepad-toolkit).
