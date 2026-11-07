"""Local stdio router for admitted Makepad Remote development apps."""

import base64
from contextlib import ExitStack
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
from queue import Empty, Full, Queue
import re
import struct
import subprocess
import sys
from threading import BoundedSemaphore, Event, RLock, Thread
from time import monotonic
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mss_profiles import Catalog, LaunchPlan, SYSTEM_KEYS, check_pin, local_path
from mss_builds import BuildError
from mss_process import confirm_app, is_live, process_identity
from mss_shared import SharedError, Store


VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_REQUEST = 256 * 1024
MAX_REPLY = 24 * 1024 * 1024
MAX_APPS = 8
QUERY = {
    key: "string" for key in ("q", "node", "w", "role", "name", "text", "value", "state", "path", "class")
}
QUERY.update({"nth": "integer", "depth": "integer", "json": "boolean"})
TARGET = {"node": "string", "w": "string", "if_user_seq": "integer", "json": "boolean"}
INPUT_WINDOW = {"w": "integer", "wait": "boolean", "if_user_seq": "integer"}
MODIFIERS = {key: "boolean" for key in ("ctrl", "shift", "alt")}
POINT = {"x": "number", "y": "number"}
POINTER_KINDS = {"move", "down", "up", "click", "scroll", "drag"}
RAW_INPUT = {"mss_ui_key", "mss_ui_mouse", "mss_ui_drop"}
WRITER_FORMAT = "writer-rich-text"
WRITER_EXPORT = "writer__export_fragment"
WRITER_PASTE = "writer__paste_fragment"
WRITER_REFUSALS = ("DESTINATION_NOT_READY", "EMPTY_CLIPBOARD", "EMPTY_SELECTION", "SOURCE_NOT_READY",
                   "INVALID_FRAGMENT", "FRAGMENT_TOO_LARGE", "PASTE_REFUSED")
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
    "mss_ui_key": (
        "ui__key", "Send a Makepad key (c=KeyA, ReturnKey, Tab, Escape, etc.) to the sole owned window. "
        "Use numeric w from status. k is press (default), down, or up. Shared clipboard chords are blocked.",
        INPUT_WINDOW | MODIFIERS | {"c": "string", "k": "string"}, ("w", "c"), False,
    ),
    "mss_ui_mouse": (
        "ui__mouse", "Send move, down, up, click, scroll, or drag in window-local points. Use numeric w from status. "
        "For scroll pass dx/dy. For drag pass x1/y1 and optionally steps (1–60).",
        INPUT_WINDOW | MODIFIERS | POINT | {"k": "string", "b": "integer", "dx": "number", "dy": "number",
                                            "x1": "number", "y1": "number", "steps": "integer"},
        ("w", "k", "x", "y"), False,
    ),
    "mss_ui_drop": (
        "ui__drop", "Drop one existing file (basename in this app's artifact directory) on its sole window. "
        "Use numeric w from status and window-local x/y. Verify the app's response independently.",
        INPUT_WINDOW | POINT | {"file": "string"}, ("w", "file", "x", "y"), False,
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
    tool("mss_list_builds", "List a profile's baseline, registered builds, active build, and rollback target.",
         {"profile": "string"}, ("profile",)),
    tool("mss_register_build", "Register a hash-pinned EXE from the profile's operator-admitted roots. "
         "This leaves the active build unchanged.",
         {"profile": "string", "exe_path": "string", "sha256": "string", "git_sha": "string"},
         ("profile", "exe_path", "sha256"), read=False),
    tool("mss_launch_app", "Launch an independent owned instance of the active or explicitly selected build.",
         {"profile": "string", "build_id": "string"},
         ("profile",), read=False),
    tool("mss_activate_build", "Switch future launches after verifying a live, explicitly selected candidate. "
         "Collect tree and PNG and confirm a postcondition with ui_wait after the last action. "
         "Describe the observed result in verification. Supply the current active ID as expected_active.",
         {"profile": "string", "build_id": "string", "expected_active": "string", "app_id": "string",
          "verification": "string"}, ("profile", "build_id", "expected_active", "app_id", "verification"),
         read=False, destructive=True),
    tool("mss_rollback_build", "Restore the profile's previous build for future launches. "
         "Supply the current active ID as expected_active.", {"profile": "string", "expected_active": "string"},
         ("profile", "expected_active"), read=False, destructive=True),
    tool("mss_find_app", "Find instances owned by this MCP connection and read their state.",
         {"profile": "string", "app_id": "string"}),
    tool("mss_transfer_fragment", "Paste a private Writer fragment copied in one owned RudraOffice app "
         "into the current Writer selection of another owned RudraOffice app. "
         "Format is writer-rich-text. The result contains metadata only; independently verify the edit.",
         {"source_app_id": "string", "target_app_id": "string", "format": "string"},
         ("source_app_id", "target_app_id", "format"), read=False, destructive=True),
    tool("mss_close_app", "Close an owned app through the launcher and check its exit receipt.",
         {"app_id": "string"}, ("app_id",), read=False, destructive=True),
]
TOOLS.extend(
    tool(name, description, {"app_id": "string"} | fields, ("app_id", *required), read=read)
    for name, (_, description, fields, required, read) in ROUTES.items()
)
TOOLS.extend([
    tool("mss_list_instances", "List local MSS instances and explicit sharing modes; no Remote credentials.", {}),
    tool("mss_share_app", "Owner only: allow local attachment in read/control mode, or revoke with private.",
         {"app_id": "string", "mode": "string"}, ("app_id", "mode"), read=False),
    tool("mss_attach_app", "Attach to an explicitly shared MSS instance in this Windows session.",
         {"app_id": "string"}, ("app_id",), read=False),
    tool("mss_detach_app", "Detach this participant only; never quits the application.",
         {"app_id": "string"}, ("app_id",), read=False),
    tool("mss_app_participants", "Read owner and participant connection IDs and effective permissions.",
         {"app_id": "string"}, ("app_id",)),
    tool("mss_operations_list", "Read recent metadata-only per-app mutation sequence and outcomes.",
         {"app_id": "string"}, ("app_id",)),
    tool("mss_operation_status", "Read one operation without repeating it.",
         {"app_id": "string", "operation_id": "string"}, ("app_id", "operation_id")),
    tool("mss_cancel_operation", "Cancel a queued operation only. RUNNING cannot be rolled back.",
         {"app_id": "string", "operation_id": "string"}, ("app_id", "operation_id"), read=False),
])
MUTATIONS = {name for name, route in ROUTES.items() if not route[-1]} | {
    "mss_transfer_fragment", "mss_close_app", "mss_activate_build"}
