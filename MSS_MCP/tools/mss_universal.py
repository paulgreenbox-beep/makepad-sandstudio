"""Per-connection stdio router for admitted Makepad Remote development apps."""

import base64
from contextlib import ExitStack
import hashlib
import json
import math
from pathlib import Path
from queue import Empty, Queue
import re
import struct
import subprocess
import sys
from threading import Thread
from time import monotonic
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mss_profiles import Catalog, local_path


VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_REQUEST = 256 * 1024
MAX_REPLY = 24 * 1024 * 1024
MAX_APPS = 8
QUERY = {
    key: "string" for key in ("q", "node", "w", "role", "name", "text", "value", "state", "path", "class")
}
QUERY.update({"nth": "integer", "depth": "integer", "json": "boolean"})
TARGET = {"node": "string", "w": "string", "if_user_seq": "integer", "json": "boolean"}
SEMANTIC_ACTIONS = {
    "press", "focus", "set_value", "replace_text", "set_text_selection", "toggle",
    "select", "expand", "collapse", "increment", "decrement", "scroll", "show_menu",
    "dismiss", "custom",
}


def tool(name, description, properties, required=(), *, read=True, destructive=False):
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": {key: {"type": kind} for key, kind in properties.items()},
            "required": list(required),
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": read,
            "destructiveHint": destructive,
            "idempotentHint": read,
            "openWorldHint": False,
        },
    }


ROUTES = {
    "mss_status": ("ui__status", "Read the owned process and window status.", {"w": "integer"}, (), True),
    "mss_activity": ("ui__activity", "Read the owned app's activity sequence.", {}, (), True),
    "mss_settled": ("ui__settled", "Read Makepad presentation readiness.", {}, (), True),
    "mss_ui_tree": ("ui__ui", "Read the semantic tree. JSON is the default.", QUERY, (), True),
    "mss_ui_find": ("ui__ui_find", "Find nodes by Makepad query q or semantic filters.", QUERY, (), True),
    "mss_ui_act": (
        "ui__ui_act", "Request an advertised action on a node in its owning window. Verify the result by readback.",
        TARGET | {"action": "string", "v": "string", "t": "string", "from": "integer",
                  "to": "integer", "dx": "number", "dy": "number", "name": "string", "wait": "boolean"},
        ("node", "w", "action"), False,
    ),
    "mss_ui_type": (
        "ui__ui_act", "Replace text on a node that advertises semantic text replacement.",
        TARGET | {"t": "string", "from": "integer", "to": "integer"},
        ("node", "w", "t"), False,
    ),
    "mss_ui_wait": (
        "ui__ui_wait", "Wait for a Makepad query condition, up to 15000 ms.",
        QUERY | {"gone": "boolean", "changed": "boolean", "count": "integer", "timeout_ms": "integer"},
        ("q",), True,
    ),
    "mss_ui_snap": (
        "ui__ui_snap", "Save a named semantic snapshot in this app.",
        {"name": "string", "w": "string", "json": "boolean"}, ("name",), True,
    ),
    "mss_ui_diff": (
        "ui__ui_diff", "Read semantic changes between this app's named snapshots.",
        {"a": "string", "b": "string", "w": "string", "json": "boolean"}, ("a",), True,
    ),
    "mss_grab": ("ui__grab", "Capture native pixels as PNG in this session's artifacts.",
                 {"w": "integer", "scale": "number"}, (), True),
    "mss_logs": ("logs__log", "Read this app's runtime log.", {"n": "integer", "since": "integer"}, (), True),
}

TOOLS = [
    tool("mss_list_apps", "List the operator-admitted application profiles.", {}),
    tool("mss_launch_app", "Launch an independent owned instance of a profile.", {"profile": "string"},
         ("profile",), read=False),
    tool("mss_find_app", "Find instances owned by this MCP connection and read their state.",
         {"profile": "string", "app_id": "string"}),
    tool("mss_close_app", "Close an owned app through the launcher and check its exit receipt.",
         {"app_id": "string"}, ("app_id",), read=False, destructive=True),
]
TOOLS.extend(
    tool(name, description, {"app_id": "string"} | fields, ("app_id", *required), read=read)
    for name, (_, description, fields, required, read) in ROUTES.items()
)
SCHEMAS = {item["name"]: item["inputSchema"] for item in TOOLS}


