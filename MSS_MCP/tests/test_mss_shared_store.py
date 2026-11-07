"""Model-free regression tests for the production shared coordination store."""

import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import sys
from threading import Thread
from time import sleep
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from mss_shared import SharedError, Store


class SharedStoreTests(unittest.TestCase):
    def setUp(self):
        self.fixture = tempfile.TemporaryDirectory(prefix="mss-shared-test-")
        self.addCleanup(self.fixture.cleanup)
        self.path = Path(self.fixture.name) / "shared.sqlite3"
        self.live = {1: 101, 2: 202, 3: 303}
        self.owner = self.store("owner", 1)
        self.member = self.store("member", 2)
        self.other = self.store("other", 3)
        self.owner.publish("app_one", self.record(501))
        self.owner.publish("app_two", self.record(502))

    def record(self, pid):
        return {"profile": "rudraoffice", "state": "READY", "pid": pid,
                "app_sha256": "a" * 64, "directory": str(self.path.parent / str(pid))}

    def store(self, connection_id, pid, session=1, queue_limit=8):
        return Store(self.path, connection_id, {"pid": pid, "birth": self.live.get(pid, 999), "windows_session": session},
                     lambda identity: self.live.get(identity["pid"]) == identity["birth"], queue_limit=queue_limit)

    def denied(self, expected_code, callback, *args, **kwargs):
        with self.assertRaises(SharedError) as caught:
            callback(*args, **kwargs)
        self.assertEqual(caught.exception.code, expected_code)

    def share(self, mode="control"):
        self.owner.share("app_one", mode)
        return self.member.attach("app_one")

    def running(self, store=None, app_id="app_one"):
        store = store or self.owner
        op = store.enqueue(app_id, "mss_ui_act")
        self.assertEqual(store.wait_turn(op["operation_id"])["state"], "RUNNING")
        return op

    def test_private_app_id_alone_confers_no_access(self):
        self.denied("NOT_ATTACHED", self.member.permission, "app_one")
        self.denied("SHARE_DISABLED", self.member.attach, "app_one")
        self.denied("UNKNOWN_APP", self.member.app, "app_missing")
        self.assertEqual(self.owner.app("app_one")["state"], "READY")

    def test_read_attachment_cannot_control_close_or_share(self):
        self.assertEqual(self.share("read")["mode"], "read")
        self.assertEqual(self.member.permission("app_one"), "read")
        self.denied("CONTROL_REQUIRED", self.member.enqueue, "app_one", "mss_ui_type")
        self.denied("OWNER_REQUIRED", self.member.enqueue, "app_one", "mss_close_app")
        self.denied("OWNER_REQUIRED", self.member.share, "app_one", "control")
        self.denied("OWNER_REQUIRED", self.member.update_state, "app_one", "CLOSED")
        self.assertEqual(self.owner.operations("app_one"), [])

    def test_control_attachment_participants_and_no_ownership_transfer(self):
        self.share()
        self.assertEqual(self.member.permission("app_one", control=True), "control")
        self.denied("OWNER_REQUIRED", self.member.permission, "app_one", owner=True)
        participants = self.member.participants("app_one")
        self.assertEqual(participants["owner_connection_id"], "owner")
        self.assertEqual({r["connection_id"]: r["mode"] for r in participants["participants"]},
                         {"owner": "owner", "member": "control"})
        self.assertEqual(len(self.member.list_instances()), 2)

    def test_downgrade_and_revoke_cancel_pending_work(self):
        self.share()
        pending = self.member.enqueue("app_one", "mss_ui_act")
        self.owner.share("app_one", "read")
        self.assertEqual(self.member.operation("app_one", pending["operation_id"])["state"], "CANCELLED")
        self.denied("CONTROL_REQUIRED", self.member.permission, "app_one", control=True)
        self.owner.share("app_one", "private")
        self.denied("NOT_ATTACHED", self.member.permission, "app_one")

    def test_detach_preserves_owner_and_cancels_only_members_queue(self):
        self.share()
        member_op = self.member.enqueue("app_one", "mss_ui_key")
        owner_op = self.owner.enqueue("app_one", "mss_ui_act")
        self.assertEqual(self.member.detach("app_one")["state"], "DETACHED")
        self.assertEqual(self.owner.operation("app_one", member_op["operation_id"])["state"], "CANCELLED")
        self.assertEqual(self.owner.operation("app_one", owner_op["operation_id"])["state"], "QUEUED")
        self.assertEqual(self.owner.app("app_one")["state"], "READY")
        self.denied("OWNER_CANNOT_DETACH", self.owner.detach, "app_one")

    def test_other_windows_session_cannot_attach(self):
        self.live[4] = 404
        other_session = self.store("other-session", 4, session=2)
        self.owner.share("app_one", "control")
        self.denied("SESSION_MISMATCH", other_session.attach, "app_one")

    def test_connection_id_cannot_be_reused_for_different_birth(self):
        self.live[1] = 909
        self.denied("CONNECTION_CONFLICT", self.store, "owner", 1)

    def test_owner_pid_reuse_blocks_attach_and_dispatch(self):
        self.owner.share("app_one", "control")
        self.live[1] = 999
        self.denied("APP_UNAVAILABLE", self.member.attach, "app_one")
        self.assertEqual(self.member.app("app_one")["state"], "OWNER_LOST")

    def test_retiring_participant_never_closes_owners_app(self):
        self.share()
        pending = self.member.enqueue("app_one", "mss_ui_drop")
        self.member.retire_connection()
        self.assertEqual(self.owner.app("app_one")["state"], "READY")
        self.assertEqual(self.owner.operation("app_one", pending["operation_id"])["state"], "CANCELLED")
        self.denied("CONNECTION_CLOSED", self.member.permission, "app_one")

    def test_retiring_owner_marks_unclosed_apps_lost_but_keeps_closed_receipt(self):
        self.share()
        self.owner.update_state("app_two", "CLOSED")
        self.owner.retire_connection()
        self.assertEqual(self.member.app("app_one")["state"], "OWNER_LOST")
        self.assertEqual(self.member.app("app_two")["state"], "CLOSED")
        self.denied("APP_UNAVAILABLE", self.member.enqueue, "app_one", "mss_ui_act")

    def test_fifo_between_two_connections_and_distinct_operation_ids(self):
        self.share()
        first = self.running(self.owner)
        second = self.member.enqueue("app_one", "mss_ui_type")
        third = self.owner.enqueue("app_one", "mss_ui_key")
        self.assertEqual(len({v["operation_id"] for v in (first, second, third)}), 3)
        completed = []

        def dispatch(store, op):
            state = store.wait_turn(op["operation_id"])
            if state["state"] == "RUNNING":
                completed.append(state["operation_id"])
                store.finish(state["operation_id"], "APPLIED")

        threads = [Thread(target=dispatch, args=(self.member, second)), Thread(target=dispatch, args=(self.owner, third))]
        for thread in threads:
            thread.start()
        sleep(0.04)
        self.assertEqual(completed, [])
        self.owner.finish(first["operation_id"], "APPLIED")
        for thread in threads:
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
        self.assertEqual(completed, [second["operation_id"], third["operation_id"]])
        self.assertTrue(all(op["state"] == "APPLIED" for op in self.owner.operations("app_one")))

    def test_other_app_dispatches_while_first_has_running_and_queued_work(self):
        first = self.running()
        self.owner.enqueue("app_one", "mss_ui_key")
        other = self.running(app_id="app_two")
        self.owner.finish(other["operation_id"], "APPLIED")
        self.assertEqual(self.owner.operation("app_one", first["operation_id"])["state"], "RUNNING")

    def test_queue_capacity_counts_pending_and_returns_queue_full(self):
        limited = self.store("owner", 1, queue_limit=2)
        self.running(limited)
        limited.enqueue("app_one", "mss_ui_act")
        limited.enqueue("app_one", "mss_ui_act")
        self.denied("QUEUE_FULL", limited.enqueue, "app_one", "mss_ui_act")
        self.assertEqual(len(limited.operations("app_one")), 3)

    def test_deadline_cancels_queued_action_and_never_dispatches_later(self):
        first = self.running()
        pending = self.owner.enqueue("app_one", "mss_ui_type", timeout_ms=10)
        sleep(0.03)
        self.assertEqual(self.owner.wait_turn(pending["operation_id"])["state"], "CANCELLED")
        self.owner.finish(first["operation_id"], "APPLIED")
        self.assertEqual(self.owner.wait_turn(pending["operation_id"])["state"], "CANCELLED")

    def test_wall_clock_rollback_cannot_extend_monotonic_queue_deadline(self):
        first = self.running()
        pending = self.owner.enqueue("app_one", "mss_ui_type", timeout_ms=10)
        self.assertEqual(pending["deadline_clock"], "monotonic")
        with patch("mss_shared.time", return_value=0):
            sleep(0.03)
            expired = self.owner.wait_turn(pending["operation_id"])
        self.assertEqual(expired["state"], "CANCELLED")
        self.assertEqual(expired["code"], "DEADLINE_EXPIRED")
        self.assertEqual(expired["completed_at"], 0)
        self.owner.finish(first["operation_id"], "APPLIED")
        self.assertEqual(self.owner.wait_turn(pending["operation_id"])["state"], "CANCELLED")
        self.assertTrue(all(op["deadline_clock"] == "monotonic" for op in self.owner.operations("app_one")))

    def test_only_queued_actions_can_be_cancelled(self):
        self.share()
        running = self.running(self.member)
        queued = self.member.enqueue("app_one", "mss_ui_act")
        self.assertEqual(self.owner.cancel("app_one", queued["operation_id"])["state"], "CANCELLED")
        self.denied("CANNOT_CANCEL", self.owner.cancel, "app_one", running["operation_id"])

    def test_other_participant_cannot_cancel_or_finish_operation(self):
        self.share()
        self.other.attach("app_one")
        pending = self.member.enqueue("app_one", "mss_ui_act")
        self.denied("OPERATION_OWNER_REQUIRED", self.other.cancel, "app_one", pending["operation_id"])
        self.denied("OPERATION_OWNER_REQUIRED", self.other.wait_turn, pending["operation_id"])
        self.member.wait_turn(pending["operation_id"])
        self.denied("OPERATION_OWNER_REQUIRED", self.owner.finish, pending["operation_id"], "APPLIED")

    def test_unknown_result_quarantines_without_replay(self):
        first = self.running()
        pending = self.owner.enqueue("app_one", "mss_ui_act")
        self.owner.finish(first["operation_id"], "OUTCOME_UNKNOWN", code="TRANSPORT_LOST", effect="OUTCOME_UNKNOWN")
        self.assertEqual(self.owner.app("app_one")["state"], "OUTCOME_UNKNOWN")
        self.assertEqual(self.owner.wait_turn(pending["operation_id"])["state"], "CANCELLED")
        self.denied("OUTCOME_UNKNOWN", self.owner.enqueue, "app_one", "mss_ui_act")
        self.denied("RECOVERY_REQUIRED", self.owner.update_state, "app_one", "READY")
        self.assertEqual(len(self.owner.operations("app_one")), 2)

    def test_dead_running_caller_is_unknown_and_dead_queued_caller_is_cancelled(self):
        self.share()
        running = self.running(self.member)
        queued = self.member.enqueue("app_one", "mss_ui_act")
        self.live[2] = 999
        observed = self.owner.operations("app_one")
        states = {op["operation_id"]: op["state"] for op in observed}
        self.assertEqual(states[running["operation_id"]], "OUTCOME_UNKNOWN")
        self.assertEqual(states[queued["operation_id"]], "CANCELLED")
        self.assertEqual(self.owner.app("app_one")["state"], "OUTCOME_UNKNOWN")

    def test_owner_can_close_quarantined_app_but_control_member_cannot(self):
        self.share()
        op = self.running()
        self.owner.finish(op["operation_id"], "OUTCOME_UNKNOWN")
        self.denied("OWNER_REQUIRED", self.member.enqueue, "app_one", "mss_close_app")
        closing = self.owner.enqueue("app_one", "mss_close_app")
        self.assertEqual(self.owner.wait_turn(closing["operation_id"])["state"], "RUNNING")
        self.owner.finish(closing["operation_id"], "APPLIED")
        self.owner.update_state("app_one", "CLOSED")
        self.assertEqual(self.member.app("app_one")["state"], "CLOSED")

    def test_transfer_is_target_queued_and_source_has_no_nested_ticket(self):
        self.share()
        transfer = self.member.enqueue("app_one", "mss_transfer_fragment")
        independent = self.running(app_id="app_two")
        self.assertEqual(self.member.wait_turn(transfer["operation_id"])["state"], "RUNNING")
        self.member.finish(transfer["operation_id"], "APPLIED", effect="VERIFIED")
        self.owner.finish(independent["operation_id"], "APPLIED")

    def test_failed_action_does_not_quarantine_and_raw_ack_is_not_verified(self):
        failed = self.running()
        self.owner.finish(failed["operation_id"], "FAILED", code="UNSUPPORTED", effect="NOT_APPLIED")
        self.assertEqual(self.owner.app("app_one")["state"], "READY")
        next_op = self.running()
        finished = self.owner.finish(next_op["operation_id"], "APPLIED")
        self.assertEqual(finished["effect"], "NOT_VERIFIED")
        self.denied("OPERATION_NOT_RUNNING", self.owner.finish, next_op["operation_id"], "APPLIED")

    def test_operation_lookup_cannot_cross_app_boundary(self):
        pending = self.owner.enqueue("app_one", "mss_ui_act")
        self.denied("UNKNOWN_OPERATION", self.owner.operation, "app_two", pending["operation_id"])

    def test_journal_is_bounded_and_does_not_store_command_arguments(self):
        for _ in range(132):
            op = self.running()
            self.owner.finish(op["operation_id"], "APPLIED")
        self.assertEqual(len(self.owner.operations("app_one")), 128)
        with closing(sqlite3.connect(self.path)) as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(operations)")}
        self.assertNotIn("arguments", columns)
        self.denied("INVALID_ARGUMENT", self.owner.publish, "app_payload", {"text": "private document"})
        self.denied("INVALID_ARGUMENT", self.owner.finish, "missing", "FAILED", code="private document")
        self.assertNotIn("private document", self.path.read_bytes().decode("utf-8", errors="ignore"))

    def test_app_id_cannot_be_republished_or_reopened(self):
        self.denied("APP_EXISTS", self.member.publish, "app_one", self.record(999))
        self.owner.update_state("app_one", "CLOSED")
        self.denied("RECOVERY_REQUIRED", self.owner.update_state, "app_one", "READY")

    def test_actual_router_metadata_preserves_bindings_without_credentials(self):
        record = self.record(700) | {
            "windows_session_id": 1,
            "os_identity": {"pid": 700, "birth": 123456, "image": "C:\\admitted\\app.exe", "windows_session": 1},
            "identity": {"app_pid": 700, "app_birth_utc": "2026-11-07T07:00:00Z",
                         "app_image": "C:\\admitted\\app.exe", "session_id": "owned-launch-uuid"},
            "native_tools": ["ui__status", "ui__ui", "ui__ui_act"],
        }
        published = self.owner.publish("app_router", record)
        self.assertEqual(published["os_identity"], record["os_identity"])
        self.assertEqual(published["identity"], record["identity"])
        self.assertEqual(published["native_tools"], record["native_tools"])
        self.denied("INVALID_ARGUMENT", self.owner.publish, "app_token", record | {"token": "never publish"})

    def test_control_revocation_during_running_does_not_promise_rollback(self):
        self.share()
        running = self.running(self.member)
        self.owner.share("app_one", "read")
        self.assertEqual(self.owner.operation("app_one", running["operation_id"])["state"], "RUNNING")
        self.member.finish(running["operation_id"], "APPLIED")
        self.assertEqual(self.owner.operation("app_one", running["operation_id"])["state"], "APPLIED")
        self.denied("CONTROL_REQUIRED", self.member.enqueue, "app_one", "mss_ui_act")

    def test_private_revocation_keeps_inflight_receipt_but_blocks_further_access(self):
        self.share()
        running = self.running(self.member)
        self.owner.share("app_one", "private")
        self.member.finish(running["operation_id"], "APPLIED")
        self.assertEqual(self.owner.operation("app_one", running["operation_id"])["state"], "APPLIED")
        self.denied("NOT_ATTACHED", self.member.permission, "app_one")

    def test_revoked_running_caller_crash_is_unknown_without_retry(self):
        self.share()
        running = self.running(self.member)
        self.owner.share("app_one", "private")
        self.live.pop(2)
        self.assertEqual(self.owner.operation("app_one", running["operation_id"])["state"], "OUTCOME_UNKNOWN")
        self.denied("OUTCOME_UNKNOWN", self.owner.enqueue, "app_one", "mss_ui_act")
        self.assertEqual(len(self.owner.operations("app_one")), 1)

    def test_distinct_connections_in_same_process_still_have_separate_permissions_and_fifo(self):
        same_process = self.store("same-process-peer", 1)
        self.owner.share("app_one", "control")
        same_process.attach("app_one")
        self.assertEqual(same_process.permission("app_one", control=True), "control")
        self.denied("OWNER_REQUIRED", same_process.permission, "app_one", owner=True)
        first = self.running(self.owner)
        second = same_process.enqueue("app_one", "mss_ui_act")
        observed = []
        worker = Thread(target=lambda: observed.append(same_process.wait_turn(second["operation_id"])))
        worker.start()
        sleep(0.03)
        self.assertEqual(observed, [])
        self.owner.finish(first["operation_id"], "APPLIED")
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(observed[0]["state"], "RUNNING")
        same_process.finish(second["operation_id"], "APPLIED")

    def test_shutdown_cancels_only_own_queued_non_close_work_and_retains_cleanup_authority(self):
        self.share()
        running = self.running(self.owner)
        pending = self.owner.enqueue("app_one", "mss_ui_act")
        closing = self.owner.enqueue("app_one", "mss_close_app")
        other_pending = self.member.enqueue("app_one", "mss_ui_key")
        self.assertEqual(self.owner.cancel_pending(), {"connection_id": "owner", "cancelled": 1})
        observed = {op["operation_id"]: op for op in self.owner.operations("app_one")}
        self.assertEqual(observed[running["operation_id"]]["state"], "RUNNING")
        self.assertEqual(observed[pending["operation_id"]]["state"], "CANCELLED")
        self.assertEqual(observed[pending["operation_id"]]["code"], "CONNECTION_CLOSING")
        self.assertEqual(observed[closing["operation_id"]]["state"], "QUEUED")
        self.assertEqual(observed[other_pending["operation_id"]]["state"], "QUEUED")
        self.assertEqual(self.owner.permission("app_one", owner=True), "owner")
        self.owner.finish(running["operation_id"], "APPLIED")
        self.assertEqual(self.owner.wait_turn(closing["operation_id"])["state"], "RUNNING")
        self.owner.finish(closing["operation_id"], "APPLIED")
        self.owner.update_state("app_one", "CLOSED")
        self.assertEqual(self.member.app("app_one")["state"], "CLOSED")

    def test_missing_clock_marker_cancels_legacy_queued_tickets_but_keeps_running_receipt(self):
        running = self.running()
        legacy_queued = self.owner.enqueue("app_one", "mss_ui_type")
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("DROP TABLE meta_clockversion")
            db.execute("UPDATE operations SET deadline=9999999999 WHERE operation_id=?", (legacy_queued["operation_id"],))
            db.commit()
        reconnected = self.store("owner", 1)
        expired = reconnected.operation("app_one", legacy_queued["operation_id"])
        self.assertEqual(expired["state"], "CANCELLED")
        self.assertEqual(expired["code"], "DEADLINE_CLOCK_MIGRATED")
        self.assertEqual(reconnected.operation("app_one", running["operation_id"])["state"], "RUNNING")
        reconnected.finish(running["operation_id"], "APPLIED")
        fresh = reconnected.enqueue("app_one", "mss_ui_act")
        self.assertEqual(reconnected.wait_turn(fresh["operation_id"])["state"], "RUNNING")
        reconnected.finish(fresh["operation_id"], "APPLIED")
        unchanged = self.store("owner", 1)
        self.assertEqual(unchanged.operation("app_one", fresh["operation_id"])["state"], "APPLIED")

    def test_build_activation_is_owner_only_and_serialized_after_shared_mutations(self):
        self.share()
        self.denied("OWNER_REQUIRED", self.member.enqueue, "app_one", "mss_activate_build")
        running = self.running(self.member)
        activation = self.owner.enqueue("app_one", "mss_activate_build")
        observed = []
        worker = Thread(target=lambda: observed.append(self.owner.wait_turn(activation["operation_id"])))
        worker.start()
        sleep(0.03)
        self.assertEqual(observed, [])
        self.member.finish(running["operation_id"], "APPLIED")
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(observed[0]["state"], "RUNNING")
        self.assertGreater(observed[0]["sequence"], running["sequence"])
        self.owner.finish(activation["operation_id"], "APPLIED")

    def test_unknown_blocks_build_activation_but_still_allows_owner_close(self):
        running = self.running()
        activation = self.owner.enqueue("app_one", "mss_activate_build")
        self.owner.finish(running["operation_id"], "OUTCOME_UNKNOWN")
        self.assertEqual(self.owner.operation("app_one", activation["operation_id"])["state"], "CANCELLED")
        self.denied("OUTCOME_UNKNOWN", self.owner.enqueue, "app_one", "mss_activate_build")
        closing = self.owner.enqueue("app_one", "mss_close_app")
        self.assertEqual(self.owner.wait_turn(closing["operation_id"])["state"], "RUNNING")
        self.owner.finish(closing["operation_id"], "APPLIED")

    def test_shutdown_cancels_queued_activation_and_preserves_only_owner_close(self):
        running = self.running()
        activation = self.owner.enqueue("app_one", "mss_activate_build")
        closing = self.owner.enqueue("app_one", "mss_close_app")
        self.owner.cancel_pending()
        self.assertEqual(self.owner.operation("app_one", activation["operation_id"])["state"], "CANCELLED")
        self.assertEqual(self.owner.operation("app_one", closing["operation_id"])["state"], "QUEUED")
        self.owner.finish(running["operation_id"], "APPLIED")
        self.assertEqual(self.owner.wait_turn(closing["operation_id"])["state"], "RUNNING")
        self.owner.finish(closing["operation_id"], "APPLIED")


if __name__ == "__main__":
    unittest.main()
