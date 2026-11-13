"""Model-free tests for addressed resize and its pixel-frame postcondition."""

import base64
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
import zlib


helpers = os.environ.get("MSS_TEST_HELPERS")
if helpers:
    sys.path.insert(0, helpers)
tools = Path(os.environ.get("MSS_TEST_TOOLS", Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(tools))

from mss_shared import Store
from mss_universal import App, Router, ToolFailure, TransportFailure, result_json


WINDOW = 17
PID = 201
START = [320, 240]
REQUESTED = [641, 360]
OBSERVED = [640.8, 360]
PIXELS = [801, 450]


def window_status(points, pixels, pid=PID):
    return {"pid": pid, "w": [{"i": WINDOW, "sz": points, "px": pixels, "dpi": 1.25}]}


def png_bytes(width, height):
    def chunk(name, data):
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data))

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    scanlines = (b"\x00" + b"\x80" * width) * height
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(scanlines)) + chunk(b"IEND", b"")


class ResizePeer:
    def __init__(self):
        self.process = SimpleNamespace(poll=lambda: None)
        self.calls = []
        self.statuses = [window_status(START, [400, 300]), window_status(OBSERVED, PIXELS)]
        self.ack = {"resize": REQUESTED}
        self.frame_window = WINDOW
        self.frame_pixels = PIXELS
        self.corrupt_file = False

    def call(self, name, args):
        self.calls.append((name, dict(args)))
        if name == "ui__status":
            return result_json(self.statuses.pop(0))
        if name == "ui__resize":
            if isinstance(self.ack, Exception):
                raise self.ack
            return result_json(self.ack)
        if name == "ui__grab":
            image = png_bytes(*self.frame_pixels)
            Path(args["out"]).write_bytes(image if not self.corrupt_file else b"wrong content")
            result = result_json({"png": args["out"], "w": self.frame_window,
                                  "sz": self.frame_pixels, "capture_kind": "pixels"})
            result["content"].append({"type": "image", "mimeType": "image/png",
                                      "data": base64.b64encode(image).decode("ascii")})
            return result
        raise AssertionError(f"Unexpected call {name}")


