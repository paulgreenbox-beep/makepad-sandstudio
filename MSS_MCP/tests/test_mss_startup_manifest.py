"""Real stdio startup identity regressions; copied MSS only, no applications/model."""

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from queue import Empty, Queue
import shutil
import subprocess
import sys
import tempfile
from threading import Thread
import unittest


MAX_REPLY = 512 * 1024
REQUIRED_MODULES = {
    "mss_universal.py", "mss_profiles.py", "mss_builds.py", "mss_process.py", "mss_shared.py",
}


def _tool_source():
    configured = os.environ.get("MSS_TEST_TOOLS")
    if configured:
        return Path(configured).resolve(strict=True)
    return (Path(__file__).resolve().parents[1] / "tools").resolve(strict=True)


class StdioFixture:
    """Own exactly one copied stdio server and retain its Popen process handle."""

    def __init__(self, repo, label):
        self.repo = repo
        self.sequence = 0
        self.inbox = Queue(maxsize=16)
        self.log = (repo / f"{label}-stderr.log").open("xb")
        self.process = subprocess.Popen(
            [sys.executable, "-I", "-B", str(repo / "MSS_MCP/tools/mss_universal.py")],
            cwd=repo, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.reader = Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            while True:
                line = self.process.stdout.readline(MAX_REPLY + 1)
                if not line:
                    raise EOFError("Copied MCP stdout closed")
                if len(line) > MAX_REPLY or not line.endswith(b"\n"):
                    raise ValueError("Copied MCP reply exceeds its boundary")
                self.inbox.put(json.loads(line))
        except BaseException as error:
            self.inbox.put(error)

    def rpc(self, method, params):
        self.sequence += 1
        self.process.stdin.write(json.dumps({
            "jsonrpc": "2.0", "id": self.sequence, "method": method, "params": params,
        }).encode("utf-8") + b"\n")
        self.process.stdin.flush()
        try:
            response = self.inbox.get(timeout=12)
        except Empty as error:
            raise AssertionError("Copied MSS did not answer within 12 seconds") from error
        if isinstance(response, BaseException):
            raise response
        if response.get("id") != self.sequence or "error" in response:
            raise AssertionError(response)
        return response["result"]

    def start(self, protocol_version="2025-06-18"):
        self.initialize_result = self.rpc(
            "initialize", {"protocolVersion": protocol_version, "capabilities": {}})
        return self

    def tool(self, name):
        result = self.rpc("tools/call", {"name": name, "arguments": {}})
        if result.get("isError"):
            raise AssertionError(result)
        return result.get("structuredContent") or json.loads("\n".join(
            item["text"] for item in result["content"] if item.get("type") == "text"
        ))

    def close(self):
        try:
            self.process.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            code = self.process.wait(timeout=12)
        except subprocess.TimeoutExpired:
            # Retained handle of this test's own copied MCP only. No app was launched.
            self.process.kill()
            self.process.wait(timeout=5)
            raise AssertionError("Copied MSS failed to close after EOF")
        finally:
            self.reader.join(timeout=1)
            if not self.reader.is_alive():
                self.process.stdout.close()
            self.log.close()
        if code != 0:
            raise AssertionError(f"Copied MSS exited with code {code}")


@unittest.skipUnless(sys.platform == "win32", "Native Windows MSS stdio contract")
class StartupManifestTests(unittest.TestCase):
    def setUp(self):
        self.fixture = tempfile.TemporaryDirectory(prefix="mss-startup-manifest-")
        self.addCleanup(self.fixture.cleanup)
        self.repo = Path(self.fixture.name)
        self.tools = self.repo / "MSS_MCP/tools"
        self.tools.mkdir(parents=True)
        profiles = self.repo / "MSS_MCP/profiles"
        profiles.mkdir()
        source = _tool_source()
        for path in source.glob("mss_*.py"):
            shutil.copyfile(path, self.tools / path.name)
        shutil.copyfile(source / "Start-MakepadMcp.ps1", self.tools / "Start-MakepadMcp.ps1")
        (profiles / "local.apps.json").write_text(
            '{"schema_version":1,"launcher_sha256":"","pwsh_sha256":"","profiles":[]}',
            encoding="utf-8", newline="\n",
        )
        (self.repo / "Cargo.toml").write_text(
            '[workspace.package]\nversion = "0.1.0-test"\n', encoding="utf-8", newline="\n",
        )
        self.start_hashes = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in self.tools.glob("mss_*.py")
        }

    def server(self, label="server"):
        server = StdioFixture(self.repo, label)
        self.addCleanup(server.close)
        return server.start()

    def manifest(self, server):
        info = server.tool("mss_server_info")
        self.assertEqual(info["server_pid"], server.process.pid)
        self.assertRegex(info["connection_id"], r"^[a-f0-9]{32}$")
        datetime.fromisoformat(info["server_started_utc"].replace("Z", "+00:00"))
        self.assertIn("mss_version", info)
        self.assertIn("mss_commit", info)
        self.assertEqual(info["mcp_protocol_version"], server.initialize_result["protocolVersion"])
        snapshot = info["source_manifest"]
        self.assertIn("frozen", snapshot["capture_mode"].lower())
        datetime.fromisoformat(snapshot["captured_at_utc"].replace("Z", "+00:00"))
        self.assertRegex(snapshot["aggregate_sha256"], r"^[a-f0-9]{64}$")
        self.assertTrue(REQUIRED_MODULES <= snapshot["modules"].keys())
        self.assertTrue(self.start_hashes.keys() <= snapshot["modules"].keys(),
                        "A local MSS helper would otherwise be loaded from mutable disk")
        for name, saved in snapshot["modules"].items():
            self.assertEqual(saved["sha256"], self.start_hashes[name], name)
        self.assertTrue(snapshot["limitations"])
        return info

    def test_protocol_identity_matches_actual_handshake_including_fallback(self):
        for index, version in enumerate(("2025-06-18", "unsupported-test-version")):
            with self.subTest(requested=version):
                server = StdioFixture(self.repo, f"protocol-{index}")
                self.addCleanup(server.close)
                server.start(version)
                info = self.manifest(server)
                self.assertEqual(info["mcp_server_version"], server.initialize_result["serverInfo"]["version"])
                self.assertIn(info["mcp_protocol_version"], info["mcp_supported_protocol_versions"])

    def test_manifest_identifies_running_process_and_frozen_sources_without_side_effects(self):
        server = self.server()
        info = self.manifest(server)
        forbidden = {"remote_token", "token", "secret", "document", "fragment", "environment"}
        def keys(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    yield key.lower()
                    yield from keys(child)
            elif isinstance(value, list):
                for child in value:
                    yield from keys(child)
        self.assertFalse(forbidden & set(keys(info)))
        self.assertFalse((self.repo / "proof").exists())
        self.assertFalse((self.repo / "MSS_MCP/profiles/local.shared").exists())

    def test_disk_edits_after_start_never_replace_manifest_of_running_code(self):
        server = self.server()
        before = self.manifest(server)
        for name in before["source_manifest"]["modules"]:
            (self.tools / name).write_bytes(b"raise RuntimeError('MSS_CHANGED_AFTER_START')\n")
        self.assertEqual(server.tool("mss_server_info"), before)
        self.assertEqual(server.tool("mss_list_apps"), {"apps": []})
        for name, saved in before["source_manifest"]["modules"].items():
            self.assertNotEqual(hashlib.sha256((self.tools / name).read_bytes()).hexdigest(), saved["sha256"])
        # This is a new OWN copied process, not a restart of an active connection.
        new = subprocess.run(
            [sys.executable, "-I", "-B", str(self.tools / "mss_universal.py")],
            cwd=self.repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.assertNotEqual(new.returncode, 0)
        self.assertIn(b"MSS_CHANGED_AFTER_START", new.stderr)

    def test_independent_connections_have_distinct_process_and_connection_identity(self):
        first, second = self.server("first"), self.server("second")
        one, two = self.manifest(first), self.manifest(second)
        self.assertNotEqual(one["server_pid"], two["server_pid"])
        self.assertNotEqual(one["connection_id"], two["connection_id"])
        self.assertEqual(one["source_manifest"]["modules"], two["source_manifest"]["modules"])
        self.assertEqual(one["source_manifest"]["aggregate_sha256"], two["source_manifest"]["aggregate_sha256"])


if __name__ == "__main__":
    unittest.main()
