"""Exercise the production MSS transfer router without launching GUI processes."""

from contextlib import redirect_stderr
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from mss_universal import App, Router, TransportFailure


FORMAT = "writer-rich-text"
SOURCE_TOOL = "writer__export_fragment"
TARGET_TOOL = "writer__paste_fragment"
TEXT = "Приватный фрагмент"
STYLE = {
    "font_family": "Arial", "size_half_points": 32,
    "bold": True, "italic": False, "underline": True, "strikethrough": False,
    "foreground": None, "background": None,
}


def native(value, *, error=False):
    message = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return {"content": [{"type": "text", "text": message}], "isError": error}


def fragment():
    return {"format": FORMAT, "version": 1, "runs": [{"text": TEXT, "style": STYLE.copy()}]}


def pasted(**overrides):
    return {
        "status": "applied", "model_match": True, "inserted_chars": len(TEXT),
        "bold_chars": len(TEXT), "italic_chars": 0, "underline_chars": len(TEXT),
        "strikethrough_chars": 0,
    } | overrides


class FakePeer:
    def __init__(self, tool, response):
        self.tool = tool
        self.response = response
        self.process = SimpleNamespace(poll=lambda: None)
        self.calls = []

    def call(self, tool, arguments):
        self.calls.append((tool, deepcopy(arguments)))
        if tool != self.tool:
            raise AssertionError(f"Unexpected native tool: {tool}")
        if isinstance(self.response, Exception):
            raise self.response
        return deepcopy(self.response)


