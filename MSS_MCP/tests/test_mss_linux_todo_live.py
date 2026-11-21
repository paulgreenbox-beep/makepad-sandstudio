"""Opt-in live acceptance for the MSS MCP router and a pinned Linux Todo guest."""

import hashlib
import json
import os
from pathlib import Path
import select
import struct
import subprocess
import sys
import tempfile
from time import monotonic, sleep
import unittest
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
ROUTER = ROOT / "MSS_MCP/tools/mss_universal.py"
REQUIRED = (
    "MSS_LINUX_TODO_EXE", "MSS_LINUX_TODO_SHA256",
    "MSS_LINUX_REMOTE_EXE", "MSS_LINUX_REMOTE_SHA256",
)
MAX_REPLY = 24 * 1024 * 1024
READ_TIMEOUT = 8


def process_start_ticks(pid):
    try:
        # The command field is enclosed in parentheses and may contain spaces.
        return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19])
    except FileNotFoundError:
        return None


class Mcp:
    """Drive the production stdio entry point, not the router's internals."""

    def __init__(self, process):
        self.process = process
        self.request_id = 0
        self.pending = bytearray()

    def send(self, method, params=None, *, timeout=READ_TIMEOUT, notification=False):
        request = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notification:
            self.request_id += 1
            request["id"] = self.request_id
        self.process.stdin.write(json.dumps(request).encode("utf-8") + b"\n")
        self.process.stdin.flush()
        if notification:
            return None

        deadline = monotonic() + timeout
        while b"\n" not in self.pending:
            remaining = deadline - monotonic()
            if remaining <= 0 or not select.select([self.process.stdout], [], [], remaining)[0]:
                raise AssertionError(f"No reply from MSS for {method}")
            chunk = os.read(self.process.stdout.fileno(), 64 * 1024)
            if not chunk:
                raise AssertionError(f"MSS closed stdout during {method}")
            self.pending.extend(chunk)
            if len(self.pending) > MAX_REPLY:
                raise AssertionError("MSS reply exceeded the acceptance-test size limit")
        line, _, self.pending = self.pending.partition(b"\n")
        response = json.loads(line)
        if response.get("id") != self.request_id or "error" in response:
            raise AssertionError(f"Unsuccessful JSON-RPC reply for {method}: {response.get('error')}")
        return response["result"]

    def call(self, name, *, timeout=READ_TIMEOUT, **arguments):
        result = self.send("tools/call", {"name": name, "arguments": arguments}, timeout=timeout)
        if result.get("isError"):
            detail = result.get("structuredContent", {})
            raise AssertionError(f"{name} refused: {detail.get('code', 'unknown error')}")
        if "structuredContent" in result:
            return result["structuredContent"]
        texts = [part["text"] for part in result.get("content", []) if part.get("type") == "text"]
        return json.loads(texts[0]) if texts else {}


def matching_nodes(reply, window=None):
    return [(tree["window"], node) for tree in reply["trees"]
            if window is None or tree["window"] == window for node in tree["nodes"]]


def wait_until(read, accept, description, seconds=7):
    deadline = monotonic() + seconds
    while True:
        observation = read()
        if accept(observation):
            return observation
        if monotonic() >= deadline:
            raise AssertionError(f"Did not observe {description}")
        sleep(0.06)