for item in TOOLS:
    if item["name"] in MUTATIONS:
        item["inputSchema"]["properties"]["queue_timeout_ms"] = {"type": "integer"}
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


def writer_refusal(value):
    if isinstance(value, dict) and value.get("status") == "refused":
        code = value.get("code")
        if isinstance(code, str) and code in WRITER_REFUSALS:
            return code
    return None


def writer_fragment_metadata(fragment):
    require(isinstance(fragment, dict) and fragment.keys() == {"format", "version", "runs"}
            and fragment["format"] == WRITER_FORMAT and type(fragment["version"]) is int and fragment["version"] == 1
            and isinstance(fragment["runs"], list) and 0 < len(fragment["runs"]) <= 64,
            "INVALID_FRAGMENT", "Source did not export a supported Writer fragment.")
    runs = fragment["runs"]
    require(all(isinstance(run, dict) and run.keys() == {"text", "style"}
                and isinstance(run["text"], str) and bool(run["text"]) and isinstance(run["style"], dict)
                and all(type(run["style"].get(key)) is bool for key in ("bold", "italic")) for run in runs),
            "INVALID_FRAGMENT", "Source exported invalid Writer runs.")
    try:
        encoded = json_bytes(fragment).rstrip(b"\n")
        escaped_args = json.dumps({"fragment": fragment}, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError, RecursionError) as error:
        raise ToolFailure("INVALID_FRAGMENT", "Source exported invalid Writer data.") from error
    require(len(encoded) <= 8192 and len(escaped_args) <= 16000,
            "FRAGMENT_TOO_LARGE", "Writer fragment exceeds the transfer limit.")
    return {"fragment_sha256": hashlib.sha256(encoded).hexdigest(), "bytes": len(encoded), "runs": len(runs),
            "inserted_chars": sum(len(run["text"]) for run in runs),
            "bold_chars": sum(len(run["text"]) for run in runs if run["style"]["bold"]),
            "italic_chars": sum(len(run["text"]) for run in runs if run["style"]["italic"])}


def raw_input_refusal(name, args, result):
    # Makepad MCP prefixes built-in tool failures with the native outcome.
    try:
        part, = result["content"]
        text = part["text"]
        if not text.startswith("failed: "):
            return None
        refusal = json.loads(text.removeprefix("failed: "))
        error = refusal.get("err")
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    if refusal.get("applied") is False and error in {"user_intervened", "user_interacting"}:
        return refusal
    if name == "mss_ui_key" and error == f"bad key code {args['c']}":
        return refusal
    return None


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
    if "queue_timeout_ms" in args:
        require(1 <= args["queue_timeout_ms"] <= 30000,
                "INVALID_ARGUMENT", "queue_timeout_ms must be 1–30000; only limits time before dispatch.")
    if "n" in args:
        require(1 <= args["n"] <= 500, "INVALID_ARGUMENT", "n must be 1–500.")
    if "scale" in args:
        require(0.25 <= args["scale"] <= 2, "INVALID_ARGUMENT", "scale must be 0.25–2.")
    if name in RAW_INPUT:
        validate_input(name, args)


def validate_input(name, args):
    require(args["w"] >= 0 and args.get("if_user_seq", 0) >= 0,
            "INVALID_ARGUMENT", "Window and activity sequence must be nonnegative.")
    if name == "mss_ui_key":
        code = args["c"].lower()
        require(re.fullmatch(r"[a-z0-9]{1,24}", code) and args.get("k", "press") in {"down", "up", "press"},
                "INVALID_ARGUMENT", "Use a Makepad key name and press, down, or up.")
        clipboard_chord = (
            args.get("ctrl") and code in {"c", "v", "x", "keyc", "keyv", "keyx", "insert"}
            or args.get("shift") and code in {"insert", "delete", "del"}
        )
        require(not clipboard_chord, "SHARED_CLIPBOARD", "Clipboard shortcuts are not app-local.")
        return

    require(args["x"] >= 0 and args["y"] >= 0, "INVALID_ARGUMENT", "Use nonnegative window-local points.")
    if name == "mss_ui_drop":
        file = args["file"]
        require(re.fullmatch(r"[\w.-]{1,240}", file) and not file.endswith(".") and not Path(file).is_reserved(),
                "INVALID_ARGUMENT", "Use a file basename from this app's artifact directory.")
        return

    kind = args["k"]
    require(kind in POINTER_KINDS and 0 <= args.get("b", 0) <= 2,
            "INVALID_ARGUMENT", "Use a supported pointer event and a button in 0–2.")
    if kind == "scroll":
        dx, dy = args.get("dx", 0), args.get("dy", 0)
        require(0 < max(abs(dx), abs(dy)) <= 10000,
                "INVALID_ARGUMENT", "Scroll needs a nonzero delta bounded to 10000 points.")
    else:
        require(not ({"dx", "dy"} & args.keys()), "INVALID_ARGUMENT", "Deltas belong to scroll.")
    if kind == "drag":
        require(args.get("x1", -1) >= 0 and args.get("y1", -1) >= 0 and 1 <= args.get("steps", 12) <= 60,
                "INVALID_ARGUMENT", "Drag needs a nonnegative endpoint and 1–60 steps.")
    else:
        require(not ({"x1", "y1", "steps"} & args.keys()), "INVALID_ARGUMENT", "Endpoints and steps belong to drag.")


