"""Model-free cleanup policy tests; never launch or signal an application."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

helpers = os.environ.get("MSS_TEST_HELPERS")
if helpers:
    sys.path.insert(0, helpers)
tools = Path(os.environ.get("MSS_TEST_TOOLS", Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(tools))

import mss_universal as mss
from mss_process import birth_ticks


BIRTH = "2026-11-07T07:02:42.3335099Z"
BIRTH_TICKS = birth_ticks(BIRTH)
APP_ID = "app_" + "a" * 32
SESSION = "b" * 32


def receipt_fixture(*, healthy=False, early_exit=False):
    return {
        "schema_version": 1, "status": "CLOSED" if healthy else "FAILED_CLOSED",
        "cleanup": "GRACEFUL" if healthy else "ALREADY_EXITED",
        "app_pid": 1734, "app_birth_utc": BIRTH, "app_birth_filetime": BIRTH_TICKS,
        "app_image": None if early_exit else "app.exe", "app_image_expected": "app.exe",
        "app_image_verified": not early_exit, "app_exit_code": 0,
        "launcher_pid": 4321, "launcher_exit_code": 0 if healthy else 1,
        "launcher_script_sha256": "d" * 64,
        "startup_qualified": healthy, "mcp_started": healthy,
        "mcp_exit_observed": healthy, "mcp_exit_code": 0 if healthy else None,
        "log_capture": "COMPLETE", "completed_utc": "2026-11-07T07:03:00.0000000Z",
        "exit_proof": {"kind": "retained_process_handle", "pid": 1734,
                       "birth_filetime": BIRTH_TICKS, "exit_observed": True, "exit_code": 0,
                       "image_verified": not early_exit},
    }


class FakePeer:
    def __init__(self, code):
        self.code = code
        self.close_calls = 0
        self.process = SimpleNamespace(pid=4321, poll=lambda: self.code)

    def close(self):
        self.close_calls += 1
        return self.code


class CleanupClassificationTests(unittest.TestCase):
    def test_modern_startup_failure_cannot_use_known_legacy_source_to_claim_closed(self):
        receipt = receipt_fixture(healthy=True)
        receipt['startup_qualified'] = False
        self.assertEqual(mss.cleanup_classification(receipt,legacy_known=True)['state'],'FAILED_CLOSED')
    def classify(self, receipt, **overrides):
        return mss.cleanup_classification(receipt, **({"launcher_code": receipt.get("launcher_exit_code"),
                                                     "launcher_pid": 4321} | overrides))

    def test_startup_failure_with_bound_exit_is_failed_closed_even_exit_one(self):
        result = self.classify(receipt_fixture())
        self.assertEqual(result["state"], "FAILED_CLOSED")
        self.assertEqual(result["launcher_exit_code"], 1)

    def test_process_exits_before_image_query_without_invented_image(self):
        result = self.classify(receipt_fixture(early_exit=True))
        self.assertEqual(result["state"], "FAILED_CLOSED")
        self.assertIsNone(result["app_image_observed"])
        self.assertFalse(result["app_image_verified"])

    def test_ordinary_qualified_graceful_lifecycle_is_closed(self):
        self.assertEqual(self.classify(receipt_fixture(healthy=True))["state"], "CLOSED")

    def test_process_exit_alone_does_not_confirm_new_remote_temp_cleanup(self):
        receipt = receipt_fixture(healthy=True) | {"remote_directory": "fixture", "remote_cleanup": "CLEANUP_PENDING"}
        self.assertEqual(self.classify(receipt)["reason"], "OWNED_REMOTE_TEMP_CLEANUP_UNCONFIRMED")
        receipt["remote_cleanup"] = "REMOVED"
        self.assertEqual(self.classify(receipt)["state"], "CLOSED")

    def test_successful_close_needs_observed_image_verification(self):
        for field in ("receipt", "proof"):
            receipt = receipt_fixture(healthy=True)
            if field == "receipt":
                receipt["app_image_verified"] = False
            else:
                receipt["exit_proof"]["image_verified"] = False
            with self.subTest(field=field):
                self.assertEqual(self.classify(receipt)["state"], "FAILED_CLOSED")

    def test_missing_exit_proof_remains_pending_even_when_old_source_exists(self):
        receipt = receipt_fixture()
        receipt["cleanup"] = "GRACEFUL"
        receipt.pop("exit_proof")
        self.assertEqual(self.classify(receipt, legacy_known=True)["state"], "CLEANUP_PENDING")

    def test_unknown_exit_and_invalid_modern_binding_remain_pending(self):
        cases = []
        for proof_change in ({"pid": 9999}, {"birth_filetime": BIRTH_TICKS + 1},
                             {"exit_observed": False}, {"exit_code": 3}, {"pid": True}):
            receipt = receipt_fixture()
            receipt["exit_proof"].update(proof_change)
            cases.append(receipt)
        for receipt_change in ({"app_birth_filetime": True}, {"app_exit_code": None},
                               {"launcher_pid": 999}, {"launcher_exit_code": 3},
                               {"mcp_started": True, "mcp_exit_observed": False}):
            receipt = receipt_fixture()
            receipt.update(receipt_change)
            cases.append(receipt)
        for receipt in cases:
            with self.subTest(receipt=receipt):
                self.assertEqual(self.classify(receipt, launcher_code=1)["state"], "CLEANUP_PENDING")

    def test_missing_pid_cannot_be_closed_from_pid_absence(self):
        receipt = receipt_fixture()
        receipt["app_pid"] = None
        self.assertEqual(self.classify(receipt)["state"], "CLEANUP_PENDING")


class CleanupAppTests(unittest.TestCase):
    def setUp(self):
        fixture = tempfile.TemporaryDirectory(prefix="mss-cleanup-test-")
        self.addCleanup(fixture.cleanup)
        self.root = Path(fixture.name)

    def app(self, name=APP_ID, *, healthy=False, proof=True):
        directory = self.root / name
        sessions = directory / "sessions"
        receipt_dir = sessions / ("fixture-" + SESSION)
        receipt_dir.mkdir(parents=True)
        image = directory / "app.exe"
        receipt = receipt_fixture(healthy=healthy, early_exit=not healthy)
        receipt.update({"app_image_expected": str(image), "app_image": str(image) if healthy else None,
                        "profile_sha256": "e" * 64, "app_sha256": "a" * 64,
                        "remote_sha256": "b" * 64, "makepad_revision_declared": "c" * 40,
                        "session_id": SESSION, "profile_id": "fixture"})
        if not proof:
            receipt.pop("exit_proof")
        path = receipt_dir / "session.json"
        path.write_text(json.dumps(receipt), encoding="utf-8")
        app = mss.App("todo", name, directory)
        app.plan = SimpleNamespace(session_root=sessions, app_image=image, app_sha256="a" * 64,
                                   profile_sha256="e" * 64, remote_sha256="b" * 64,
                                   makepad_revision="c" * 40, build_id="baseline")
        app.launcher_sha256 = "d" * 64
        app.peer = FakePeer(0 if healthy else 1)
        return app, path

    def test_failed_closed_is_terminal_and_keeps_process_identity(self):
        app, _ = self.app()
        result = app.close()
        self.assertEqual(result["state"], "FAILED_CLOSED")
        self.assertEqual((result["pid"], result["app_birth_utc"]), (1734, BIRTH))
        self.assertEqual(app.peer.close_calls, 1)

    def test_router_startup_failure_is_not_a_successful_lifecycle_even_if_launcher_closed_normally(self):
        app, _ = self.app(healthy=True)
        app.startup_failed = True
        self.assertEqual(app.close()['state'], 'FAILED_CLOSED')
        self.assertEqual(app.cleanup_detail['reason'], 'ROUTER_STARTUP_FAILED_PROCESS_CLOSED')

    def test_no_launcher_attempt_is_explicit_evidence_not_inference_from_missing_pid(self):
        app, _ = self.app()
        app.peer = None
        self.assertFalse(app.launcher_start_attempted)
        self.assertEqual(app.close()['state'], 'FAILED_CLOSED')
        self.assertEqual(app.cleanup_detail['reason'], 'NO_LAUNCHER_START_ATTEMPT')

    def test_lost_launcher_handle_after_attempt_remains_pending(self):
        app, _ = self.app()
        app.peer = None
        app.launcher_start_attempted = True
        with self.assertRaises(mss.ToolFailure):
            app.close()
        self.assertEqual(app.state, 'CLEANUP_PENDING')

    def test_new_lifecycle_metadata_does_not_widen_shared_registry_contract(self):
        from mss_shared import Store
        store = Store(self.root/'registry.sqlite3', 'owner', {'pid':1,'birth':1,'windows_session':1}, lambda _: True)
        router = mss.Router.__new__(mss.Router)
        router.store = lambda: store
        app, _ = self.app()
        app.native_tools = {'ui__status'}
        router.publish(app)
        published = store.app(app.app_id)
        self.assertEqual(published['app_id'], app.app_id)
        for key in ('cleanup_reason','startup_failed','launcher_start_attempted'):
            self.assertNotIn(key,published)

    def test_closed_and_failed_closed_close_are_idempotent(self):
        for healthy in (False, True):
            app, _ = self.app("app_" + ("c" if healthy else "d") * 32, healthy=healthy)
            first = app.close()
            evidence = (app.directory / "closure.json").read_bytes()
            self.assertEqual(app.close(), first)
            self.assertEqual(app.peer.close_calls, 1)
            self.assertEqual((app.directory / "closure.json").read_bytes(), evidence)

    def test_unknown_failure_remains_pending_with_a_reason(self):
        app, _ = self.app(proof=False)
        with self.assertRaises(mss.ToolFailure) as error:
            app.close()
        self.assertEqual(error.exception.code, "CLEANUP_PENDING")
        self.assertEqual(app.state, "CLEANUP_PENDING")
        self.assertTrue(app.cleanup_detail["reason"])
        with self.assertRaises(mss.ToolFailure):
            app.close()
        self.assertEqual(app.peer.close_calls, 1)

    def test_recheck_reads_later_exit_proof_without_repeating_close(self):
        app, path = self.app(proof=False)
        with self.assertRaises(mss.ToolFailure):
            app.close()
        receipt = json.loads(path.read_bytes())
        receipt["exit_proof"] = receipt_fixture()["exit_proof"]
        path.write_text(json.dumps(receipt), encoding="utf-8")
        self.assertEqual(app.reconcile_cleanup()["state"], "FAILED_CLOSED")
        count = len(list(app.directory.glob("cleanup-recheck-*.json")))
        self.assertEqual(app.reconcile_cleanup()["state"], "FAILED_CLOSED")
        self.assertEqual(len(list(app.directory.glob("cleanup-recheck-*.json"))), count)
        self.assertEqual(app.peer.close_calls, 1)

    def test_ready_app_cannot_be_reclassified_as_cleanup(self):
        app, _ = self.app(healthy=True)
        app.state = "READY"
        with self.assertRaises(mss.ToolFailure) as error:
            app.reconcile_cleanup()
        self.assertEqual(error.exception.code, "APP_RUNNING")
        self.assertEqual(app.peer.close_calls, 0)

    def test_failure_of_one_app_does_not_close_or_mutate_neighbor(self):
        failed, _ = self.app()
        neighbor, _ = self.app("app_" + "f" * 32, healthy=True)
        neighbor.state = "READY"
        failed.close()
        router = mss.Router.__new__(mss.Router)
        router.apps = {failed.app_id: failed, neighbor.app_id: neighbor}
        router.closed_apps, router.shared = {}, None
        self.assertEqual(router.recheck_cleanup(failed.app_id)["state"], "FAILED_CLOSED")
        self.assertIs(router.apps[neighbor.app_id], neighbor)
        self.assertEqual(neighbor.state, "READY")
        self.assertEqual(neighbor.peer.close_calls, 0)
        self.assertEqual(failed.peer.close_calls, 1)


class ArchivedCleanupTests(unittest.TestCase):
    def test_unreviewed_legacy_record_is_not_authorized_by_a_generic_old_source_copy(self):
        receipt=json.loads(self.receipt_path.read_bytes())
        receipt.pop('exit_proof')
        receipt.pop('launcher_script_sha256')
        receipt.update(status='FAIL',cleanup='GRACEFUL')
        self.receipt_path.write_text(json.dumps(receipt),encoding='utf-8')
        source=b'reviewed legacy helper fixture'
        path=self.repo/'proof/mss-cleanup-remediation/source-before/MSS_MCP/tools/Start-MakepadMcp.ps1'
        path.parent.mkdir(parents=True)
        path.write_bytes(source)
        with patch.object(mss,'LEGACY_LAUNCHER_SHA256',hashlib.sha256(source).hexdigest()), patch.object(mss,'process_identity') as query:
            result=self.router.recheck_cleanup(APP_ID)
        self.assertEqual(result['state'],'CLEANUP_PENDING')
        self.assertEqual(result['reason'],'LEGACY_LAUNCHER_PROVENANCE_NOT_VERIFIED')
        query.assert_not_called()
        # A cached terminal label must not bypass current receipt/provenance checks.
        result['state']='FAILED_CLOSED'
        (self.directory/'cleanup-reconciliation.json').write_text(json.dumps(result),encoding='utf-8')
        self.router.closed_apps.clear()
        with patch.object(mss,'process_identity') as query:
            repeated=self.router.recheck_cleanup(APP_ID)
        self.assertEqual(repeated['state'],'CLEANUP_PENDING')
        query.assert_not_called()
    def setUp(self):
        fixture = tempfile.TemporaryDirectory(prefix="mss-archive-cleanup-")
        self.addCleanup(fixture.cleanup)
        self.repo = Path(fixture.name)
        self.directory = self.repo / "proof/mss-universal/connections" / ("e" * 32) / APP_ID
        receipt_dir = self.directory / "sessions" / ("fixture-" + SESSION)
        receipt_dir.mkdir(parents=True)
        profile = {"id": "fixture", "admission": "TRUSTED_DEVELOPMENT",
                   "working_directory": str(self.directory / "work"),
                   "session_root": str(self.directory / "sessions"),
                   "app_executable": str(self.directory / "app.exe"), "app_sha256": "a" * 64,
                   "remote_sha256": "b" * 64, "makepad_revision": "c" * 40}
        profile_bytes = json.dumps(profile).encode()
        (self.directory / "profile.json").write_bytes(profile_bytes)
        receipt = receipt_fixture(early_exit=True)
        receipt.update({"app_image_expected": profile["app_executable"],
                        "profile_sha256": hashlib.sha256(profile_bytes).hexdigest(),
                        "app_sha256": profile["app_sha256"], "remote_sha256": profile["remote_sha256"],
                        "makepad_revision_declared": profile["makepad_revision"],
                        "profile_id": "fixture", "session_id": SESSION})
        self.receipt_path = receipt_dir / "session.json"
        self.receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        self.closure_path = self.directory / "closure.json"
        self.closure_path.write_text(json.dumps({"app_id": APP_ID, "profile": "todo",
            "state": "CLEANUP_PENDING", "pid": None, "app_birth_utc": None}), encoding="utf-8")
        self.router = mss.Router.__new__(mss.Router)
        self.router.catalog = SimpleNamespace(repo=self.repo)
        self.router.apps, self.router.closed_apps, self.router.shared = {}, {}, None

    def test_invalid_app_id_is_refused_before_process_query(self):
        with patch.object(mss, "process_identity") as query:
            for value in ("unknown", "app_../outside", "app_" + "x" * 32):
                with self.subTest(value=value), self.assertRaises(mss.ToolFailure) as error:
                    self.router.recheck_cleanup(value)
                self.assertEqual(error.exception.code, "INVALID_ARGUMENT")
            query.assert_not_called()

    def test_missing_pid_and_proof_stays_pending_without_process_query(self):
        receipt = json.loads(self.receipt_path.read_bytes())
        receipt["app_pid"] = None
        receipt.pop("exit_proof")
        self.receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        with patch.object(mss, "process_identity") as query:
            result = self.router.recheck_cleanup(APP_ID)
            self.assertEqual(result["state"], "CLEANUP_PENDING")
            self.assertEqual(result["reason"], "MISSING_OWNED_PROCESS_EXIT_IDENTITY")
            query.assert_not_called()

    def test_terminal_archive_recheck_is_idempotent_and_preserves_originals(self):
        originals = {p: p.read_bytes() for p in (self.receipt_path, self.closure_path, self.directory / "profile.json")}
        with patch.object(mss, "process_identity", side_effect=OSError(87, "PID absent")) as query:
            first = self.router.recheck_cleanup(APP_ID)
            self.assertEqual(first["state"], "FAILED_CLOSED")
            self.assertEqual(query.call_count, 1)
            evidence_count = len(list(self.directory.glob("cleanup-reconciliation-*.json")))
            second = self.router.recheck_cleanup(APP_ID)
            self.assertTrue(second["already_reconciled"])
            self.assertEqual(query.call_count, 1)
            self.assertEqual(len(list(self.directory.glob("cleanup-reconciliation-*.json"))), evidence_count)
        self.assertEqual({p: p.read_bytes() for p in originals}, originals)

    def test_current_original_process_contradicts_exit_receipt_and_is_not_signalled(self):
        with patch.object(mss, "process_identity", return_value={"birth": BIRTH_TICKS}) as query, \
                patch.object(mss.subprocess, "Popen") as launch:
            result = self.router.recheck_cleanup(APP_ID)
            self.assertEqual(result["state"], "CLEANUP_PENDING")
            self.assertEqual(result["observation"]["kind"], "ORIGINAL_PROCESS_STILL_LIVE")
            query.assert_called_once_with(1734)
            launch.assert_not_called()

    def test_reused_pid_is_not_authority_over_replacement(self):
        with patch.object(mss, "process_identity", return_value={"birth": BIRTH_TICKS + 1}) as query, \
                patch.object(mss.subprocess, "Popen") as launch:
            result = self.router.recheck_cleanup(APP_ID)
            self.assertEqual(result["state"], "FAILED_CLOSED")
            self.assertEqual(result["observation"]["kind"], "PID_REUSED_NO_AUTHORITY_OVER_REPLACEMENT")
            query.assert_called_once_with(1734)
            launch.assert_not_called()

    def test_access_denied_is_unknown_not_pid_absence(self):
        with patch.object(mss, "process_identity", side_effect=OSError(5, "access denied")):
            result = self.router.recheck_cleanup(APP_ID)
        self.assertEqual(result["state"], "CLEANUP_PENDING")
        self.assertEqual(result["reason"], "CURRENT_IDENTITY_QUERY_UNAVAILABLE")

    def test_conflicting_archived_pid_refused_before_current_process_query(self):
        metadata = json.loads(self.closure_path.read_bytes())
        metadata["pid"] = 9999
        self.closure_path.write_text(json.dumps(metadata), encoding="utf-8")
        with patch.object(mss, "process_identity") as query, self.assertRaises(mss.ToolFailure) as error:
            self.router.recheck_cleanup(APP_ID)
        self.assertEqual(error.exception.code, "OWNERSHIP_UNVERIFIED")
        query.assert_not_called()


if __name__ == "__main__":
    unittest.main()