class ResizeTests(unittest.TestCase):
    def setUp(self):
        fixture = tempfile.TemporaryDirectory(prefix="mss-resize-test-")
        self.addCleanup(fixture.cleanup)
        self.root = Path(fixture.name)
        directory = self.root / "app_resize"
        self.app = App("todo", "app_resize", directory)
        self.app.artifacts.mkdir(parents=True)
        sessions = directory / "sessions"
        session = sessions / "fixture"
        session.mkdir(parents=True)
        self.app.plan = SimpleNamespace(access="semantic", session_root=sessions, app_image=directory / "app.exe",
                                       app_sha256="a" * 64, remote_sha256="b" * 64,
                                       profile_sha256="c" * 64, makepad_revision="d" * 40, build_id="baseline")
        self.app.identity = {"app_pid": PID, "app_birth_utc": "2026-11-11T00:00:00Z",
                             "app_image": str(self.app.plan.app_image), "session_id": "fixture"}
        receipt = self.app.identity | {"status": "READY", "profile_sha256": self.app.plan.profile_sha256,
                                       "app_sha256": self.app.plan.app_sha256,
                                       "remote_sha256": self.app.plan.remote_sha256,
                                       "makepad_revision_declared": self.app.plan.makepad_revision}
        (session / "session.json").write_text(json.dumps(receipt), encoding="utf-8")
        self.app.native_tools = {"ui__resize", "ui__status", "ui__grab"}
        self.app.state = "READY"
        self.peer = self.app.peer = ResizePeer()
        self.store_path = self.root / "control.sqlite3"
        self.store = Store(self.store_path, "owner", {"pid": 1, "birth": 100, "windows_session": 1}, lambda _: True)
        self.store.publish(self.app.app_id, {"state": "READY", "profile": "todo"})
        self.router = Router.__new__(Router)
        self.router.initialized = True
        self.router.apps = {self.app.app_id: self.app}
        self.router.shared = self.store

    def resize(self, **overrides):
        arguments = {"app_id": self.app.app_id, "w": WINDOW, "width": REQUESTED[0], "height": REQUESTED[1]}
        response = self.router.handle({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "mss_resize", "arguments": arguments | overrides},
        })
        return response["result"]

    def assert_error(self, result, code):
        self.assertTrue(result["isError"], result)
        self.assertEqual(result["structuredContent"]["code"], code)

    def test_resize_verifies_rounded_layout_and_matching_pixels(self):
        result = self.resize()
        self.assertFalse(result["isError"], result)
        data = result["structuredContent"]
        self.assertEqual(data["code"], "RESIZED")
        self.assertEqual((data["app_id"], data["w"]), (self.app.app_id, WINDOW))
        self.assertEqual((data["layout_size"], data["dpi"], data["sz"]), (OBSERVED, 1.25, PIXELS))
        self.assertEqual(data["status"], window_status(OBSERVED, PIXELS))
        self.assertEqual(data["native_ack"], {"resize": REQUESTED})
        self.assertEqual(data["effect"], "VERIFIED")
        self.assertEqual(self.store.operation(self.app.app_id, data["operation_id"])["effect"], "VERIFIED")
        path = Path(data["png"])
        self.assertEqual(path.parent, self.app.artifacts)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), data["sha256"])
        self.assertEqual([p["type"] for p in result["content"]], ["text"])
        self.assertEqual(self.peer.calls[:3], [
            ("ui__status", {}), ("ui__resize", {"w": 641, "h": 360, "window": WINDOW}), ("ui__status", {}),
        ])
        self.assertEqual(self.peer.calls[3], ("ui__grab", {"w": WINDOW, "scale": 1, "out": str(path)}))

    def test_duplicate_size_captures_without_dispatching_resize(self):
        self.peer.statuses = [window_status(OBSERVED, PIXELS)]
        result = self.resize()
        self.assertFalse(result["isError"], result)
        self.assertEqual(result["structuredContent"]["code"], "UNCHANGED")
        self.assertIsNone(result["structuredContent"]["native_ack"])
        self.assertEqual([name for name, _ in self.peer.calls], ["ui__status", "ui__grab"])
        self.assertFalse(self.app.build_action_dispatched)

    def test_resize_does_not_supply_candidate_activation_evidence(self):
        self.app.requested_build = self.app.plan.build_id
        self.app.build_tree_observed = True
        self.app.build_postcondition = {"operation_sequence": 0}
        self.assertFalse(self.resize()["isError"])
        self.assertFalse(self.app.build_action_dispatched)
        self.assertIsNone(self.app.build_png)
        self.assertIsNone(self.app.build_postcondition)

    def test_bad_input_rejected_before_queue_or_native_calls(self):
        for args in ({"w": -1}, {"width": 0}, {"height": 16385}, {"width": True}, {"height": "360"}):
            with self.subTest(args=args):
                self.assert_error(self.resize(**args), "INVALID_ARGUMENT")
        self.assertEqual(self.peer.calls, [])
        self.assertEqual(self.store.operations(self.app.app_id), [])

    def test_unknown_window_is_refused_before_resize(self):
        self.assert_error(self.resize(w=WINDOW + 1), "UNKNOWN_WINDOW")
        self.assertEqual(self.peer.calls, [("ui__status", {})])

    def test_wrong_process_is_refused_before_resize(self):
        self.peer.statuses[0] = window_status(START, [400, 300], pid=PID + 1)
        self.assert_error(self.resize(), "IDENTITY_UNVERIFIED")
        self.assertEqual(self.peer.calls, [("ui__status", {})])

    def test_missing_native_resize_is_unsupported(self):
        self.app.native_tools.remove("ui__resize")
        self.assert_error(self.resize(), "UNSUPPORTED")
        self.assertEqual(self.peer.calls, [])

    def test_read_only_profile_is_denied_without_dispatch(self):
        self.app.plan.access = "read-only"
        self.assert_error(self.resize(), "READ_ONLY_PROFILE")
        self.assertEqual(self.peer.calls, [])

    def test_read_only_preview_reuses_only_its_own_frame_files(self):
        self.app.plan.access = "read-only"
        for _ in range(2):
            result = self.app.call("mss_grab", {"w": WINDOW, "preview": True})
            self.assertFalse(result["isError"], result)
            data = result["structuredContent"]
            self.assertEqual((data["app_id"], data["pid"], data["w"]), (self.app.app_id, PID, WINDOW))
            path = Path(data["png"])
            self.assertEqual(path, self.app.artifacts / "preview.png")
            self.assertEqual(data["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual([part["type"] for part in result["content"]], ["text"])
        self.assertEqual(sorted(path.name for path in self.app.artifacts.iterdir()), ["preview.json", "preview.png"])
        self.assertEqual([name for name, _ in self.peer.calls], ["ui__grab", "ui__grab"])

    def test_preview_refuses_wrong_window_and_semantic_profile(self):
        with self.assertRaisesRegex(ToolFailure, "owned read-only profile"):
            self.app.call("mss_grab", {"w": WINDOW, "preview": True})
        self.assertEqual(self.peer.calls, [])
        self.app.plan.access = "read-only"
        self.peer.frame_window = WINDOW + 1
        with self.assertRaisesRegex(ToolFailure, "different window"):
            self.app.call("mss_grab", {"w": WINDOW, "preview": True})
        self.assertFalse((self.app.artifacts / "preview.json").exists())

    def test_attached_read_only_participant_cannot_resize(self):
        self.store.share(self.app.app_id, "read")
        reader = Store(self.store_path, "reader", {"pid": 2, "birth": 200, "windows_session": 1}, lambda _: True)
        reader.attach(self.app.app_id)
        self.router.shared = reader
        self.assert_error(self.resize(), "CONTROL_REQUIRED")
        self.assertEqual(self.peer.calls, [])

    def test_transport_loss_quarantines_after_one_resize_request(self):
        self.peer.ack = TransportFailure("fixture reply lost")
        self.assert_error(self.resize(), "OUTCOME_UNKNOWN")
        self.assertEqual(self.store.app(self.app.app_id)["state"], "OUTCOME_UNKNOWN")
        self.assert_error(self.resize(), "OUTCOME_UNKNOWN")
        self.assertEqual([name for name, _ in self.peer.calls], ["ui__status", "ui__resize"])

    def test_wrong_acknowledgement_quarantines_without_capture(self):
        self.peer.ack = {"resize": START}
        self.assert_error(self.resize(), "OUTCOME_UNKNOWN")
        self.assertEqual([name for name, _ in self.peer.calls], ["ui__status", "ui__resize"])

    def test_wrong_post_resize_geometry_is_unknown(self):
        self.peer.statuses[1] = window_status(START, [400, 300])
        self.assert_error(self.resize(), "OUTCOME_UNKNOWN")
        self.assertEqual([name for name, _ in self.peer.calls], ["ui__status", "ui__resize", "ui__status"])

    def test_capture_from_wrong_window_is_unknown(self):
        self.peer.frame_window = WINDOW + 1
        self.assert_error(self.resize(), "OUTCOME_UNKNOWN")
        self.assertEqual(self.store.app(self.app.app_id)["state"], "OUTCOME_UNKNOWN")

    def test_capture_must_match_status_pixel_dimensions(self):
        self.peer.frame_pixels = [800, 450]
        self.assert_error(self.resize(), "OUTCOME_UNKNOWN")
        self.assertEqual(self.store.app(self.app.app_id)["state"], "OUTCOME_UNKNOWN")

    def test_duplicate_size_capture_failure_does_not_quarantine_mutation(self):
        self.peer.statuses = [window_status(OBSERVED, PIXELS)]
        self.peer.corrupt_file = True
        self.assert_error(self.resize(), "CAPTURE_UNVERIFIED")
        self.assertEqual(self.store.app(self.app.app_id)["state"], "READY")
        self.assertEqual([name for name, _ in self.peer.calls], ["ui__status", "ui__grab"])


if __name__ == "__main__":
    unittest.main()
