"""Synthetic Linux Todo policy integration over MSS stdio; no Makepad process."""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_mss_linux_todo_live import Mcp, ROOT


TOOLS = ("ui__status", "ui__ui", "ui__ui_find", "ui__ui_act", "ui__grab", "ui__quit")
WINDOW = "71:0"
NODES = {
    "input": {"id": "input", "path": "body.todo_input", "actions": "replace_text"},
    "add": {"id": "add", "path": "body.add_button", "actions": "press"},
    "other": {"id": "other", "path": "delete_button", "actions": "press"},
}


class FakeApp:
    def __init__(self, directory):
        self.pid = os.getpid()  # synthetic identity; never signal this as a guest
        self.directory = directory
        self.directory.mkdir()
        self.closed = False

    @classmethod
    def launch(cls, guest, *, cwd):
        return cls(cwd / "fake-owned-session")

    def verify(self):
        if self.closed:
            raise AssertionError("Router addressed a closed synthetic app")

    def start_remote(self, remote):
        return self

    def close(self):
        self.verify()
        self.closed = True
        self.directory.rmdir()
        return {"exit_code": 0}


class FakePeer:
    def __init__(self, app):
        self.app = app
        self.value = ""
        self.items = []
        self.press_count = 0

    @classmethod
    def from_process(cls, app):
        return cls(app)

    def request(self, method, params, timeout=None):
        if method == "initialize":
            return {"protocolVersion": "2025-06-18"}
        if method == "tools/list":
            return {"tools": [{"name": name} for name in TOOLS]}
        if method == "tools/call" and params["name"] == "ui__quit":
            return {"result": {}}
        raise AssertionError(f"Unexpected native request: {method}")

    def send(self, notification):
        assert notification["method"] == "notifications/initialized"

    def call(self, name, args):
        self.app.verify()
        match name:
            case "ui__status":
                return MSS.result_json({"pid": self.app.pid, "w": [{"i": 0}]})
            case "ui__ui":
                node = NODES[args["node"]]
                return MSS.result_json({"trees": [{"window": WINDOW, "nodes": [node]}]})
            case "ui__ui_find":
                return MSS.result_json({"items": self.items, "value": self.value,
                                        "native_add_dispatches": self.press_count})
            case "ui__ui_act":
                assert args["w"] == WINDOW and args["wait"] is True
                if args["action"] == "replace_text":
                    assert args["node"] == "input"
                    self.value = args["t"]
                else:
                    assert args["action"] == "press" and args["node"] == "add"
                    self.press_count += 1
                    self.items.append(self.value)
                    self.value = ""
                    if self.press_count == 2:
                        raise MSS.TransportFailure("Synthetic loss after the second Add was applied")
                return MSS.result_json({"code": "SYNTHETIC_DISPATCH"})
        raise AssertionError(f"Unexpected native call: {name}")


def serve_fake():
    # Keep production admission, JSON-RPC, routing and configuration. Only the
    # process/Remote boundary is synthetic. This is not frozen-source evidence.
    global MSS
    sys.path.insert(0, str(ROOT / "MSS_MCP/tools"))
    import mss_universal as MSS
    with patch.object(MSS, "OwnedLinuxApp", FakeApp), patch.object(MSS, "Peer", FakePeer):
        return MSS.main()


