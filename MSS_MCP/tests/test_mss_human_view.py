"""Model-free contracts for compact attachment capture and pinned CAD presses."""

import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest


helpers = os.environ.get("MSS_TEST_HELPERS")
if helpers:
    sys.path.insert(0, helpers)
tools = Path(os.environ.get("MSS_TEST_TOOLS", Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(tools))

from mss_profiles import Catalog
from mss_shared import Store
from mss_universal import App, Router, result_json


APP_ID = "app_" + "a" * 32
PID = 201
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aY9sAAAAASUVORK5CYII="
)
PATHS = (
    "body.app_view.file_toolbar.workspace_2d",
    "body.app_view.file_toolbar.workspace_3d",
)
APP_HASH = "A" * 64
GEOMETRY = {"if_layout_width": 320.5, "if_layout_height": 240, "if_dpi": 1.25}


class NativePeer:
    def __init__(self):
        self.process = SimpleNamespace(poll=lambda: None)
        self.calls = []
        self.node = {"id": "1e", "path": PATHS[0], "role": "button", "actions": "focus,press"}
        self.window = "2:0"
        self.frame_window = 0
        self.status = {"pid": PID, "w": [{"i": 0, "sz": [320.5, 240], "dpi": 1.25}]}
        self.input_error = None

    def call(self, name, args):
        self.calls.append((name, dict(args)))
        if name == "ui__ui":
            return result_json({"trees": [{"window": self.window, "nodes": [self.node]}]})
        if name == "ui__ui_act":
            return result_json({"result": "handled"})
        if name == "ui__status":
            return result_json(self.status)
        if name == "ui__activity":
            return result_json({"user_seq": 8})
        if name in {"ui__key", "ui__mouse"}:
            if self.input_error is not None:
                return {"isError": True, "content": [
                    {"type": "text", "text": "failed: " + json.dumps(self.input_error)},
                ]}
            return result_json({"ok": 1})
        if name == "ui__grab":
            Path(args["out"]).write_bytes(PNG)
            response = result_json({"png": args["out"], "w": self.frame_window,
                                    "sz": [1, 1], "capture_kind": "pixels"})
            response["content"].append({"type": "image", "mimeType": "image/png",
                                        "data": base64.b64encode(PNG).decode("ascii")})
            return response
        raise AssertionError(f"Unexpected call {name}")


