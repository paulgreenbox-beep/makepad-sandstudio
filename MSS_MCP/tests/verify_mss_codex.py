"""Exercise the registered MSS through two native Codex App Server threads.

This probe uses only App Server client RPCs. It never starts a model turn or
answers a permission prompt. Native UI and process ownership stay with MSS.
"""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
from queue import Empty, Queue
import re
import struct
import subprocess
from threading import Thread
from time import monotonic
import tomllib
from uuid import uuid4


REQUIRED_TOOLS = {
    "mss_list_apps", "mss_launch_app", "mss_find_app", "mss_status",
    "mss_activity", "mss_ui_tree", "mss_ui_find", "mss_ui_act", "mss_ui_type",
    "mss_ui_wait", "mss_grab", "mss_logs", "mss_close_app",
}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_END = b"\x00\x00\x00\x00IEND\xaeB\x60\x82"
MAX_REPLY = 24 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_tool_json(result):
    if isinstance(result.get("structuredContent"), dict):
        return result["structuredContent"]
    text = "\n".join(item["text"] for item in result["content"] if item.get("type") == "text")
    return json.loads(text)


class CodexSession:
    def __init__(self, label, command, workspace, evidence):
        self.label = label
        self.evidence = evidence
        self.workspace = workspace
        self.inbox = Queue()
        self.sequence = 0
        self.thread_id = None
        self.usable = True
        self.owned = set()
        self.process = subprocess.Popen(
            command, cwd=workspace, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.reader = Thread(target=self._read, name=f"codex-rpc-{label}", daemon=True)
        self.reader.start()
        self.trace = evidence / f"codex-{label}.jsonl"
        self.record("process", {"pid": self.process.pid})

    def _read(self):
        try:
            while True:
                raw = self.process.stdout.readline(MAX_REPLY + 1)
                if not raw:
                    raise EOFError("Codex App Server closed stdout")
                require(len(raw) <= MAX_REPLY and raw.endswith(b"\n"), "Invalid Codex reply size")
                self.inbox.put(json.loads(raw))
        except Exception as error:
            self.inbox.put(error)

    def record(self, direction, message):
        with self.trace.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"direction": direction, **message}, ensure_ascii=False) + "\n")

    def send(self, message):
        self.record("request", message)
        self.process.stdin.write(json.dumps(message).encode("utf-8") + b"\n")
        self.process.stdin.flush()

    def rpc(self, method, params):
        require(self.usable, f"Codex connection {self.label} is no longer usable")
        self.sequence += 1
        try:
            self.send({"id": self.sequence, "method": method, "params": params})
            deadline = monotonic() + 75
            while True:
                try:
                    response = self.inbox.get(timeout=max(0, deadline - monotonic()))
                except Empty as error:
                    raise TimeoutError(f"Codex {self.label} timed out at {method}") from error
                if isinstance(response, Exception):
                    raise response
                if "method" in response:
                    if "id" in response:
                        self.record("server_request", {"id": response["id"], "method": response["method"]})
                        raise RuntimeError(f"Codex requested user input: {response['method']}")
                    continue
                require(response.get("id") == self.sequence, "Codex reply ID did not match")
                if "error" in response:
                    error = response["error"]
                    self.record("response", {"id": self.sequence, "code": error.get("code"),
                                             "message": error.get("message", "")})
                    raise RuntimeError(f"Codex rejected {method}: {error.get('message', '')}")
                return response["result"]
        except Exception:
            self.usable = False
            raise

    def start(self):
        initialized = self.rpc("initialize", {
            "clientInfo": {"name": "mss-native-verification", "version": "1"},
            "capabilities": {"experimentalApi": True},
        })
        self.record("response", {"id": self.sequence, "userAgent": initialized.get("userAgent")})
        self.send({"method": "initialized"})
        started = self.rpc("thread/start", {
            "cwd": str(self.workspace), "ephemeral": True, "sandbox": "read-only",
        })
        self.thread_id = started["thread"]["id"]
        self.record("response", {"id": self.sequence, "threadId": self.thread_id})
        inventory = self.rpc("mcpServerStatus/list", {
            "threadId": self.thread_id, "serverName": "mss", "detail": "toolsAndAuthOnly",
        })
        servers = inventory["data"]
        require(len(servers) == 1 and servers[0]["name"] == "mss", "Codex did not discover mss")
        self.record("response", {"id": self.sequence, "result": servers[0]})
        require(REQUIRED_TOOLS <= set(servers[0]["tools"]), "Incomplete MSS tool catalogue in Codex")
        return self.tool_json("mss_list_apps", {})

    def tool(self, name, arguments, *, expect_error=False, png=None):
        result = self.rpc("mcpServer/tool/call", {
            "threadId": self.thread_id, "server": "mss", "tool": name, "arguments": arguments,
        })
        sequence = self.sequence
        content = []
        for item in result.get("content", []):
            if item.get("type") != "image":
                content.append(item)
                continue
            require(png is not None and item.get("mimeType") == "image/png", "Unexpected image result")
            pixels = base64.b64decode(item["data"], validate=True)
            require(pixels.startswith(PNG_SIGNATURE) and pixels.endswith(PNG_END) and pixels[12:16] == b"IHDR",
                    "Malformed native PNG")
            width, height = struct.unpack(">II", pixels[16:24])
            require(width > 0 and height > 0, "Empty native PNG")
            png.write_bytes(pixels)
            content.append({"type": "image", "mimeType": "image/png", "file": png.name,
                            "sha256": hashlib.sha256(pixels).hexdigest(), "width": width, "height": height})
        self.record("response", {"id": sequence, "tool": name, "result": {**result, "content": content}})
        require(bool(result.get("isError")) == expect_error, f"Unexpected outcome from {name}")
        return {**result, "content": content}

    def tool_json(self, name, arguments):
        return read_tool_json(self.tool(name, arguments))

    def launch(self):
        app = self.tool_json("mss_launch_app", {"profile": "todo"})
        self.owned.add(app["app_id"])
        require(app["profile"] == "todo" and app["pid"] > 0 and bool(app["app_birth_utc"]), "Incomplete app identity")
        self.status(app)
        return app

    def status(self, app):
        current = self.tool_json("mss_status", {"app_id": app["app_id"]})
        require(current["pid"] == app["pid"] and bool(current["w"]), "Native status lost the owned app identity")
        return current

    def tree(self, app_id):
        return self.tool_json("mss_ui_tree", {"app_id": app_id, "json": True})

    def close(self, app_id):
        self.owned.discard(app_id)  # An uncertain close must never be replayed.
        result = self.tool_json("mss_close_app", {"app_id": app_id})
        require(result["app_id"] == app_id and result["state"] == "CLOSED", "MSS did not confirm a normal close")
        return result

    def finish(self):
        errors = []
        for app_id in sorted(self.owned):
            if not self.usable:
                break
            try:
                self.close(app_id)
            except Exception as error:
                errors.append(str(error))
        if self.usable and self.thread_id:
            try:
                result = self.rpc("thread/unsubscribe", {"threadId": self.thread_id})
                self.record("response", {"id": self.sequence, "result": result})
            except Exception as error:
                errors.append(str(error))
        try:
            self.process.stdin.close()
        except BrokenPipeError:
            pass
        try:
            code = self.process.wait(timeout=50)
            self.record("process_exit", {"pid": self.process.pid, "exit_code": code})
            require(code == 0, f"Codex {self.label} exited with code {code}")
        except Exception as error:
            errors.append(str(error))
        return errors


