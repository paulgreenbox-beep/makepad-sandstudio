"""Router checks for the owned Remote discovery directory, without native apps."""

import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

tools = Path(os.environ.get("MSS_TEST_TOOLS", Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(tools))

import mss_universal as mss


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name).resolve()
        self.session_id = "a" * 32
        self.session = root / "sessions" / f"todo-{self.session_id}"
        self.session.mkdir(parents=True)
        self.remote = root / "MSS-Remote" / self.session_id
        self.remote.mkdir(parents=True)
        app_image = root / "todo.exe"
        profile = root / "profile.json"
        profile.write_text(json.dumps({"remote_executable": str(root / "makepad-remote.exe")}), encoding="utf-8")
        (root / "makepad-remote.exe").touch()
        self.app = mss.App("todo", "app_a", root)
        self.app.plan = mss.LaunchPlan([], root / "work", {"TEMP": "ignored", "TMP": "ignored"},
                                       self.session.parent, app_image, "a" * 64, "b" * 64, "c" * 40,
                                       "d" * 64, "semantic")
        self.app.receipt_path = self.session / "session.json"
        self.app.identity = {"app_pid": 321, "app_birth_utc": "2026-11-13T01:00:00Z",
                             "app_image": str(app_image), "session_id": self.session_id,
                             "remote_directory": str(self.remote)}
        self.receipt = self.app.identity | {
            "status": "READY", "profile_id": "todo", "profile_sha256": "d" * 64,
            "app_sha256": "a" * 64, "remote_sha256": "b" * 64,
            "makepad_revision_declared": "c" * 40,
        }
        self.discovery = {"pid": 321, "app": "todo.exe", "socket": "tcp:127.0.0.1:1234", "token": "9" * 64}

    def write_receipt(self):
        self.app.receipt_path.write_text(json.dumps(self.receipt), encoding="utf-8")

    def test_client_uses_exact_owned_temp_and_pid(self):
        self.write_receipt()
        (self.remote / "makepad-remote-321.json").write_text(json.dumps(self.discovery), encoding="utf-8")
        with patch.object(mss, "check_pin"), patch.object(mss, "Peer") as create_peer:
            create_peer.return_value.call.return_value = mss.result_json(
                {"pid": 321, "app": "todo.exe", "w": [{"i": 0}]})
            self.app.direct_peer(self.session)
        plan = create_peer.call_args.args[0]
        self.assertEqual(plan.env, {"TEMP": str(self.remote), "TMP": str(self.remote)})
        self.assertEqual(plan.command[1:], ["mcp", "321"])

    def test_legacy_receipt_without_remote_directory_keeps_old_layout(self):
        del self.receipt["remote_directory"]
        del self.app.identity["remote_directory"]
        self.write_receipt()
        self.assertEqual(self.app.discovery_directory(self.app.receipt()), self.session)

    def test_ready_receipt_cannot_remove_or_replace_a_bound_directory(self):
        for directory in (None, str(self.session)):
            with self.subTest(directory=directory):
                if directory is None:
                    self.receipt.pop("remote_directory", None)
                else:
                    self.receipt["remote_directory"] = directory
                self.write_receipt()
                with self.assertRaises(mss.ToolFailure) as error:
                    self.app.receipt()
                self.assertEqual(error.exception.code, "IDENTITY_UNVERIFIED")

    def test_legacy_identity_cannot_acquire_new_directory_through_receipt(self):
        del self.app.identity["remote_directory"]
        self.write_receipt()
        with self.assertRaises(mss.ToolFailure):
            self.app.receipt()

    def test_remote_directory_must_be_this_session_and_never_falls_back(self):
        other = self.remote.with_name("b" * 32)
        other.mkdir()
        for directory in (None, str(other), str(self.session)):
            with self.subTest(directory=directory):
                self.receipt["remote_directory"] = directory
                with self.assertRaises(mss.ToolFailure):
                    self.app.discovery_directory(self.receipt)

    def test_lost_or_foreign_discovery_does_not_start_a_client(self):
        self.write_receipt()
        leaf = "makepad-remote-321.json"
        (self.session / leaf).write_text(json.dumps(self.discovery), encoding="utf-8")
        invalid = [{"pid": 322}, {"app": "neighbor.exe"}, {"socket": "tcp:192.0.2.1:1234"},
                   {"token": "invalid"}]
        with patch.object(mss, "check_pin"), patch.object(mss, "Peer") as create_peer:
            with self.assertRaises(mss.ToolFailure):
                self.app.direct_peer(self.session)
            for change in invalid:
                with self.subTest(change=change):
                    (self.remote / leaf).write_text(json.dumps(self.discovery | change), encoding="utf-8")
                    with self.assertRaises(mss.ToolFailure) as error:
                        self.app.direct_peer(self.session)
                    self.assertNotIn(self.discovery["token"], str(error.exception))
        create_peer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