class HumanViewTests(unittest.TestCase):
    def setUp(self):
        fixture = tempfile.TemporaryDirectory(prefix="mss-human-view-")
        self.addCleanup(fixture.cleanup)
        root = Path(fixture.name)
        self.store_path = root / "control.sqlite3"
        self.owner = self.store("owner", 1)
        self.owner.publish(APP_ID, {"state": "READY", "profile": "ai-cad"})
        self.app = App("ai-cad", APP_ID, root / "attachment-own")
        self.app.artifacts.mkdir(parents=True)
        self.app.plan = SimpleNamespace(access="read-only", allowed_press_paths=PATHS,
                                        app_image=root / "app.exe", app_sha256=APP_HASH, build_id=None)
        self.app.identity = {"app_pid": PID}
        self.app.receipt = lambda: {"status": "READY"}
        self.app.state = "READY"
        self.peer = self.app.peer = self.app.read_peer = NativePeer()
        self.app.native_tools = {"ui__grab", "ui__ui_act", "ui__key", "ui__mouse", "ui__status", "ui__activity"}
        self.router = Router.__new__(Router)
        self.router.initialized = True
        self.router.apps = {APP_ID: self.app}
        self.router.shared = self.owner

    def store(self, connection, pid):
        return Store(self.store_path, connection, {"pid": pid, "birth": 100, "windows_session": 1}, lambda _: True)

    def attach(self, mode):
        self.owner.share(APP_ID, mode)
        viewer = self.store("viewer", 2)
        viewer.attach(APP_ID)
        self.router.shared = viewer
        self.app.participant = True

    def call(self, name, **args):
        return self.router.handle({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": {"app_id": APP_ID} | args},
        })["result"]

    def act(self, **args):
        return self.call("mss_ui_act", **({"node": "1e", "w": "2:0", "action": "press"} | args))

    def assert_code(self, reply, code):
        self.assertTrue(reply["isError"])
        self.assertEqual(reply["structuredContent"]["code"], code)

    def assert_preview(self):
        result = self.call("mss_grab", w=0, preview=True)
        self.assertFalse(result.get("isError", False), result)
        frame = result["structuredContent"]
        png = self.app.artifacts.resolve() / "preview.png"
        self.assertEqual(frame, {"png": str(png), "w": 0, "sz": [1, 1], "capture_kind": "pixels",
                                 "app_id": APP_ID, "pid": PID, "sha256": hashlib.sha256(PNG).hexdigest()})
        self.assertEqual(png.read_bytes(), PNG)
        self.assertTrue(png.with_suffix(".json").is_file())
        self.assertTrue(all(part["type"] == "text" for part in result["content"]))
        self.assertEqual(self.peer.calls[-1], ("ui__grab", {"w": 0, "out": str(png)}))
        self.assertIsNone(self.app.build_png)

    def test_preview_uses_the_attachment_artifacts_for_both_admitted_access_modes(self):
        self.attach("read")
        for access in ("semantic", "read-only"):
            with self.subTest(access=access):
                self.app.plan.access = access
                self.assert_preview()

    def test_preview_preserves_owned_read_only_and_rejects_wrong_window(self):
        self.assert_preview()
        self.peer.frame_window = 8
        self.assert_code(self.call("mss_grab", w=0, preview=True), "CAPTURE_UNVERIFIED")

    def test_read_viewer_cannot_dispatch_press(self):
        self.attach("read")
        self.assert_code(self.act(), "CONTROL_REQUIRED")
        self.assertEqual(self.peer.calls, [])

    def test_control_viewer_can_press_only_fresh_matching_native_buttons(self):
        self.attach("control")
        for path in PATHS:
            with self.subTest(path=path):
                self.peer.node["path"] = path
                reply = self.act()
                self.assertFalse(reply.get("isError", False), reply)
                self.assertEqual(reply["structuredContent"]["effect"], "NOT_VERIFIED")
        self.assertEqual([name for name, _ in self.peer.calls], ["ui__ui", "ui__ui_act"] * 2)

    def test_read_only_blocks_unrelated_action_before_native_dispatch(self):
        for patch in ({"action": "focus"}, {"v": "unexpected"}):
            self.assert_code(self.act(**patch), "READ_ONLY_PROFILE")
        self.assert_code(self.call("mss_ui_key", w=0, c="KeyA"), "READ_ONLY_PROFILE")
        self.assertEqual(self.peer.calls, [])

    def test_wrong_path_role_window_or_action_offer_cannot_dispatch(self):
        cases = [
            ("path", PATHS[0] + "_other", "READ_ONLY_PROFILE"),
            ("role", "text", "READ_ONLY_PROFILE"),
            ("actions", "focus", "UNSUPPORTED"),
            ("id", "wrong", "UNKNOWN_NODE"),
        ]
        for key, value, code in cases:
            with self.subTest(key=key):
                previous = self.peer.node[key]
                self.peer.node[key] = value
                self.assert_code(self.act(), code)
                self.peer.node[key] = previous
        self.assert_code(self.act(w="2:1"), "UNKNOWN_NODE")
        self.assertEqual([name for name, _ in self.peer.calls], ["ui__ui"] * 5)

    def test_catalog_policy_is_literal_and_bound_to_exact_app_digest(self):
        policy = {"app_sha256": APP_HASH, "paths": list(PATHS)}
        catalog = Catalog.__new__(Catalog)
        catalog.entries = {"ai-cad": {"allowed_presses": policy}, "todo": {}}
        catalog.validate_allowed_presses("ai-cad", "native", "read-only", policy)
        self.assertEqual(catalog.press_paths("ai-cad", APP_HASH.lower()), PATHS)
        self.assertEqual(catalog.press_paths("ai-cad", "B" * 64), ())
        self.assertEqual(catalog.press_paths("todo", APP_HASH), ())
        for profile, item in (("todo", policy), ("ai-cad", policy | {"paths": ["body.*", PATHS[1]]}),
                              ("ai-cad", policy | {"paths": [PATHS[0], PATHS[0]]})):
            with self.assertRaises(ValueError):
                catalog.validate_allowed_presses(profile, "native", "read-only", item)

    def test_app_local_text_dispatch_keeps_window_activity_and_queue(self):
        self.app.plan.access = "semantic"
        self.attach("control")
        args = {"w": 0, "t": "MSS \u041f\u0440\u0438\u0432\u0435\u0442 \u2713",
                "wait": True, "if_user_seq": 8}
        result = self.call("mss_ui_key", **args, **GEOMETRY)
        self.assertFalse(result.get("isError", False), result)
        outcome = result["structuredContent"]
        self.assertEqual(outcome["code"], "DISPATCHED")
        self.assertEqual(outcome["operation_state"], "APPLIED")
        self.assertEqual(outcome["effect"], "NOT_VERIFIED")
        self.assertEqual(self.peer.calls, [("ui__status", {}), ("ui__activity", {}), ("ui__key", args)])

    def test_text_keeps_existing_ownership_profile_and_single_window_guards(self):
        self.assert_code(self.call("mss_ui_key", w=0, t="text"), "READ_ONLY_PROFILE")
        self.app.plan.access = "semantic"
        self.attach("read")
        self.assert_code(self.call("mss_ui_key", w=0, t="text"), "CONTROL_REQUIRED")
        self.attach("control")
        self.assert_code(self.call("mss_ui_key", w=1, t="text"), "UNKNOWN_WINDOW")
        self.peer.status["w"].append({"i": 1, "sz": [200, 200], "dpi": 1})
        self.assert_code(self.call("mss_ui_key", w=0, t="text"), "UNSUPPORTED")
        self.assertEqual(self.peer.calls, [("ui__status", {})] * 2)

    def test_invalid_text_combinations_and_clipboard_chord_never_dispatch(self):
        self.app.plan.access = "semantic"
        invalid = [{}, {"c": "KeyA", "t": "text"}, {"t": ""}, {"t": "a\x00b"},
                   {"t": "a\nb"}, {"t": "a\x85b"}, {"t": "a\u2028b"}, {"t": "\ud800"}]
        invalid.extend({"t": "text", key: False} for key in ("ctrl", "shift", "alt"))
        invalid.append({"t": "text", "k": "press"})
        for args in invalid:
            with self.subTest(args=args):
                self.assert_code(self.call("mss_ui_key", w=0, **args), "INVALID_ARGUMENT")
        self.assert_code(self.call("mss_ui_key", w=0, c="KeyV", ctrl=True), "SHARED_CLIPBOARD")
        self.assertEqual(self.peer.calls, [])

    def test_pointer_guards_compare_current_geometry_and_stay_inside_router(self):
        self.app.plan.access = "semantic"
        args = {"w": 0, "k": "click", "x": 11, "y": 12}
        invalid_guards = [{"if_dpi": 1}, GEOMETRY | {"if_layout_width": 0},
                          GEOMETRY | {"if_dpi": float("inf")}]
        for guards in invalid_guards:
            self.assert_code(self.call("mss_ui_mouse", **args, **guards), "INVALID_ARGUMENT")
        self.assertEqual(self.peer.calls, [])
        for key in GEOMETRY:
            stale = GEOMETRY | {key: GEOMETRY[key] + 1}
            result = self.call("mss_ui_mouse", **args, **stale)
            self.assert_code(result, "STALE_GEOMETRY")
            self.assertEqual(result["structuredContent"]["operation_state"], "FAILED")
        self.assert_code(self.call("mss_ui_key", w=0, c="Escape", **(GEOMETRY | {"if_dpi": 1})),
                         "STALE_GEOMETRY")
        self.assertEqual(self.peer.calls, [("ui__status", {})] * 4)
        self.assertFalse(self.call("mss_ui_mouse", **args, **GEOMETRY).get("isError", False))
        self.assertEqual(self.peer.calls[-1], ("ui__mouse", args))

    def test_key_refusal_and_unknown_text_result_do_not_retry(self):
        self.app.plan.access = "semantic"
        self.peer.input_error = {"err": "user_intervened", "applied": False}
        self.assert_code(self.call("mss_ui_key", w=0, t="text", if_user_seq=8), "NOT_DISPATCHED")
        self.peer.input_error = {"err": "bad key code KeyUnknown"}
        self.assert_code(self.call("mss_ui_key", w=0, c="KeyUnknown"), "NOT_DISPATCHED")
        self.assert_code(self.call("mss_ui_key", w=0, t="text"), "OUTCOME_UNKNOWN")
        self.assert_code(self.call("mss_ui_key", w=0, t="text"), "OUTCOME_UNKNOWN")
        self.assertEqual([name for name, _ in self.peer.calls],
                         ["ui__status", "ui__activity", "ui__key"] + ["ui__status", "ui__key"] * 2)


if __name__ == "__main__":
    unittest.main()