class Peer:
    """Use the pinned Makepad server through the existing launcher pipes."""

    def __init__(self, plan, log_path):
        with log_path.open("xb") as log:
            self.process = subprocess.Popen(
                plan.command, cwd=plan.cwd, env=plan.env, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW,
            )
        self.sequence = 0
        self.lock = RLock()
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
        with self.lock:
            return self._request(method, params, timeout)

    def _request(self, method, params, timeout):
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
        with self.lock:
            return self._close()

    def _close(self):
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
    def __init__(self, profile, app_id, directory, build_id=None):
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
        self.requested_build = build_id
        self.build_tree_observed = False
        self.build_png = None
        self.build_action_dispatched = False
        self.build_postcondition = None
        self.os_identity = None
        self.participant = False
        self.read_peer = None
        self.read_lock = RLock()

    def record(self):
        return {
            "app_id": self.app_id, "profile": self.profile, "state": self.state,
            "pid": self.identity.get("app_pid") if self.identity else None,
            "app": self.plan.app_image.name if self.plan else None,
            "build_id": self.plan.build_id if self.plan else None,
            "app_sha256": self.plan.app_sha256 if self.plan else None,
            "app_birth_utc": self.identity.get("app_birth_utc") if self.identity else None,
            "artifact_dir": str(self.artifacts),
            "launcher_receipt": str(self.receipt_path) if self.receipt_path else None,
            "windows_session_id": self.os_identity["windows_session"] if self.os_identity else None,
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
        self.plan = self.stack.enter_context(catalog.prepare(self.profile, self.directory, self.requested_build))
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
        self.os_identity = confirm_app(self.identity, None)
        self.state = "READY"
        write_record(self.directory / "ownership.json", self.record() | self.identity)

    def direct_peer(self, directory):
        """A second official MCP client, bound to the owner's exact discovery directory."""
        receipt = self.receipt()
        profile_path = local_path(self.plan.cwd.parent / "profile.json")
        check_pin(profile_path, self.plan.profile_sha256)
        profile = json.loads(profile_path.read_bytes())
        remote = local_path(profile["remote_executable"])
        check_pin(remote, self.plan.remote_sha256)
        env = dict(self.plan.env)
        env.update(TEMP=str(self.receipt_path.parent), TMP=str(self.receipt_path.parent))
        discovery = json.loads((self.receipt_path.parent / f'makepad-remote-{receipt["app_pid"]}.json').read_bytes())
        require(discovery.get("pid") == receipt["app_pid"]
                and re.fullmatch(r"tcp:127\.0\.0\.1:[0-9]+", discovery.get("socket", ""))
                and bool(discovery.get("token")), "IDENTITY_UNVERIFIED", "Owned Remote discovery changed.")
        plan = replace(self.plan, command=[str(remote), "mcp", str(receipt["app_pid"])], env=env)
        peer = Peer(plan, directory / f"remote-client-{uuid4().hex}.log")
        try:
            peer.request("initialize", {"protocolVersion": VERSIONS[0], "capabilities": {},
                                       "clientInfo": {"name": "mss", "version": "1"}})
            peer.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            status = native_json(peer.call("ui__status", {}))
            require(status.get("pid") == self.identity["app_pid"],
                    "IDENTITY_UNVERIFIED", "Attached Remote process changed.")
            return peer
        except Exception:
            peer.close()
            raise

    def read_call(self, name, args, directory=None):
        # Separate native client lets observations progress during another client's long call.
        with self.read_lock:
            self.ensure_ready(allow_unknown=True)
            if self.read_peer is None:
                self.read_peer = self.direct_peer(directory or self.directory)
            return self.call(name, args, peer=self.read_peer)

    def action_target(self, tool_name, args):
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

    def focus_observed(self, args):
        # Stock Makepad may set app-local focus itself and report "fallback".
        query = {"node": args["node"], "w": args["w"], "json": True}
        tree = native_json(self.peer.call("ui__ui", query))
        return any(window["window"] == args["w"] and window["focus"] == args["node"]
                   and any(node["id"] == args["node"] for node in window["nodes"])
                   for window in tree["trees"])

    def input_target(self, name, args):
        status = native_json(self.peer.call("ui__status", {}))
        require(isinstance(status, dict) and status.get("pid") == self.identity["app_pid"],
                "IDENTITY_UNVERIFIED", "Makepad returned a different process identity.")
        windows = status.get("w", [])
        matches = [window for window in windows if window["i"] == args["w"]]
        require(len(matches) == 1, "UNKNOWN_WINDOW", "Use a window ID from this app's current status.")
        # At this Makepad revision keys use process-wide focus and drop events have no window ID.
        require(name == "mss_ui_mouse" or len(windows) == 1, "UNSUPPORTED",
                "Key and drop require exactly one live window on the admitted Makepad app.")
        if name == "mss_ui_key":
            return
        width, height = matches[0]["sz"]
        require(args["x"] < width and args["y"] < height and
                args.get("x1", 0) < width and args.get("y1", 0) < height,
                "INVALID_ARGUMENT", "Input points must be inside the selected window.")
        if name == "mss_ui_drop":
            try:
                directory = local_path(self.artifacts, directory=True)
                path = local_path(directory / args.pop("file"))
                require(path.parent == directory and path.stat().st_nlink == 1 and len(str(path).encode("utf-8")) <= 4096,
                        "INVALID_ARGUMENT", "Use a local, unlinked file owned by this app's artifact directory.")
            except (OSError, ValueError) as error:
                raise ToolFailure("INVALID_ARGUMENT", "File is missing or is outside this app's artifact directory.") from error
            args["path"] = str(path)
        if args.get("k") == "drag":
            args.setdefault("steps", 12)

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
            return digest
        except (OSError, KeyError, TypeError, ValueError) as error:
            raise ToolFailure("CAPTURE_UNVERIFIED", "The owned PNG could not be verified.") from error

    def ensure_ready(self, *, allow_unknown=False):
        require(self.state in ({"READY", "OUTCOME_UNKNOWN"} if allow_unknown else {"READY"})
                and self.peer.process.poll() is None,
                "APP_UNAVAILABLE", "The app channel is unavailable. Close it to check cleanup.")
        require(self.receipt()["status"] == "READY", "APP_UNAVAILABLE", "The launcher is no longer ready.")
        if self.os_identity is not None:
            try:
                confirm_app(self.identity, self.os_identity)
            except OSError as error:
                raise ToolFailure("IDENTITY_UNVERIFIED", "Owned OS process identity changed.") from error

    def call(self, name, args, *, peer=None):
        native, _, _, _, read = ROUTES[name]
        self.ensure_ready(allow_unknown=read)
        require(native in self.native_tools, "UNSUPPORTED", "The admitted Makepad server does not expose this tool.")
        raw_input = name in RAW_INPUT
        mutating_dispatch = False
        try:
            if not read:
                require(self.plan.access == "semantic", "READ_ONLY_PROFILE", "This profile permits inspection only.")
                if raw_input:
                    self.input_target(name, args)
                else:
                    self.action_target(name, args)
                    args.setdefault("json", True)
            if name == "mss_ui_type":
                args.update(action="replace_text", wait=True)
            if name == "mss_ui_tree":
                args.setdefault("json", True)
            if name == "mss_ui_wait":
                args.setdefault("timeout_ms", 5000)
                if "count" in args or args.get("gone") is True or args.get("changed") is True:
                    self.build_postcondition = None
            if name == "mss_grab":
                output = self.artifacts / f"{uuid4().hex}.png"
                args["out"] = str(output)
            mutating_dispatch = not read
            result = (peer or self.peer).call(native, args)
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
            refusal = raw_input_refusal(name, args, result) if raw_input else None
            if refusal is not None:
                return result_json({"code": "NOT_DISPATCHED", "native_refusal": refusal}, error=True)
            self.state = "OUTCOME_UNKNOWN"
            write_record(self.directory / "channel-state.json", self.record())
            return result_json({"code": self.state, "message": "Makepad reported an error after dispatch.",
                                "native_result": result}, error=True)
        if mutating_dispatch:
            try:
                if raw_input:
                    acknowledgement = native_json(result)
                    handled = acknowledgement.get("ok") == 1
                elif args["json"]:
                    outcome = native_json(result).get("result")
                    handled = outcome == "handled" or (outcome == "fallback" and args.get("action") == "focus"
                                                       and self.focus_observed(args))
                else:
                    reply = next((part["text"] for part in result.get("content", []) if part.get("type") == "text"), "")
                    handled = reply.startswith("handled:") or (reply.startswith("fallback:")
                              and args.get("action") == "focus" and self.focus_observed(args))
            except (ToolFailure, TransportFailure, AttributeError, KeyError, TypeError):
                handled = False
            if not handled:
                self.state = "OUTCOME_UNKNOWN"
                write_record(self.directory / "channel-state.json", self.record())
                return result_json({"code": self.state, "message": "Makepad did not acknowledge the expected dispatch.",
                                    "native_result": result}, error=True)
            self.build_action_dispatched = True
            self.build_postcondition = None
            if raw_input:
                return result_json({"code": "DISPATCHED", "effect": "NOT_VERIFIED", "native_ack": acknowledgement})
        if name == "mss_grab" and not result.get("isError"):
            digest = self.capture(result, output)
            if self.requested_build is not None:
                self.build_png = (output, digest)
        if name == "mss_status" and not result.get("isError"):
            status = native_json(result)
            require(status.get("pid") == self.identity["app_pid"],
                    "IDENTITY_UNVERIFIED", "Makepad returned a different process identity.")
            return result_json(status | {"build_id": self.plan.build_id, "app_sha256": self.plan.app_sha256})
        if self.requested_build is not None and args.get("json") is True and not result.get("isError"):
            self.observe_build(name, args, result)
        return result

    def observe_build(self, name, args, result):
        if name == "mss_ui_tree":
            self.build_tree_observed |= bool(native_json(result).get("trees"))
        if name != "mss_ui_wait" or not self.build_action_dispatched:
            return
        if not ("count" in args or args.get("gone") is True or args.get("changed") is True):
            return
        count = native_json(result).get("count")
        if type(count) is int and count >= 0 and count == (0 if args.get("gone") is True else args.get("count", count)):
            self.build_postcondition = {
                "query_sha256": hashlib.sha256(args["q"].encode("utf-8")).hexdigest(),
                "window": args.get("w"), "count": count,
                "conditions": {key: args[key] for key in ("count", "gone", "changed") if key in args},
            }

    def activation_evidence(self, profile, build_id, statement):
        require(self.state == "READY" and self.profile == profile and self.requested_build == build_id
                and self.plan.build_id == build_id and self.build_tree_observed and self.build_png
                and self.build_postcondition is not None,
                "VERIFICATION_REQUIRED", "Use an owned, explicitly launched build with tree, PNG, and verified ui_wait.")
        status = native_json(self.call("mss_status", {}))
        require(bool(status.get("w")), "VERIFICATION_REQUIRED", "The tested app has no live window.")
        png, digest = self.build_png
        try:
            check_pin(local_path(png), digest)
        except (OSError, ValueError) as error:
            raise ToolFailure("VERIFICATION_REQUIRED", "The tested app's PNG is unavailable or changed.") from error
        evidence = self.directory / f"build-verification-{uuid4().hex}.json"
        write_record(evidence, self.record() | {"statement": statement, "png_sha256": digest,
                                                "png": str(png), "postcondition": self.build_postcondition})
        return {"statement": statement, "app_id": self.app_id, "launcher_receipt": str(self.receipt_path),
                "evidence": str(evidence), "png": str(png), "sha256": self.plan.app_sha256}

    def close(self):
        with self.read_lock:
            return self._close_owned()

    def _close_owned(self):
        require(not self.cleanup_started, "CLEANUP_PENDING", "Cleanup was already requested.")
        self.cleanup_started = True
        self.state = "CLOSING"
        code = None
        failure = None
        try:
            if self.read_peer:
                self.read_peer.close()
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
        self.shared = None
        self.apps_lock = RLock()
        self.stopping = False

    def begin_shutdown(self):
        self.stopping = True
        if self.shared is not None:
            self.shared.cancel_pending()

    def store(self):
        with self.apps_lock:
            if self.shared is None:
                base = local_path(self.catalog.repo / "MSS_MCP/profiles", directory=True) / "local.shared"
                base.mkdir(exist_ok=True)
                base = local_path(base, directory=True)
                self.shared = Store(base / "control.sqlite3", self.root.name, process_identity(os.getpid()), is_live)
            return self.shared

    def permission(self, app_id, *, control=False, owner=False):
        if getattr(self, "shared", None) is not None:
            mode = self.shared.permission(app_id, control=control, owner=owner)
            require(self.shared.app(app_id)["state"] != "OWNER_LOST",
                    "OWNER_LOST", "The process owner disconnected; no takeover or further dispatch is allowed.")
            return mode

    def build_revision(self, app_id):
        operations = [op for op in self.shared.operations(app_id)
                      if op["tool"] in MUTATIONS - {"mss_activate_build", "mss_close_app"}
                      and op["state"] not in {"QUEUED", "CANCELLED"}]
        return (max((op["sequence"] for op in operations), default=0),
                any(op["state"] == "RUNNING" for op in operations))

    def publish(self, app):
        self.store().publish(app.app_id, app.record() | {
            "directory": str(app.directory), "os_identity": app.os_identity,
            "identity": app.identity, "native_tools": sorted(app.native_tools),
        })

    def attach(self, app_id):
        require(app_id not in self.apps, "ALREADY_ATTACHED", "This connection already holds the app.")
        store = self.store()
        store.attach(app_id)
        try:
            row = store.app(app_id)
            base = local_path(self.catalog.repo / "proof/mss-universal/connections", directory=True)
            directory = local_path(row["directory"], directory=True)
            require(directory.is_relative_to(base) and directory.name == app_id,
                    "IDENTITY_UNVERIFIED", "Shared app directory is not an MSS launch.")
            profile_path = local_path(directory / "profile.json")
            # The launcher pins admitted EXEs; receipt pins this materialized profile.
            receipt_path = local_path(row["launcher_receipt"])
            receipt = json.loads(receipt_path.read_bytes())
            check_pin(profile_path, receipt["profile_sha256"])
            profile = json.loads(profile_path.read_bytes())
            require(receipt["status"] == "READY" and row["profile"] in self.catalog.entries,
                    "APP_UNAVAILABLE", "Shared launcher is not ready.")
            check_pin(local_path(profile["app_executable"]), receipt["app_sha256"])
            check_pin(local_path(profile["remote_executable"]), receipt["remote_sha256"])
            parent = self.launch_directory(app_id)
            parent.mkdir(exist_ok=True)
            parent = local_path(parent, directory=True)
            own_directory = parent / ("attachment-" + uuid4().hex)
            own_directory.mkdir()
            app = App(row["profile"], app_id, own_directory)
            app.artifacts.mkdir()
            env = {key: os.environ[key] for key in SYSTEM_KEYS if key in os.environ}
            windows = Path(env["SystemRoot"])
            env.update(PATH=os.pathsep.join(map(str, (windows / "System32", windows))),
                       TEMP=str(receipt_path.parent), TMP=str(receipt_path.parent))
            app.plan = LaunchPlan([], Path(profile["working_directory"]), env, Path(profile["session_root"]),
                                  Path(profile["app_executable"]), receipt["app_sha256"], receipt["remote_sha256"],
                                  receipt["makepad_revision_declared"], receipt["profile_sha256"],
                                  self.catalog.entries[row["profile"]]["access"], row.get("build_id"))
            app.identity, app.os_identity = row["identity"], row["os_identity"]
            confirm_app(app.identity, app.os_identity)
            require(app.os_identity["windows_session"] == process_identity(os.getpid())["windows_session"],
                    "ACCESS_DENIED", "Only the current Windows session is supported.")
            app.native_tools = set(row["native_tools"])
            app.receipt_path, app.participant = receipt_path, True
            app.peer = app.direct_peer(own_directory)
            app.state = "READY"
            app.ensure_ready()
            self.apps[app_id] = app
            return result_json(app.record() | {"mode": store.permission(app_id), "owner": False})
        except Exception:
            if "app" in locals() and app.peer:
                app.peer.close()
            store.detach(app_id)
            raise

    def detach(self, app_id):
        app = self.get_app(app_id)
        require(app.participant, "OWNER_CANNOT_DETACH", "Owner closes its app; ownership is not transferred.")
        try:
            self.store().detach(app_id)  # Cancel queued calls before closing only our own clients.
        except SharedError as error:
            if error.code != "NOT_ATTACHED":  # Owner may already have revoked this attachment.
                raise
        with app.read_lock:
            app.state = "DETACHING"
            if app.read_peer:
                app.read_peer.close()
            app.peer.close()
            self.apps.pop(app_id, None)
        return result_json({"app_id": app_id, "state": "DETACHED", "app_closed": False})

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

    def export_fragment(self, args):
        require(args["format"] == WRITER_FORMAT, "UNSUPPORTED_FORMAT", "Only writer-rich-text is supported.")
        source = self.get_app(args["source_app_id"])
        target = self.get_app(args["target_app_id"])
        self.permission(source.app_id)
        self.permission(target.app_id, control=True)
        require(source is not target, "INVALID_ARGUMENT", "Select two distinct app IDs.")
        source.ensure_ready()
        target.ensure_ready()
        require(source.identity["app_pid"] != target.identity["app_pid"],
                "INVALID_ARGUMENT", "Transfer requires two distinct processes.")
        require(source.profile == target.profile == "rudraoffice" and source.plan.access == target.plan.access == "semantic"
                and source.plan.makepad_revision == target.plan.makepad_revision
                and WRITER_EXPORT in source.native_tools and WRITER_PASTE in target.native_tools,
                "UNSUPPORTED", "Both owned apps must expose compatible Writer transfer tools.")
        try:
            fragment = native_json(source.peer.call(WRITER_EXPORT, {"source": "clipboard"}))
        except TransportFailure as error:
            source.state = "TRANSPORT_LOST"
            raise ToolFailure("TRANSPORT_LOST", "Source export failed before paste was sent.") from error
        refusal = writer_refusal(fragment)
        if refusal:
            return result_json({"code": "TRANSFER_REFUSED", "phase": "export", "reason": refusal}, error=True)
        metadata = writer_fragment_metadata(fragment)
        return target, fragment, metadata

    def transfer_fragment(self, args):
        exported = self.export_fragment(args)
        if isinstance(exported, dict):
            return exported  # Export refusal; no target action was enqueued or sent.
        target, fragment, metadata = exported
        if getattr(self, "shared", None) is not None:
            return self.queued(target, "mss_transfer_fragment", args,
                               lambda: self.paste_fragment(target, args, fragment, metadata))
        return self.paste_fragment(target, args, fragment, metadata)

    def paste_fragment(self, target, args, fragment, metadata):
        target.ensure_ready()
        try:
            reply = native_json(target.peer.call(WRITER_PASTE, {"fragment": fragment}))
        except (ToolFailure, TransportFailure, RecursionError):
            reply = None
        refusal = writer_refusal(reply)
        if refusal:
            return result_json({"code": "TRANSFER_REFUSED", "phase": "paste", "reason": refusal}, error=True)
        if (isinstance(reply, dict) and reply.get("status") == "applied" and reply.get("model_match") is True
                and all(type(reply.get(key)) is int and reply[key] == metadata[key]
                        for key in ("inserted_chars", "bold_chars", "italic_chars"))):
            target.build_action_dispatched = True
            target.build_postcondition = None
            return result_json({"code": "APPLIED", "model_match": True, **args, **metadata})

        target.state = "OUTCOME_UNKNOWN"
        try:
            write_record(target.directory / "channel-state.json", target.record())
        except OSError:
            print("[mss] Unable to save the Writer transfer channel state.", file=sys.stderr)
        raise ToolFailure("OUTCOME_UNKNOWN", "Writer paste outcome is unconfirmed. The request was not replayed.")

    def queued(self, app, name, args, dispatch):
        require(not getattr(self, "stopping", False) or name == "mss_close_app",
                "CONNECTION_CLOSING", "This connection is closing; no new GUI mutation was accepted.")
        store = self.shared
        op = store.enqueue(app.app_id, name, args.get("queue_timeout_ms", 10000))
        op = store.wait_turn(op["operation_id"])
        if op["state"] != "RUNNING":
            return result_json({"code": op["state"], "operation_id": op["operation_id"],
                                "effect": "NOT_DISPATCHED"}, error=True)
        try:
            self.permission(app.app_id, control=name != "mss_close_app",
                            owner=name in {"mss_close_app", "mss_activate_build"})
            result = dispatch()
            if result.get("isError"):
                data = result.get("structuredContent", {})
                state = "OUTCOME_UNKNOWN" if data.get("code") == "OUTCOME_UNKNOWN" else "FAILED"
            else:
                state = "APPLIED"
            op = store.finish(op["operation_id"], state,
                              code=result.get("structuredContent", {}).get("code"))
            try:
                data = native_json(result) if not result.get("isError") else result.get("structuredContent", {})
            except ToolFailure:
                data = {"effect": "NOT_VERIFIED"}
            return result_json(data | {"operation_id": op["operation_id"], "operation_state": op["state"],
                                       "operation_sequence": op["sequence"], "effect": "NOT_VERIFIED"},
                               error=bool(result.get("isError")))
        except (ToolFailure, SharedError) as error:
            op = store.finish(op["operation_id"], "OUTCOME_UNKNOWN" if error.code == "OUTCOME_UNKNOWN" else "FAILED",
                              code=error.code)
            return result_json({"code": error.code, "message": str(error), "operation_id": op["operation_id"],
                                "operation_state": op["state"], "effect": "NOT_VERIFIED"}, error=True)
        except Exception:
            store.finish(op["operation_id"], "OUTCOME_UNKNOWN", code="DISPATCH_EXCEPTION")
            raise

    def run_tool(self, name, args):
        validate(name, args)
        require(not getattr(self, "stopping", False) or name == "mss_close_app",
                "CONNECTION_CLOSING", "This connection is closing.")
        if name == "mss_list_instances":
            rows = self.store().list_instances()
            fields = ("app_id", "profile", "state", "pid", "app_birth_utc", "app_sha256", "build_id",
                      "windows_session_id", "owner_connection_id", "share_mode")
            return result_json({"connection_id": self.root.name,
                                "instances": [{key: row.get(key) for key in fields} for row in rows]})
        if name == "mss_attach_app":
            with self.apps_lock:
                return self.attach(args["app_id"])
        if name == "mss_detach_app":
            return self.detach(args["app_id"])
        if name in {"mss_share_app", "mss_app_participants", "mss_operations_list", "mss_operation_status", "mss_cancel_operation"}:
            store = self.store()
            if name == "mss_share_app":
                app = self.get_app(args["app_id"])
                with app.read_lock:
                    row = store.share(args["app_id"], args["mode"])
                    app.build_tree_observed = False
                    app.build_png = None
                    app.build_action_dispatched = False
                    app.build_postcondition = None
                return result_json({key: row[key] for key in ("app_id", "share_mode", "owner_connection_id")})
            if name == "mss_app_participants":
                return result_json(store.participants(args["app_id"]))
            if name == "mss_operations_list":
                return result_json({"operations": store.operations(args["app_id"])})
            if name == "mss_cancel_operation":
                return result_json(store.cancel(args["app_id"], args["operation_id"]))
            return result_json(store.operation(args["app_id"], args["operation_id"]))
        if name == "mss_transfer_fragment":
            return self.transfer_fragment(args)
        if name == "mss_list_apps":
            return result_json({"apps": self.catalog.apps()})
        if name == "mss_list_builds":
            return result_json(self.catalog.build_registry(args["profile"]).list())
        if name == "mss_register_build":
            registry = self.catalog.build_registry(args["profile"])
            return result_json(registry.register(args["exe_path"], args["sha256"], args.get("git_sha")))
        if name == "mss_activate_build":
            statement = args["verification"].strip()
            require(0 < len(statement) <= 512, "INVALID_ARGUMENT", "Describe the verification in 1–512 characters.")
            registry = self.catalog.build_registry(args["profile"])
            app = self.get_app(args["app_id"])
            self.permission(app.app_id, control=True, owner=True)
            def activate_owned():
                with app.read_lock:
                    require(self.shared.app(app.app_id)["share_mode"] == "private",
                            "VERIFICATION_REQUIRED", "Revoke sharing and reverify the candidate before activation.")
                    revision, running = self.build_revision(app.app_id)
                    require(not running and app.build_postcondition is not None
                            and app.build_postcondition.get("operation_sequence") == revision,
                            "VERIFICATION_REQUIRED", "Candidate verification is stale after a shared or concurrent mutation.")
                    evidence = app.activation_evidence(args["profile"], args["build_id"], statement)
                    return result_json(registry.activate(args["build_id"], args["expected_active"], evidence))
            return self.queued(app, name, args, activate_owned)
        if name == "mss_rollback_build":
            return result_json(self.catalog.build_registry(args["profile"]).rollback(args["expected_active"]))
        if name == "mss_find_app":
            if "app_id" in args:
                candidates = [self.get_app(args["app_id"])]
            else:
                candidates = list(self.apps.values())
            records = []
            for app in candidates:
                if "profile" in args and args["profile"] != app.profile:
                    continue
                record = app.record()
                if getattr(self, "shared", None) is not None:
                    record["state"] = self.shared.app(app.app_id)["state"]
                records.append(record)
            return result_json({"apps": records})
        if name == "mss_launch_app":
            require(args["profile"] in {item["profile"] for item in self.catalog.apps()},
                    "UNKNOWN_PROFILE", "Choose an admitted profile from mss_list_apps.")
            require(len(self.apps) < MAX_APPS, "APP_LIMIT", "Close an existing app before starting another.")
            app_id = "app_" + uuid4().hex
            app = App(args["profile"], app_id, self.launch_directory(app_id), args.get("build_id"))
            self.apps[app_id] = app
            try:
                app.start(self.catalog)
                self.publish(app)
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
                if isinstance(error, BuildError):
                    raise
                raise ToolFailure("LAUNCH_FAILED", f"Launch did not qualify. Owned run: {app.directory}") from error
            return result_json(app.record())
        app = self.get_app(args["app_id"])
        self.permission(app.app_id, control=name in MUTATIONS and name != "mss_close_app", owner=name == "mss_close_app")
        if getattr(self, "shared", None) is not None:
            row = self.shared.app(app.app_id)
            if row["state"] == "CLOSED":
                if name == "mss_status":
                    return result_json(app.record() | {"state": "CLOSED", "w": []})
                raise ToolFailure("CLOSED", "The owner closed this application.")
        if name == "mss_close_app":
            def close_owned():
                closed = app.close()
                self.shared.update_state(app.app_id, closed["state"])
                del self.apps[app.app_id]
                return result_json(closed)
            return self.queued(app, name, args, close_owned)
        native_args = {key: value for key, value in args.items() if key not in {"app_id", "queue_timeout_ms"}}
        if getattr(self, "shared", None) is not None:
            if name in MUTATIONS:
                return self.queued(app, name, args, lambda: app.call(name, native_args))
            verifying = name == "mss_ui_wait" and app.requested_build is not None
            revision_before = self.build_revision(app.app_id) if verifying else None
            result = app.read_call(name, native_args)
            if verifying:
                revision_after = self.build_revision(app.app_id)
                with app.read_lock:
                    if revision_before != revision_after or revision_after[1]:
                        app.build_postcondition = None
                    elif app.build_postcondition is not None:
                        app.build_postcondition["operation_sequence"] = revision_after[0]
            if name == "mss_status" and not result.get("isError"):
                return result_json(native_json(result) | {"state": self.shared.app(app.app_id)["state"],
                                                         "windows_session_id": app.os_identity["windows_session"]})
            return result
        return app.call(name, native_args)

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
            except (ToolFailure, BuildError, SharedError) as error:
                outcome = result_json({"code": error.code, "message": str(error)}, error=True)
            except (OSError, KeyError, ValueError, TypeError, RuntimeError) as error:
                print(f"[mss] Request failed: {type(error).__name__}", file=sys.stderr)
                outcome = result_json({"code": "MSS_ERROR", "message": "Request failed. See local evidence."}, error=True)
            return response | {"result": outcome}
        return response | {"error": {"code": -32601, "message": "Method unavailable"}}

    def close(self):
        ok = True
        for app in list(self.apps.values()):
            if app.participant:
                try:
                    self.detach(app.app_id)
                except (ToolFailure, SharedError, OSError):
                    ok = False
                continue
            if app.cleanup_started:
                ok &= app.state == "CLOSED"
                continue
            try:
                outcome = self.run_tool("mss_close_app", {"app_id": app.app_id, "queue_timeout_ms": 30000})
                ok &= not outcome.get("isError")
            except (ToolFailure, SharedError, OSError):
                ok = False
                print(f"[mss] Cleanup unresolved for {app.app_id}", file=sys.stderr)
        if self.shared is not None:
            self.shared.retire_connection()
        return ok


def main():
    if sys.platform != "win32" or len(sys.argv) != 1:
        print("[mss] Use the local Windows stdio entry point without arguments.", file=sys.stderr)
        return 2
    router = Router(Path(__file__).resolve().parents[2])
    output_lock, slots = RLock(), BoundedSemaphore(24)
    transport_closed = Event()
    output_failed = Event()
    incoming = Queue(maxsize=24)

    def offer(value):
        while not transport_closed.is_set():
            try:
                incoming.put(value, timeout=0.1)
                return
            except Full:
                pass

    def read_input():
        # Raw reads avoid a daemon retaining BufferedReader's lock at interpreter shutdown.
        pending = bytearray()
        try:
            while not transport_closed.is_set():
                chunk = os.read(sys.stdin.fileno(), 8192)
                if not chunk:
                    if pending:
                        offer(bytes(pending))
                    offer(None)
                    return
                pending.extend(chunk)
                while b"\n" in pending:
                    line, _, remainder = pending.partition(b"\n")
                    pending = bytearray(remainder)
                    offer(bytes(line) + b"\n")
                if len(pending) > MAX_REQUEST:
                    offer(bytes(pending))
                    return
        except OSError:
            offer(None)

    def respond(message):
        try:
            response = router.handle(message)
            if response is not None:
                with output_lock:
                    sys.stdout.buffer.write(json_bytes(response))
                    sys.stdout.buffer.flush()
        except (OSError, ValueError):
            output_failed.set()
            transport_closed.set()
            with output_lock:
                try:
                    sys.stdout.close()
                except OSError:
                    pass
        finally:
            slots.release()

    try:
        Thread(target=read_input, name="mss-stdin", daemon=True).start()
        with ThreadPoolExecutor(max_workers=16, thread_name_prefix="mss-request") as executor:
            while not transport_closed.is_set():
                try:
                    line = incoming.get(timeout=0.1)
                except Empty:
                    continue
                if line is None:
                    break
                if len(line) > MAX_REQUEST or not line.endswith(b"\n"):
                    print("[mss] Input exceeded the MCP request boundary.", file=sys.stderr)
                    break
                try:
                    message = json.loads(line)
                except (ValueError, RecursionError):
                    with output_lock:
                        sys.stdout.buffer.write(json_bytes({"jsonrpc": "2.0", "id": None,
                                                           "error": {"code": -32700, "message": "Parse error"}}))
                        sys.stdout.buffer.flush()
                    continue
                # Keep initialization and immediate refusals ordered for existing clients.
                # Only already-bound app calls need concurrent progress.
                params = message.get("params", {}) if isinstance(message, dict) else {}
                args = params.get("arguments", {}) if isinstance(params, dict) else {}
                bound = isinstance(args, dict) and any(isinstance(args.get(key), str)
                         and args[key] in router.apps for key in ("app_id", "target_app_id"))
                slots.acquire()
                if bound and message.get("method") == "tools/call":
                    executor.submit(respond, message)
                else:
                    respond(message)
            transport_closed.set()
            router.begin_shutdown()
    except (BrokenPipeError, KeyboardInterrupt):
        pass
    finally:
        transport_closed.set()
        if not router.stopping:
            router.begin_shutdown()
        cleaned = router.close()
    return 0 if cleaned and not output_failed.is_set() else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print(f"[mss] Startup failed: {type(error).__name__}", file=sys.stderr)
        raise SystemExit(1)