class ToolFailure(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class TransportFailure(Exception):
    pass


def require(condition, code, message):
    if not condition:
        raise ToolFailure(code, message)


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"


def write_record(path, value):
    path.write_bytes(json_bytes(value))


def result_json(value, *, error=False):
    return {"content": [{"type": "text", "text": json_bytes(value).decode("utf-8").rstrip()}],
            "structuredContent": value, "isError": error}


def native_json(result):
    require(not result.get("isError"), "REMOTE_ERROR", "Makepad returned an error.")
    try:
        return json.loads("\n".join(part["text"] for part in result["content"] if part["type"] == "text"))
    except (KeyError, TypeError, ValueError) as error:
        raise ToolFailure("REMOTE_ERROR", "Expected a structured Makepad response.") from error


def validate(name, args):
    schema = SCHEMAS.get(name)
    require(schema is not None, "UNKNOWN_TOOL", "Unknown MSS tool.")
    require(isinstance(args, dict), "INVALID_ARGUMENT", "Arguments must be an object.")
    fields = schema["properties"]
    require(set(args) <= set(fields) and set(schema["required"]) <= set(args),
            "INVALID_ARGUMENT", "Unexpected or missing arguments. Use the tool schema.")
    for key, value in args.items():
        kind = fields[key]["type"]
        valid = {
            "string": lambda: isinstance(value, str) and len(value) <= 32000 and "\x00" not in value,
            "integer": lambda: type(value) is int and -(2**31) <= value < 2**31,
            "number": lambda: type(value) in (int, float) and abs(value) <= 2**31 and math.isfinite(value),
            "boolean": lambda: type(value) is bool,
        }[kind]()
        require(valid, "INVALID_ARGUMENT", f"Invalid value for {key}.")
    if "timeout_ms" in args:
        require(1 <= args["timeout_ms"] <= 15000, "INVALID_ARGUMENT", "timeout_ms must be 1–15000.")
    if "n" in args:
        require(1 <= args["n"] <= 500, "INVALID_ARGUMENT", "n must be 1–500.")
    if "scale" in args:
        require(0.25 <= args["scale"] <= 2, "INVALID_ARGUMENT", "scale must be 0.25–2.")


class Peer:
    """Use the pinned Makepad server through the existing launcher pipes."""

    def __init__(self, plan, log_path):
        with log_path.open("xb") as log:
            self.process = subprocess.Popen(
                plan.command, cwd=plan.cwd, env=plan.env, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW,
            )
        self.sequence = 0
        self.queue = Queue(maxsize=8)
        self.reader = Thread(target=self._read, name="makepad-mcp-stdout", daemon=True)
        self.reader.start()

    def _read(self):
        try:
            while True:
                line = self.process.stdout.readline(MAX_REPLY + 1)
                if not line:
                    raise EOFError("Makepad MCP closed stdout.")
                if len(line) > MAX_REPLY or not line.endswith(b"\n"):
                    raise ValueError("Makepad MCP response exceeds its limit.")
                self.queue.put(json.loads(line))
        except (OSError, ValueError, EOFError, RecursionError) as error:
            self.queue.put(TransportFailure(str(error)))

    def send(self, message):
        try:
            self.process.stdin.write(json_bytes(message))
            self.process.stdin.flush()
        except (OSError, ValueError) as error:
            raise TransportFailure("Makepad MCP input is unavailable.") from error

    def request(self, method, params, timeout=28):
        self.sequence += 1
        self.send({"jsonrpc": "2.0", "id": self.sequence, "method": method, "params": params})
        deadline = monotonic() + timeout
        while True:
            try:
                response = self.queue.get(timeout=max(0, deadline - monotonic()))
            except Empty as error:
                raise TransportFailure("Makepad MCP response timed out.") from error
            if isinstance(response, Exception):
                raise response
            if isinstance(response, dict) and "id" not in response and str(response.get("method", "")).startswith("notifications/"):
                continue
            if not isinstance(response, dict) or response.get("id") != self.sequence or response.get("jsonrpc") != "2.0":
                raise TransportFailure("Makepad MCP response does not match the request.")
            if "error" in response:
                raise ToolFailure("REMOTE_ERROR", "Makepad rejected the MCP request.")
            if not isinstance(response.get("result"), dict):
                raise TransportFailure("Makepad MCP returned a malformed result.")
            return response["result"]

    def call(self, name, args):
        return self.request("tools/call", {"name": name, "arguments": args})

    def close(self):
        try:
            self.process.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            code = self.process.wait(timeout=60)
        except subprocess.TimeoutExpired as error:
            raise ToolFailure("CLEANUP_PENDING", "Launcher did not finish after EOF.") from error
        self.reader.join(timeout=1)
        if not self.reader.is_alive():
            self.process.stdout.close()
        return code


class App:
    def __init__(self, profile, app_id, directory):
        self.profile = profile
        self.app_id = app_id
        self.directory = directory
        self.artifacts = directory / "artifacts"
        self.stack = ExitStack()
        self.peer = None
        self.plan = None
        self.identity = None
        self.receipt_path = None
        self.state = "STARTING"
        self.cleanup_started = False

    def record(self):
        return {
            "app_id": self.app_id, "profile": self.profile, "state": self.state,
            "pid": self.identity.get("app_pid") if self.identity else None,
            "app": self.plan.app_image.name if self.plan else None,
            "app_birth_utc": self.identity.get("app_birth_utc") if self.identity else None,
            "artifact_dir": str(self.artifacts),
            "launcher_receipt": str(self.receipt_path) if self.receipt_path else None,
        }

    def receipt(self):
        candidates = list(self.plan.session_root.glob("*/session.json"))
        require(len(candidates) == 1, "IDENTITY_UNVERIFIED", "Expected one owned launcher receipt.")
        try:
            self.receipt_path = local_path(candidates[0])
            receipt = json.loads(self.receipt_path.read_bytes())
            require(
                receipt["profile_sha256"].lower() == self.plan.profile_sha256.lower()
                and receipt["app_sha256"].lower() == self.plan.app_sha256.lower()
                and receipt["remote_sha256"].lower() == self.plan.remote_sha256.lower()
                and receipt["makepad_revision_declared"] == self.plan.makepad_revision
                and Path(receipt["app_image"]) == self.plan.app_image
                and type(receipt["app_pid"]) is int and receipt["app_pid"] > 0
                and bool(receipt["app_birth_utc"]) and bool(receipt["session_id"]),
                "IDENTITY_UNVERIFIED", "Launcher receipt does not match the admitted profile.",
            )
            if self.identity:
                require(all(receipt[key] == value for key, value in self.identity.items()),
                        "IDENTITY_UNVERIFIED", "Owned process identity changed.")
            return receipt
        except (OSError, KeyError, TypeError, ValueError) as error:
            raise ToolFailure("IDENTITY_UNVERIFIED", "Owned launcher receipt is unavailable.") from error

    def start(self, catalog):
        self.directory.mkdir(parents=True, exist_ok=False)
        self.plan = self.stack.enter_context(catalog.prepare(self.profile, self.directory))
        self.artifacts.mkdir()
        self.peer = Peer(self.plan, self.directory / "launcher-stderr.log")
        initialized = self.peer.request(
            "initialize", {"protocolVersion": VERSIONS[0], "capabilities": {},
                           "clientInfo": {"name": "mss", "version": "1"}}, timeout=40,
        )
        require(initialized.get("protocolVersion") == VERSIONS[0],
                "REMOTE_ERROR", "Unexpected Makepad MCP protocol version.")
        self.peer.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools = self.peer.request("tools/list", {}).get("tools", [])
        self.native_tools = {item["name"] for item in tools}
        receipt = self.receipt()
        status = native_json(self.peer.call("ui__status", {}))
        require(receipt["status"] == "READY" and status.get("pid") == receipt["app_pid"]
                and status.get("app", "").lower() == self.plan.app_image.name.lower() and status.get("w"),
                "IDENTITY_UNVERIFIED", "Makepad status did not identify the owned window.")
        self.identity = {key: receipt[key] for key in ("app_pid", "app_birth_utc", "app_image", "session_id")}
        self.state = "READY"
        write_record(self.directory / "ownership.json", self.record() | self.identity)

    def action_target(self, tool_name, args):
        require(self.plan.access == "semantic", "READ_ONLY_PROFILE", "This profile permits inspection only.")
        require(re.fullmatch(r"[0-9]+:[0-9]+", args["w"]) and bool(args["node"]),
                "INVALID_ARGUMENT", "Use the exact node and window from this app's tree.")
        tree = native_json(self.peer.call("ui__ui", {"node": args["node"], "w": args["w"], "json": True}))
        nodes = [node for window in tree.get("trees", []) if window.get("window") == args["w"]
                 for node in window.get("nodes", []) if node.get("id") == args["node"]]
        require(len(nodes) == 1, "UNKNOWN_NODE", "This node is absent from the selected app window.")
        actions = set(nodes[0].get("actions", "").split(","))
        action = "replace_text" if tool_name == "mss_ui_type" else args["action"]
        require(action in SEMANTIC_ACTIONS and action in actions, "UNSUPPORTED",
                "This node does not advertise the requested semantic action.")

    def capture(self, result, output):
        metadata = native_json(result)
        images = [part for part in result["content"] if part.get("type") == "image"]
        require(len(images) == 1 and images[0].get("mimeType") == "image/png",
                "CAPTURE_UNVERIFIED", "Makepad did not return a PNG image.")
        try:
            image = base64.b64decode(images[0]["data"], validate=True)
            require(len(image) >= 24 and image[:8] == b"\x89PNG\r\n\x1a\n" and image[12:16] == b"IHDR",
                    "CAPTURE_UNVERIFIED", "Invalid PNG header.")
            dimensions = list(struct.unpack(">II", image[16:24]))
            digest = hashlib.sha256(image).hexdigest()
            with local_path(output).open("rb") as saved:
                file_digest = hashlib.file_digest(saved, "sha256").hexdigest()
            require(Path(metadata["png"]) == output and metadata["capture_kind"] == "pixels"
                    and metadata["sz"] == dimensions and all(dimensions) and file_digest == digest,
                    "CAPTURE_UNVERIFIED", "Makepad image and owned PNG file disagree.")
            write_record(output.with_suffix(".json"), metadata | {"sha256": digest, **self.record()})
        except (OSError, KeyError, TypeError, ValueError) as error:
            raise ToolFailure("CAPTURE_UNVERIFIED", "The owned PNG could not be verified.") from error

    def call(self, name, args):
        require(self.state == "READY" and self.peer.process.poll() is None,
                "APP_UNAVAILABLE", "The app channel is unavailable. Close it to check cleanup.")
        require(self.receipt()["status"] == "READY", "APP_UNAVAILABLE", "The launcher is no longer ready.")
        native, _, _, _, read = ROUTES[name]
        require(native in self.native_tools, "UNSUPPORTED", "The admitted Makepad server does not expose this tool.")
        mutating_dispatch = False
        try:
            if not read:
                self.action_target(name, args)
                args.setdefault("json", True)
            if name == "mss_ui_type":
                args.update(action="replace_text", wait=True)
            if name == "mss_ui_tree":
                args.setdefault("json", True)
            if name == "mss_ui_wait":
                args.setdefault("timeout_ms", 5000)
            if name == "mss_grab":
                output = self.artifacts / f"{uuid4().hex}.png"
                args["out"] = str(output)
            mutating_dispatch = not read
            result = self.peer.call(native, args)
        except TransportFailure as error:
            self.state = "OUTCOME_UNKNOWN" if mutating_dispatch else "TRANSPORT_LOST"
            write_record(self.directory / "channel-state.json", self.record())
            raise ToolFailure(self.state, "Makepad transport failed. No request was replayed.") from error
        except ToolFailure as error:
            if not mutating_dispatch:
                raise
            self.state = "OUTCOME_UNKNOWN"
            write_record(self.directory / "channel-state.json", self.record())
            raise ToolFailure(self.state, "Makepad did not confirm the action outcome.") from error
        if mutating_dispatch and result.get("isError"):
            self.state = "OUTCOME_UNKNOWN"
            write_record(self.directory / "channel-state.json", self.record())
            return result_json({"code": self.state, "message": "Makepad reported an error after dispatch.",
                                "native_result": result}, error=True)
        if mutating_dispatch:
            try:
                if args["json"]:
                    handled = native_json(result).get("result") == "handled"
                else:
                    handled = any(part.get("text", "").startswith("handled:")
                                  for part in result.get("content", []))
            except (ToolFailure, AttributeError):
                handled = False
            if not handled:
                self.state = "OUTCOME_UNKNOWN"
                write_record(self.directory / "channel-state.json", self.record())
                return result_json({"code": self.state, "message": "Makepad did not report a handled semantic action.",
                                    "native_result": result}, error=True)
        if name == "mss_grab" and not result.get("isError"):
            self.capture(result, output)
        if name == "mss_status" and not result.get("isError"):
            require(native_json(result).get("pid") == self.identity["app_pid"],
                    "IDENTITY_UNVERIFIED", "Makepad returned a different process identity.")
        return result

    def close(self):
        require(not self.cleanup_started, "CLEANUP_PENDING", "Cleanup was already requested.")
        self.cleanup_started = True
        code = None
        failure = None
        try:
            code = self.peer.close() if self.peer else None
            if self.peer:
                receipt = self.receipt()
                require(code == 0 and receipt["status"] == "CLOSED" and receipt["cleanup"] == "GRACEFUL"
                        and receipt.get("log_capture") == "COMPLETE"
                        and all(receipt.get(key) == 0 for key in ("launcher_exit_code", "app_exit_code", "mcp_exit_code")),
                        "CLEANUP_PENDING", "Graceful exit is not confirmed. See the owned launcher receipt.")
        except Exception as error:
            failure = error
        try:
            self.stack.close()
        except Exception as error:
            if failure is None:
                failure = error
        self.state = "CLOSED" if failure is None else "CLEANUP_PENDING"
        if self.directory.is_dir():
            write_record(self.directory / "closure.json", self.record() | {"launcher_exit_code": code})
        if failure is not None:
            raise ToolFailure("CLEANUP_PENDING", "Cleanup is unresolved. See the owned session directory.") from failure
        return self.record()


class Router:
    def __init__(self, repo):
        self.catalog = Catalog(repo, Path(sys.executable))
        self.root = repo / "proof" / "mss-universal" / "connections" / uuid4().hex
        self.apps = {}
        self.initialized = False

    def get_app(self, app_id):
        app = self.apps.get(app_id)
        require(app is not None, "UNKNOWN_APP", "App ID is not owned by this MCP connection.")
        return app

    def launch_directory(self, app_id):
        path = local_path(self.catalog.repo / "proof", directory=True)
        for component in ("mss-universal", "connections", self.root.name):
            path = path / component
            path.mkdir(exist_ok=True)
            path = local_path(path, directory=True)
        return path / app_id

    def run_tool(self, name, args):
        validate(name, args)
        if name == "mss_list_apps":
            return result_json({"apps": self.catalog.apps()})
        if name == "mss_find_app":
            if "app_id" in args:
                candidates = [self.get_app(args["app_id"])]
            else:
                candidates = self.apps.values()
            return result_json({"apps": [app.record() for app in candidates
                                         if "profile" not in args or args["profile"] == app.profile]})
        if name == "mss_launch_app":
            require(args["profile"] in {item["profile"] for item in self.catalog.apps()},
                    "UNKNOWN_PROFILE", "Choose an admitted profile from mss_list_apps.")
            require(len(self.apps) < MAX_APPS, "APP_LIMIT", "Close an existing app before starting another.")
            app_id = "app_" + uuid4().hex
            app = App(args["profile"], app_id, self.launch_directory(app_id))
            self.apps[app_id] = app
            try:
                app.start(self.catalog)
            except Exception as error:
                try:
                    app.close()
                    self.apps.pop(app_id)
                except ToolFailure:
                    pass
                if app.directory.is_dir():
                    write_record(app.directory / "launch-failure.json", app.record() | {
                        "error_type": type(error).__name__, "error_code": getattr(error, "code", None),
                    })
                raise ToolFailure("LAUNCH_FAILED", f"Launch did not qualify. Owned run: {app.directory}") from error
            return result_json(app.record())
        app = self.get_app(args["app_id"])
        if name == "mss_close_app":
            closed = app.close()
            del self.apps[app.app_id]
            return result_json(closed)
        return app.call(name, {key: value for key, value in args.items() if key != "app_id"})

    def handle(self, message):
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
        if "id" not in message:
            return None
        response = {"jsonrpc": "2.0", "id": message["id"]}
        method, params = message.get("method"), message.get("params", {})
        if not isinstance(params, dict):
            return response | {"error": {"code": -32602, "message": "Invalid params"}}
        if method == "initialize":
            version = params.get("protocolVersion")
            self.initialized = True
            return response | {"result": {
                "protocolVersion": version if version in VERSIONS else VERSIONS[0],
                "serverInfo": {"name": "mss", "version": "1.0.0"}, "capabilities": {"tools": {}},
            }}
        if method == "ping":
            return response | {"result": {}}
        if self.initialized and method == "tools/list":
            return response | {"result": {"tools": TOOLS}}
        if self.initialized and method == "tools/call":
            try:
                outcome = self.run_tool(params.get("name"), params.get("arguments", {}))
            except ToolFailure as error:
                outcome = result_json({"code": error.code, "message": str(error)}, error=True)
            except (OSError, KeyError, ValueError, TypeError, RuntimeError) as error:
                print(f"[mss] Request failed: {type(error).__name__}", file=sys.stderr)
                outcome = result_json({"code": "MSS_ERROR", "message": "Request failed. See local evidence."}, error=True)
            return response | {"result": outcome}
        return response | {"error": {"code": -32601, "message": "Method unavailable"}}

    def close(self):
        ok = True
        for app in self.apps.values():
            if app.cleanup_started:
                ok &= app.state == "CLOSED"
                continue
            try:
                app.close()
            except (ToolFailure, OSError):
                ok = False
                print(f"[mss] Cleanup unresolved for {app.app_id}", file=sys.stderr)
        return ok


def main():
    if sys.platform != "win32" or len(sys.argv) != 1:
        print("[mss] Use the local Windows stdio entry point without arguments.", file=sys.stderr)
        return 2
    router = Router(Path(__file__).resolve().parents[2])
    try:
        while line := sys.stdin.buffer.readline(MAX_REQUEST + 1):
            if len(line) > MAX_REQUEST or not line.endswith(b"\n"):
                print("[mss] Input exceeded the MCP request boundary.", file=sys.stderr)
                break
            try:
                response = router.handle(json.loads(line))
            except (ValueError, RecursionError):
                response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
            if response is not None:
                sys.stdout.buffer.write(json_bytes(response))
                sys.stdout.buffer.flush()
    except (BrokenPipeError, KeyboardInterrupt):
        pass
    finally:
        cleaned = router.close()
    return 0 if cleaned else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print(f"[mss] Startup failed: {type(error).__name__}", file=sys.stderr)
        raise SystemExit(1)