def todo_node(tree, suffix):
    nodes = tree["trees"][0]["nodes"]
    matches = [node for node in nodes if node.get("path", "").split(".")[-1] == suffix]
    require(len(matches) == 1, f"Expected one native Todo node: {suffix}")
    return matches[0]


def todo_state(tree):
    texts = [node.get("name", "") for node in tree["trees"][0]["nodes"] if node.get("role") == "static_text"]
    return {"input": todo_node(tree, "todo_input").get("value", ""),
            "status": todo_node(tree, "status")["name"], "texts": texts}


def act(session, app_id, tree, node, action, **extra):
    activity = session.tool_json("mss_activity", {"app_id": app_id})
    session.tool("mss_ui_act", {
        "app_id": app_id, "node": node["id"], "w": tree["trees"][0]["window"],
        "action": action, "wait": True, "if_user_seq": activity["user_seq"], **extra,
    })


def verify_apps(a, b, evidence, report):
    catalog_a, catalog_b = a.start(), b.start()
    require(catalog_a == catalog_b and a.thread_id != b.thread_id, "Codex threads lack equal catalogues or distinct IDs")
    report["threads"] = {a.label: a.thread_id, b.label: b.thread_id}
    report["codex_pids"] = {a.label: a.process.pid, b.label: b.process.pid}
    owners = {"A1": a, "A2": a, "B1": b}
    apps = {key: owner.launch() for key, owner in owners.items()}
    report["apps"] = apps
    require(len({app["pid"] for app in apps.values()}) == len(apps), "Duplicate owned PIDs")
    require(len({app["app_id"] for app in apps.values()}) == len(apps), "Duplicate app IDs")
    for owner, labels in ((a, ("A1", "A2")), (b, ("B1",))):
        found = owner.tool_json("mss_find_app", {})["apps"]
        require({app["app_id"] for app in found} == {apps[key]["app_id"] for key in labels}, "Cross-chat app catalogue leak")
    a.tool("mss_ui_tree", {"app_id": apps["B1"]["app_id"], "json": True}, expect_error=True)
    b.tool("mss_ui_tree", {"app_id": apps["A1"]["app_id"], "json": True}, expect_error=True)

    def snapshot(key, name):
        tree = owners[key].tree(apps[key]["app_id"])
        write_json(evidence / f"{key}-{name}.json", tree)
        return tree

    expected = {key: todo_state(snapshot(key, "before")) for key in apps}
    captures = {}
    for key, owner in owners.items():
        app_id = apps[key]["app_id"]
        tree = owner.tree(app_id)
        marker = f"MSS {key} Привет ✓ {evidence.name[-8:]}"
        act(owner, app_id, tree, todo_node(tree, "todo_input"), "set_value", v=marker)
        typed = owner.tree(app_id)
        require(todo_state(typed)["input"] == marker, "Native Todo input failed exact readback")
        act(owner, app_id, typed, todo_node(typed, "add_button"), "press")
        expected[key] = todo_state(snapshot(key, "after"))
        require(expected[key]["input"] == "" and expected[key]["texts"].count(marker) == 1,
                "Native Todo Add postcondition failed")
        for other in apps.keys() - {key}:
            require(todo_state(owners[other].tree(apps[other]["app_id"])) == expected[other],
                    f"{key} mutation changed the independent {other} state")
        png = evidence / f"{key}.png"
        image = owner.tool("mss_grab", {"app_id": app_id}, png=png)
        require(sum(item.get("type") == "image" for item in image["content"]) == 1 and png.is_file(), "No native PNG returned")
        capture = read_tool_json(image)
        image_receipt = next(item for item in image["content"] if item["type"] == "image")
        require(capture.get("capture_kind") == "pixels"
                and capture.get("sz") == [image_receipt["width"], image_receipt["height"]],
                "Native GPU frame receipt does not match the returned PNG")
        captures[key] = image_receipt
        logs = owner.tool_json("mss_logs", {"app_id": app_id, "n": 500})
        require(isinstance(logs.get("l"), list) and not re.search(
            r"\[E\]|script\s*error|panicked at", json.dumps(logs["l"]), re.IGNORECASE),
            "Native app log reported a runtime error")
    report["todo_states"] = expected
    report["captures"] = captures
    require(len({item["sha256"] for item in captures.values()}) == len(captures), "Different Todo states produced identical PNGs")

    report["closed"] = {"A1": a.close(apps["A1"]["app_id"])}
    for key in ("A2", "B1"):
        owners[key].status(apps[key])
        require(todo_state(snapshot(key, "after-A1-close")) == expected[key], "Peer state changed after closing A1")
        report["closed"][key] = owners[key].close(apps[key]["app_id"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args()
    workspace = args.workspace.resolve(strict=True)
    codex = args.codex.resolve(strict=True)
    config_file = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "config.toml"
    servers = tomllib.loads(config_file.read_text(encoding="utf-8-sig"))["mcp_servers"]
    require(servers.get("mss", {}).get("enabled", True) and "mss" in servers, "No enabled global mss registration")
    unrelated = [name for name, spec in servers.items() if name != "mss" and spec.get("enabled", True)]
    require(all(re.fullmatch(r"[A-Za-z0-9_-]+", name) for name in unrelated), "Unexpected unrelated MCP key syntax")
    command = [str(codex), "app-server", "--listen", "stdio://", "--disable", "plugins", "--disable", "apps"]
    for name in unrelated:
        command.extend(["-c", f"mcp_servers.{name}.enabled=false"])
    evidence = args.evidence_root.resolve() / ("codex-mss-" + uuid4().hex)
    evidence.mkdir(parents=True)
    report = {"status": "FAIL", "model_invoked": False, "global_mss_overridden": False,
              "codex_executable": str(codex), "workspace": str(workspace), "cleanup_errors": []}
    sessions = []
    try:
        for label in ("A", "B"):
            sessions.append(CodexSession(label, command, workspace, evidence))
        verify_apps(*sessions, evidence, report)
        report["status"] = "PASS"
    except Exception as error:
        report["error"] = str(error)
    finally:
        for session in reversed(sessions):
            report["cleanup_errors"].extend(session.finish())
        if report["cleanup_errors"]:
            report["status"] = "FAIL"
        write_json(evidence / "results.json", report)
    print(json.dumps({"status": report["status"], "evidence": str(evidence), "error": report.get("error")}, ensure_ascii=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
