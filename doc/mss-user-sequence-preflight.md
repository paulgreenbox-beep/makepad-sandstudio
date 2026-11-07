# Explicit user-sequence preflight

## Scope and dependency

This source-only change is stacked on Draft PR #15 at
`68ce7287347d9d82ca009b3f88559afc2718454f`. It changes the existing MSS Python
router and adds model-free regressions. It does not install code into a running
MCP, change application/profile/SDK pins or add a GUI tool. Use the existing
semantic `mss_ui_act` with action `select` and `v=<label>` for a combo-box that
advertises that action; refresh its node/window and independently inspect the
result. This PR does not claim that every popup implements selection.

## Why the preflight is needed

At inspected official Makepad revision
`2271c0eb350cedd497c84373f17ad2b0b662cb72`, the semantic handler checks
`if_user_seq` before `backend.action`, then rechecks sequence before individual
actions and again **after** action/presentation. Therefore a postdispatch
`user_intervened` error cannot universally establish that nothing happened.
See [the pre- and post-action guards](https://github.com/makepad/makepad/blob/2271c0eb350cedd497c84373f17ad2b0b662cb72/platform/hal/src/a11y/remote.rs#L175-L205).

The semantic backend's
[sequence query](https://github.com/makepad/makepad/blob/2271c0eb350cedd497c84373f17ad2b0b662cb72/platform/hal/src/a11y.rs#L297-L299)
uses the owning app's
[Cx activity ledger](https://github.com/makepad/makepad/blob/2271c0eb350cedd497c84373f17ad2b0b662cb72/platform/src/os/hal/query.rs#L25).
The existing `ui__activity` route reads
[that same ledger](https://github.com/makepad/makepad/blob/2271c0eb350cedd497c84373f17ad2b0b662cb72/platform/src/remote.rs#L1803-L1805),
whose JSON has an exact `u64` `user_seq` field; see
[activity JSON](https://github.com/makepad/makepad/blob/2271c0eb350cedd497c84373f17ad2b0b662cb72/platform/src/remote_activity.rs#L72-L84).
These are source findings, not live GUI acceptance or cross-version guarantees.

## Contract

Only an explicitly supplied `if_user_seq` opts into the new read. The existing
argument-type/range validation remains, with negative semantic sequences now
rejected before native calls as well as negative raw-input sequences.

1. Resolve the connection-owned app and enforce current permissions. In shared
   mode, obtain the existing queue turn and recheck permission first.
2. Verify the existing ready receipt/process identity and node/window/capability
   checks. Do not discover another app by PID, name or window.
3. On the same selected native peer, call the existing read-only `ui__activity`.
   Accept `user_seq` only as an exact Python `int` (not bool), between zero and
   `2**64 - 1`. Missing/malformed/error/unavailable activity has no implicit zero.
4. On mismatch return `REFUSED_STALE_USER_SEQ`, `action_dispatched: false`, and
   expected/observed sequence metadata. On unavailable/invalid activity return
   `REFUSED_ACTIVITY_UNAVAILABLE`, `action_dispatched: false`. No native mutation
   is called and app state stays ready. A queued refusal is `FAILED`, not PASS.
5. On a match send exactly the existing native mutation with the **original**
   `if_user_seq`. Do not remove or replace the native compare-and-check guard.

The preflight is an observation, not an atomic lock. A race after it can still
produce an uncertain outcome. The existing postdispatch semantic error,
timeout and unhandled/fallback classifications remain `OUTCOME_UNKNOWN`, with
no replay. Existing narrow raw-input refusals with independent `applied:false`
proof remain unchanged; no new error-text heuristic is added.

Without explicit `if_user_seq`, the existing call path is unchanged. The read
adds no API/tool/schema, timer, background polling, cross-app operation or
clipboard access. The normal queued envelope still reports effect separately;
the `action_dispatched:false` field identifies this predispatch refusal, not a
verified user-visible postcondition. A matching sequence and native `handled`
acknowledgement are not test PASS: inspect the resulting tree/state and health.

## Invariants and regression coverage

| ID | Falsifiable rule | Test in `MSS_MCP/tests/test_mss_user_seq.py` |
| --- | --- | --- |
| C-SEQ-01 | Explicit mismatched guard causes zero native mutations. | `test_stale_sequence_refused_without_native_action` |
| C-SEQ-02 | Missing/invalid/unavailable activity never becomes zero or permits dispatch. | `test_missing_or_invalid_activity_never_defaults_to_zero`, `test_error_malformed_json_or_transport_before_action_is_controlled_refusal`, `test_activity_capability_missing_does_not_dispatch` |
| C-SEQ-03 | Same sequence dispatches once with the original native guard; zero/u64 reads remain exact. | `test_matching_sequence_dispatched_once_with_original_native_guard`, `test_zero_is_a_real_sequence_not_a_missing_default`, `test_u64_activity_sequence_not_narrowed_or_float_converted` |
| C-SEQ-04 | Foreign/stale/window/read-only/revoked contexts cannot reach activity or dispatch. | `test_foreign_app_is_refused_before_any_native_read`, `test_stale_process_identity_is_refused_before_activity`, `test_wrong_window_is_refused_before_activity`, `test_read_only_profile_cannot_gain_dispatch_authority`, `test_revoked_permission_is_refused_before_activity` |
| C-SEQ-05 | Postdispatch race, timeout and selection fallback stay unknown and are not replayed. | `test_race_error_after_matching_preflight_stays_unknown_and_never_replayed`, `test_timeout_after_dispatch_is_unknown_without_replay`, `test_select_fallback_after_dispatch_is_still_unknown`, `test_queued_postdispatch_error_marks_unknown` |
| C-SEQ-06 | Preflight occurs after queue turn, not when the request first entered the queue. | `test_queued_preflight_runs_after_turn_and_records_failed_not_unknown` |
| C-SEQ-07 | Existing tool semantics, no-guard path and clipboard refusal are preserved. | `test_no_explicit_guard_keeps_existing_call_path`, `test_semantic_type_keeps_replace_text_and_guard`, `test_raw_key_mouse_and_drop_keep_guard_and_clipboard_policy`, `test_invalid_requested_sequence_rejected_by_public_validation` |

Additional edge regressions cover deeply nested activity JSON before dispatch,
two managed peers with different sequence values, permission revocation while
waiting for the turn, and the exact upstream **post-action** error wording:
`test_deeply_nested_activity_is_refused_before_dispatch_in_queue`,
`test_neighbor_activity_cannot_satisfy_this_apps_guard`,
`test_permission_revoked_while_waiting_is_rechecked_before_activity` and
`test_native_error_after_applied_action_stays_unknown`.

## Reproduction and evidence limits

Use the previously admitted Python runtime and an operator-owned task-only
writable temporary root; change no host ACLs or privileges.

```powershell
$env:TEMP = $taskOnlyTemporaryRoot
$env:TMP = $taskOnlyTemporaryRoot
python -B -m unittest discover -s MSS_MCP/tests -p 'test_mss_user_seq.py' -v
python -B -m unittest discover -s MSS_MCP/tests -p 'test_mss_*.py' -v
git diff 68ce7287347d9d82ca009b3f88559afc2718454f HEAD --check
```

The focused tests exercise actual Router/App permission/receipt/window/dispatch
code, with a synthetic native peer, OS identity observer and queue interface.
They do not launch Makepad, simulate a GPU frame or qualify an OS isolation
boundary. Parent-provided live observations are separate from this source-only
verification and are not promoted to acceptance here. Native Makepad replay of
this exact change remains `NOT_RUN`; GUI/Toolkit/security qualification remains
`NOT_VERIFIED`. No Cargo/native/model run, software installation, upstream edit,
live MCP restart, profile activation, automatic merge or force push is needed.