@unittest.skipUnless(sys.platform == "linux", "Linux synthetic Todo policy integration")
class LinuxTodoRouterTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory(prefix="mss-linux-router-")
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        guest, remote = self.root / "makepad-example-todo", self.root / "makepad-remote"
        source = Path(shutil.which("true") or sys.executable).resolve(strict=True)
        for target in (guest, remote):
            shutil.copyfile(source, target)
            target.chmod(0o700)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        self.env = os.environ | {
            "MSS_LINUX_TODO_EXE": str(guest), "MSS_LINUX_TODO_SHA256": digest,
            "MSS_LINUX_REMOTE_EXE": str(remote), "MSS_LINUX_REMOTE_SHA256": digest,
            "MSS_LINUX_TODO_CWD": str(self.root),
        }

    def open(self, env=None):
        process = subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()), "--serve-fake"],
                                   env=self.env if env is None else env, cwd=self.root,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self.addCleanup(self.stop, process)
        endpoint = Mcp(process)
        hello = endpoint.send("initialize", {"protocolVersion": "2025-06-18"})
        self.assertEqual(hello["serverInfo"]["name"], "mss")
        endpoint.send("notifications/initialized", notification=True)
        return endpoint

    def stop(self, process):
        process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            self.fail("Synthetic MSS stdio did not close")
        finally:
            process.stdout.close()
        self.assertEqual(process.returncode, 0)

    def expect_refusal(self, endpoint, name, code, **arguments):
        result = endpoint.send("tools/call", {"name": name, "arguments": arguments})
        self.assertIs(result["isError"], True)
        self.assertEqual(result["structuredContent"]["code"], code)

    def test_incomplete_pins_do_not_configure_todo(self):
        env = self.env.copy()
        del env["MSS_LINUX_REMOTE_SHA256"]
        endpoint = self.open(env)
        names = {tool["name"] for tool in endpoint.send("tools/list")["tools"]}
        self.assertNotIn("mss_launch_app", names)
        self.assertEqual(endpoint.call("mss_list_apps"), {"apps": []})
        self.expect_refusal(endpoint, "mss_launch_app", "UNSUPPORTED_PLATFORM", profile="todo")

    def test_owned_app_admission_actions_quarantine_and_close(self):
        endpoint = self.open()
        names = {tool["name"] for tool in endpoint.send("tools/list")["tools"]}
        self.assertIn("mss_launch_app", names)
        self.assertNotIn("mss_ui_key", names)
        self.assertEqual([row["profile"] for row in endpoint.call("mss_list_apps")["apps"]], ["todo"])

        response = endpoint.call("mss_launch_app", profile="todo")
        app_id = response["app_id"]
        self.assertRegex(app_id, r"^app_[a-f0-9]{32}$")
        self.assertEqual(response["state"], "READY")
        self.assertTrue((self.root / "fake-owned-session").is_dir())
        self.assertEqual(endpoint.call("mss_status", app_id=app_id)["pid"], response["pid"])
        self.expect_refusal(endpoint, "mss_launch_app", "APP_LIMIT", profile="todo")
        self.expect_refusal(endpoint, "mss_status", "UNKNOWN_APP", app_id="app_" + "0" * 32)
        other_connection = self.open()
        self.expect_refusal(other_connection, "mss_status", "UNKNOWN_APP", app_id=app_id)
        self.expect_refusal(other_connection, "mss_close_app", "UNKNOWN_APP", app_id=app_id)
        self.expect_refusal(endpoint, "mss_ui_key", "UNSUPPORTED_PLATFORM", app_id=app_id, w=0, t="forbidden")
        self.expect_refusal(endpoint, "mss_ui_act", "UNSUPPORTED", app_id=app_id, w=WINDOW,
                            node="other", action="press")
        self.expect_refusal(endpoint, "mss_ui_act", "UNSUPPORTED", app_id=app_id, w="72:0",
                            node="add", action="press")

        def type_text(value):
            endpoint.call("mss_ui_type", app_id=app_id, node="input", w=WINDOW, t=value,
                          **{"from": 0, "to": 0})

        def read():
            return endpoint.call("mss_ui_find", app_id=app_id, w=WINDOW, q='path="todo_input"')

        add = {"app_id": app_id, "node": "add", "w": WINDOW, "action": "press"}
        type_text("first")
        self.assertEqual(read()["value"], "first")
        self.assertEqual(endpoint.call("mss_ui_act", **add)["effect"], "NOT_VERIFIED")
        self.assertEqual(read(), {"items": ["first"], "value": "", "native_add_dispatches": 1})
        type_text("second")
        self.expect_refusal(endpoint, "mss_ui_act", "OUTCOME_UNKNOWN", **add)
        self.expect_refusal(endpoint, "mss_ui_act", "OUTCOME_UNKNOWN", **add)
        self.assertEqual(read(), {"items": ["first", "second"], "value": "", "native_add_dispatches": 2})
        result = endpoint.call("mss_close_app", app_id=app_id)
        self.assertEqual(result, {"app_id": app_id, "pid": response["pid"], "state": "CLOSED", "exit_code": 0})
        self.assertFalse((self.root / "fake-owned-session").exists())
        self.expect_refusal(endpoint, "mss_status", "UNKNOWN_APP", app_id=app_id)


if __name__ == "__main__" and sys.argv[1:] == ["--serve-fake"]:
    sys.argv.pop()  # production stdio entry point accepts no arguments
    raise SystemExit(serve_fake())
