# Goal attempt/event receipts

Each completed check attempt should be recorded as a **new immutable file** named `<goal-id>-<attempt>-<check-id>.json`. Do not rewrite historical receipts. A receipt must identify schema, goal/check IDs, attempt, exact source commit, host or CI runner, start and completion time, exit/result status, and references plus hashes of raw evidence. No fabricated placeholders should be submitted as real attempts.

Example (illustration only, **not** an actual execution): `{"schema":"mss-check-receipt-v1","goal_id":"MSS-002","check_id":"CORE_TEST","status":"NOT_RUN","source_commit":null}`.

The goal JSON's latest check status is a projection of reviewed receipts, never independent proof. A stale source hash invalidates current applicability but does not erase original historical receipts.