class TransferTests(unittest.TestCase):
    def setUp(self):
        fixture = tempfile.TemporaryDirectory()
        self.addCleanup(fixture.cleanup)
        self.router = Router.__new__(Router)
        self.router.root = Path(fixture.name)
        self.router.initialized = True
        self.source = self.app("app_source", 1001, SOURCE_TOOL, native(fragment()))
        self.target = self.app("app_target", 1002, TARGET_TOOL, native(pasted()))
        self.router.apps = {app.app_id: app for app in (self.source, self.target)}
        self.arguments = {"source_app_id": self.source.app_id, "target_app_id": self.target.app_id,
                          "format": FORMAT}

    def app(self, app_id, pid, tool, response):
        directory = self.router.root / app_id
        session_root = directory / "sessions"
        receipt_dir = session_root / "owned"
        receipt_dir.mkdir(parents=True)
        app = App("rudraoffice", app_id, directory)
        app.state = "READY"
        app.peer = FakePeer(tool, response)
        app.native_tools = {tool}
        app.plan = SimpleNamespace(
            access="semantic", makepad_revision="a" * 40, session_root=session_root,
            app_image=directory / "rudra-office-app.exe", build_id="test-build",
            app_sha256="b" * 64, remote_sha256="c" * 64, profile_sha256="d" * 64,
        )
        app.identity = {
            "app_pid": pid, "app_birth_utc": "2026-11-06T10:00:00Z",
            "app_image": str(app.plan.app_image), "session_id": app_id,
        }
        receipt = {
            "status": "READY", "profile_sha256": app.plan.profile_sha256,
            "app_sha256": app.plan.app_sha256, "remote_sha256": app.plan.remote_sha256,
            "makepad_revision_declared": app.plan.makepad_revision,
        } | app.identity
        (receipt_dir / "session.json").write_text(json.dumps(receipt), encoding="utf-8")
        return app

    def transfer(self, **overrides):
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "mss_transfer_fragment", "arguments": self.arguments | overrides,
        }}
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            response = self.router.handle(request)
        self.assertNotIn(TEXT, json.dumps(response, ensure_ascii=False))
        self.assertNotIn(TEXT, stderr.getvalue())
        return response["result"]

    def assert_denied(self, code, **arguments):
        result = self.transfer(**arguments)
        self.assertTrue(result["isError"], result)
        self.assertEqual(result["structuredContent"]["code"], code, result)
        return result["structuredContent"]

    def assert_no_native_call(self):
        self.assertEqual(self.source.peer.calls, [])
        self.assertEqual(self.target.peer.calls, [])

    def update_target_receipt(self, **fields):
        path = self.target.plan.session_root / "owned" / "session.json"
        receipt = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps(receipt | fields), encoding="utf-8")

    def assert_unknown_and_no_retry(self):
        self.assert_denied("OUTCOME_UNKNOWN")
        self.assertEqual(self.target.state, "OUTCOME_UNKNOWN")
        self.assertEqual(len(self.source.peer.calls), 1)
        self.assertEqual(len(self.target.peer.calls), 1)
        self.assert_denied("APP_UNAVAILABLE")
        self.assertEqual(len(self.source.peer.calls), 1)
        self.assertEqual(len(self.target.peer.calls), 1)
        receipt = (self.target.directory / "channel-state.json").read_text(encoding="utf-8")
        self.assertNotIn(TEXT, receipt)
        self.assertEqual(json.loads(receipt)["state"], "OUTCOME_UNKNOWN")

    def test_valid_transfer_sends_one_typed_fragment_and_returns_only_metadata(self):
        result = self.transfer()
        self.assertFalse(result["isError"], result)
        self.assertEqual(self.source.peer.calls, [(SOURCE_TOOL, {"source": "clipboard"})])
        [(tool, arguments)] = self.target.peer.calls
        self.assertEqual(tool, TARGET_TOOL)
        self.assertEqual(arguments["fragment"], fragment())
        self.assertEqual(result["structuredContent"]["inserted_chars"], len(TEXT))
        self.assertTrue(result["structuredContent"]["model_match"])
        self.assertEqual(result["structuredContent"]["runs"], 1)
        self.assertNotIn("fragment", result["structuredContent"])
        self.assertEqual(self.target.state, "READY")

    def test_unknown_source_or_target_is_refused_before_export(self):
        for key in ("source_app_id", "target_app_id"):
            with self.subTest(key=key):
                self.assert_denied("UNKNOWN_APP", **{key: "app_foreign"})
                self.assert_no_native_call()

    def test_same_app_is_refused_before_export(self):
        self.assert_denied("INVALID_ARGUMENT", target_app_id=self.source.app_id)
        self.assert_no_native_call()

    def test_two_app_ids_for_one_pid_are_refused_before_export(self):
        self.target.identity["app_pid"] = self.source.identity["app_pid"]
        self.update_target_receipt(app_pid=self.target.identity["app_pid"])
        self.assert_denied("INVALID_ARGUMENT")
        self.assert_no_native_call()

    def test_incompatible_format_is_refused_before_export(self):
        self.assert_denied("UNSUPPORTED_FORMAT", format="text/plain")
        self.assert_no_native_call()

    def test_client_cannot_supply_fragment_payload(self):
        self.assert_denied("INVALID_ARGUMENT", fragment=fragment())
        self.assert_no_native_call()

    def test_incompatible_profile_is_refused_before_export(self):
        self.target.profile = "todo"
        self.assert_denied("UNSUPPORTED")
        self.assert_no_native_call()

    def test_read_only_target_is_refused_before_export(self):
        self.target.plan.access = "read-only"
        self.assert_denied("UNSUPPORTED")
        self.assert_no_native_call()

    def test_missing_native_capability_is_refused_before_export(self):
        self.target.native_tools.clear()
        self.assert_denied("UNSUPPORTED")
        self.assert_no_native_call()

    def test_incompatible_makepad_revision_is_refused_before_export(self):
        self.target.plan.makepad_revision = "e" * 40
        self.update_target_receipt(makepad_revision_declared=self.target.plan.makepad_revision)
        self.assert_denied("UNSUPPORTED")
        self.assert_no_native_call()

    def test_missing_ownership_receipt_is_refused_before_export(self):
        self.target.plan.session_root = self.target.directory / "unowned"
        self.assert_denied("IDENTITY_UNVERIFIED")
        self.assert_no_native_call()

    def test_malformed_exports_do_not_reach_target(self):
        for invalid in (
            fragment() | {"format": "text/plain"},
            fragment() | {"version": True},
            fragment() | {"runs": "not an array"},
            fragment() | {"runs": [{"text": TEXT, "style": False}]},
        ):
            with self.subTest(invalid=invalid):
                self.source.peer.response = native(invalid)
                self.assert_denied("INVALID_FRAGMENT")
                self.assertEqual(self.target.peer.calls, [])
                self.assertEqual(self.target.state, "READY")

    def test_oversize_utf8_export_does_not_reach_target(self):
        data = fragment()
        data["runs"][0]["text"] = "я" * 9000
        self.source.peer.response = native(data)
        self.assert_denied("FRAGMENT_TOO_LARGE")
        self.assertEqual(self.target.peer.calls, [])

    def test_oversize_escaped_transport_does_not_reach_target(self):
        data = fragment()
        data["runs"][0]["text"] = "я" * 3000
        self.source.peer.response = native(data)
        self.assert_denied("FRAGMENT_TOO_LARGE")
        self.assertEqual(self.target.peer.calls, [])

    def test_explicit_source_refusal_does_not_reach_target(self):
        self.source.peer.response = native({"status": "refused", "code": "EMPTY_CLIPBOARD"})
        result = self.assert_denied("TRANSFER_REFUSED")
        self.assertEqual((result["phase"], result["reason"]), ("export", "EMPTY_CLIPBOARD"))
        self.assertEqual(self.target.peer.calls, [])
        self.assertEqual(self.target.state, "READY")

    def test_explicit_destination_refusal_does_not_freeze_app_or_retry(self):
        self.target.peer.response = native({"status": "refused", "code": "DESTINATION_NOT_READY"})
        result = self.assert_denied("TRANSFER_REFUSED")
        self.assertEqual((result["phase"], result["reason"]), ("paste", "DESTINATION_NOT_READY"))
        self.assertEqual(len(self.target.peer.calls), 1)
        self.assertEqual(self.target.state, "READY")

    def test_export_transport_loss_never_writes_target(self):
        self.source.peer.response = TransportFailure(TEXT)
        self.assert_denied("TRANSPORT_LOST")
        self.assertEqual(self.source.state, "TRANSPORT_LOST")
        self.assertEqual(self.target.peer.calls, [])
        self.assertEqual(self.target.state, "READY")

    def test_target_timeout_marks_uncertain_and_never_replays(self):
        self.target.peer.response = TransportFailure(TEXT)
        self.assert_unknown_and_no_retry()

    def test_malformed_target_response_marks_uncertain_and_never_replays(self):
        self.target.peer.response = native(f"malformed: {TEXT}")
        self.assert_unknown_and_no_retry()

    def test_target_transport_error_is_sanitized_and_never_replayed(self):
        self.target.peer.response = native(f"failed: {TEXT}", error=True)
        self.assert_unknown_and_no_retry()

    def test_target_readback_mismatch_marks_uncertain_and_never_replays(self):
        self.target.peer.response = native(pasted(model_match=False))
        self.assert_unknown_and_no_retry()

    def test_untyped_destination_refusal_marks_uncertain_and_never_replays(self):
        self.target.peer.response = native({"status": "refused", "code": {"secret": TEXT}})
        self.assert_unknown_and_no_retry()

    def test_deeply_nested_target_json_marks_uncertain_and_never_replays(self):
        self.target.peer.response = native("[" * 1500 + "null" + "]" * 1500)
        self.assert_unknown_and_no_retry()


if __name__ == "__main__":
    unittest.main()
