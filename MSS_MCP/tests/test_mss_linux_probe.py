"""Integration test for the real Linux stdio entry point (no guest)."""

import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
ROUTER = ROOT / "MSS_MCP/tools/mss_universal.py"


@unittest.skipUnless(sys.platform == "linux", "Linux stdio probe")
class LinuxProbeTests(unittest.TestCase):
    def test_real_stdio_and_fail_closed_tool_surface(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = root / "MSS_MCP/profiles/local.apps.json"
            catalog.parent.mkdir(parents=True)
            catalog.write_text("must not be read as a Windows catalog", encoding="utf-8")
            before = set(root.rglob("*"))
            env = os.environ | {"MSS_DATA_ROOT": tmp}
            with subprocess.Popen(
                [sys.executable, "-I", "-B", str(ROUTER)], cwd=root, env=env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            ) as process, selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                self.addCleanup(self.stop_on_timeout, process)
                next_id = 0

                def send(method, params=None, *, notification=False):
                    nonlocal next_id
                    request = {"jsonrpc": "2.0", "method": method, "params": params or {}}
                    if not notification:
                        next_id += 1
                        request["id"] = next_id
                    process.stdin.write(json.dumps(request).encode() + b"\n")
                    process.stdin.flush()
                    if notification:
                        return
                    self.assertTrue(selector.select(timeout=5), f"No response to {method}")
                    line = process.stdout.readline()
                    self.assertTrue(line, f"EOF in response to {method}")
                    reply = json.loads(line)
                    self.assertEqual(reply["id"], next_id)
                    self.assertNotIn("error", reply)
                    return reply["result"]

                def call(name, **args):
                    return send("tools/call", {"name": name, "arguments": args})

                try:
                    hello = send("initialize", {"protocolVersion": "2025-06-18"})
                    self.assertEqual(hello["serverInfo"]["name"], "mss")
                    self.assertEqual(hello["protocolVersion"], "2025-06-18")
                    send("notifications/initialized", notification=True)
                    tools = send("tools/list")["tools"]
                    self.assertEqual({item["name"] for item in tools}, {"mss_server_info", "mss_list_apps"})
                    info = call("mss_server_info")["structuredContent"]
                    self.assertEqual(info["server_pid"], process.pid)
                    self.assertEqual(info["platform"], "linux")
                    self.assertEqual(info["mode"], "stdio_probe")
                    self.assertIs(info["native_guest_launch"], False)
                    self.assertEqual(info["source_manifest"]["capture_mode"], "frozen_source_bytes_executed")
                    self.assertEqual(call("mss_list_apps")["structuredContent"], {"apps": []})
                    for name, args in [
                        ("mss_launch_app", {"profile": "todo"}),
                        ("mss_list_instances", {}),
                        ("mss_close_app", {"app_id": "app_" + "0" * 32}),
                    ]:
                        with self.subTest(name=name):
                            rejected = call(name, **args)
                            self.assertTrue(rejected["isError"])
                            self.assertEqual(rejected["structuredContent"]["code"], "UNSUPPORTED_PLATFORM")
                finally:
                    process.stdin.close()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                        raise
                self.assertEqual(process.returncode, 0, process.stderr.read().decode())
            self.assertEqual(set(root.rglob("*")), before)
            self.assertEqual(catalog.read_text(encoding="utf-8"), "must not be read as a Windows catalog")

    @staticmethod
    def stop_on_timeout(process):
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