@unittest.skipUnless(sys.platform == "linux", "Linux Todo live acceptance")
class LinuxTodoLiveTests(unittest.TestCase):
    def test_add_todo_and_verify_pixels_and_owned_exit(self):
        missing = [name for name in REQUIRED if not os.environ.get(name)]
        if missing:
            self.skipTest("Pinned Linux binaries not configured: " + ", ".join(missing))
        with tempfile.TemporaryDirectory(prefix="mss-todo-acceptance-") as scratch:
            process = subprocess.Popen(
                [sys.executable, "-I", "-B", str(ROUTER)], cwd=scratch,
                env=os.environ | {"MSS_DATA_ROOT": scratch},
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            )
            endpoint = Mcp(process)
            try:
                self.check_todo(endpoint)
            finally:
                # EOF is the production router's owner-shutdown path on failure.
                # Do not retry an action if dispatch or its result was uncertain.
                process.stdin.close()
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                    self.fail("MSS timed out in owner shutdown; guest cleanup is unverified")
                finally:
                    process.stdout.close()
                self.assertEqual(process.returncode, 0, "MSS shutdown did not report success")

    def check_todo(self, endpoint):
        hello = endpoint.send("initialize", {"protocolVersion": "2025-06-18"})
        self.assertEqual(hello["serverInfo"]["name"], "mss")
        self.assertEqual(hello["protocolVersion"], "2025-06-18")
        endpoint.send("notifications/initialized", notification=True)
        expected_tools = {
            "mss_list_apps", "mss_launch_app", "mss_status", "mss_ui_find",
            "mss_ui_type", "mss_ui_act", "mss_grab", "mss_close_app",
        }
        self.assertLessEqual(expected_tools, {tool["name"] for tool in endpoint.send("tools/list")["tools"]})
        self.assertIn("todo", {entry["profile"] for entry in endpoint.call("mss_list_apps")["apps"]})

        started = endpoint.call("mss_launch_app", profile="todo", timeout=35)
        self.assertEqual(started["state"], "READY")
        app_id, pid = started["app_id"], started["pid"]
        self.assertRegex(app_id, r"^app_[a-f0-9]{32}$")
        self.assertIs(type(pid), int)
        self.assertGreater(pid, 1)
        birth = process_start_ticks(pid)
        self.assertIsNotNone(birth, "Owned Todo process was not live after launch")

        status = endpoint.call("mss_status", app_id=app_id)
        self.assertEqual(status["pid"], pid)
        self.assertEqual(len(status["w"]), 1)
        window_index = status["w"][0]["i"]
        self.assertIs(type(window_index), int)

        def find(q, window=None):
            args = {"q": q, "json": True}
            if window is not None:
                args["w"] = window
            return matching_nodes(endpoint.call("mss_ui_find", app_id=app_id, **args), window)

        [(window, field)] = wait_until(
            lambda: find('path="todo_input"'), lambda rows: len(rows) == 1, "the input field"
        )
        self.assertRegex(window, r"^[0-9]+:[0-9]+$")
        self.assertEqual(int(window.rsplit(":", 1)[1]), window_index)
        self.assertEqual(field["value"], "")
        item = f"MSS Linux acceptance {uuid4().hex[:12]}"
        item_query = "name=" + json.dumps(item)
        self.assertEqual(find(item_query, window), [])

        endpoint.call("mss_ui_type", app_id=app_id, node=field["id"], w=window, t=item,
                      **{"from": 0, "to": 0})
        wait_until(lambda: find('path="todo_input"', window),
                   lambda rows: len(rows) == 1 and rows[0][1].get("value") == item,
                   "the exact text in the input field")

        [(button_window, button)] = find('path="add_button"', window)
        self.assertEqual(button_window, window)
        endpoint.call("mss_ui_act", app_id=app_id, node=button["id"], w=window,
                      action="press", wait=True)
        [(item_window, label)] = wait_until(
            lambda: find(item_query, window),
            lambda rows: len(rows) == 1 and rows[0][1].get("name") == item,
            "exactly one task with the test label",
        )
        self.assertEqual(item_window, window)
        states = set(label["states"].split(","))
        self.assertTrue(states.isdisjoint({"hidden", "offscreen"}))
        self.assertGreater(label["bounds"][2], 0)
        self.assertGreater(label["bounds"][3], 0)
        wait_until(lambda: find('path="todo_input"', window),
                   lambda rows: len(rows) == 1 and rows[0][1].get("value") == "",
                   "the cleared input after Add")

        capture = endpoint.call("mss_grab", app_id=app_id, w=window_index, scale=1)
        self.assertEqual(capture["capture_kind"], "pixels")
        self.assertEqual(capture["w"], window_index)
        with Path(capture["png"]).open("rb") as png:
            image = png.read(MAX_REPLY + 1)
        self.assertLessEqual(len(image), MAX_REPLY)
        self.assertGreater(len(image), 33)
        self.assertEqual(image[:16], b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
        width, height = struct.unpack(">II", image[16:24])
        self.assertGreater(width * height, 0)
        self.assertEqual([width, height], capture["sz"])
        self.assertEqual(hashlib.sha256(image).hexdigest(), capture["sha256"])
        self.assertEqual(endpoint.call("mss_status", app_id=app_id)["pid"], pid)
        self.assertEqual(process_start_ticks(pid), birth)

        closed = endpoint.call("mss_close_app", app_id=app_id, timeout=20)
        self.assertEqual(closed["app_id"], app_id)
        self.assertEqual(closed["pid"], pid)
        self.assertEqual(closed["state"], "CLOSED")
        self.assertEqual(closed["exit_code"], 0)
        self.assertNotEqual(process_start_ticks(pid), birth, "The owned Todo process is still present")
        # Copy byte-for-byte only after every check, to an operator-selected new file.
        if destination := os.environ.get("MSS_LINUX_TODO_SCREENSHOT"):
            path = Path(destination)
            self.assertTrue(path.is_absolute(), "MSS_LINUX_TODO_SCREENSHOT must be absolute")
            with path.open("xb") as output:
                output.write(image)
