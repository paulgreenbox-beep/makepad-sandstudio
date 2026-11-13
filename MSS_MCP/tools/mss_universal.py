"""Local stdio router for admitted Makepad Remote development apps."""

# Freeze the server implementation before any MSS helper import. The small initial
# boot wrapper and the interpreter itself are outside this source attestation.
if __name__ == "__main__" and "_MSS_FROZEN_STARTUP" not in globals():
    import hashlib as _hashlib
    import importlib.abc as _abc
    import importlib.util as _util
    import json as _json
    import sys as _sys
    from datetime import datetime as _datetime, timezone as _timezone
    from pathlib import Path as _Path

    _base = _Path(__file__).resolve().parent
    _names = ("mss_universal", "mss_profiles", "mss_builds", "mss_process", "mss_shared")
    if any(_name in _sys.modules for _name in _names):
        raise RuntimeError("MSS source was imported before the startup snapshot")
    _frozen = {_name: ((_base / (_name + ".py")).read_bytes(), str(_base / (_name + ".py")))
               for _name in _names}
    _digests = {_name + ".py": {"sha256": _hashlib.sha256(_data[0]).hexdigest()}
                for _name, _data in sorted(_frozen.items())}
    _MSS_FROZEN_STARTUP = {
        "capture_mode": "frozen_source_bytes_executed",
        "captured_at_utc": _datetime.now(_timezone.utc).isoformat(), "modules": _digests,
        "aggregate_sha256": _hashlib.sha256(_json.dumps(_digests, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "limitations": ["Initial bootstrap, Python interpreter, standard library and native modules are not attested.",
                        "Trusted local source snapshot; not a signed receipt or protection against host tampering.",
                        "Hashes identify frozen bytes, not later files on disk; external launcher is pinned separately."],
    }

    class _FrozenMss(_abc.MetaPathFinder, _abc.Loader):
        def find_spec(self, fullname, path=None, target=None):
            if fullname in _frozen and fullname != "mss_universal":
                return _util.spec_from_loader(fullname, self, origin=_frozen[fullname][1])
            return None

        def create_module(self, spec):
            return None

        def exec_module(self, module):
            source, filename = _frozen[module.__name__]
            module.__file__ = filename
            exec(compile(source, filename, "exec"), module.__dict__)

    _sys.meta_path.insert(0, _FrozenMss())
    exec(compile(_frozen["mss_universal"][0], _frozen["mss_universal"][1], "exec"), globals())
    raise SystemExit(0)

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
from unicodedata import category
from datetime import datetime, timezone
from threading import BoundedSemaphore, Event, RLock, Thread
from time import monotonic
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mss_profiles import Catalog, LaunchPlan, SYSTEM_KEYS, check_pin, local_directory, local_path
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
INPUT_GEOMETRY = {key: "number" for key in ("if_layout_width", "if_layout_height", "if_dpi")}
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
        "ui__key", "Send exactly one Makepad key (c) or nonempty app-local text (t) to the sole owned window. "
        "Use numeric w from status. Only c accepts k (press, down, or up) and modifiers. "
        "Shared clipboard chords are blocked. Supply all three geometry guards together.",
        INPUT_WINDOW | INPUT_GEOMETRY | MODIFIERS | {"c": "string", "t": "string", "k": "string"},
        ("w",), False,
    ),
    "mss_ui_mouse": (
        "ui__mouse", "Send move, down, up, click, scroll, or drag in window-local points. Use numeric w from status. "
        "For scroll pass dx/dy. For drag pass x1/y1 and optionally steps (1–60). "
        "Supply all three geometry guards together.",
        INPUT_WINDOW | INPUT_GEOMETRY | MODIFIERS | POINT | {
            "k": "string", "b": "integer", "dx": "number", "dy": "number",
            "x1": "number", "y1": "number", "steps": "integer"},
        ("w", "k", "x", "y"), False,
    ),
    "mss_ui_drop": (
        "ui__drop", "Drop one existing file (basename in this app's artifact directory) on its sole window. "
        "Use numeric w from status and window-local x/y. Verify the app's response independently.",
        INPUT_WINDOW | POINT | {"file": "string"}, ("w", "file", "x", "y"), False,
    ),
    "mss_resize": (
        "ui__resize", "Resize the selected owned window in layout points and verify its new pixel frame. "
        "Use numeric w from mss_status.",
        {"w": "integer", "width": "number", "height": "number"}, ("w", "width", "height"), False,
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
                 {"w": "integer", "scale": "number", "preview": "boolean"}, (), True),
    "mss_logs": ("logs__log", "Read this app's runtime log.", {"n": "integer", "since": "integer"}, (), True),
}

TOOLS = [
    tool("mss_server_info", "Read this running MSS server's immutable startup identity and frozen Python source manifest.", {}),
    tool("mss_recheck_cleanup", "Reconcile an MSS launch receipt without signalling a process. Never attaches or retries GUI actions.",
         {"app_id": "string"}, ("app_id",), read=False),
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


LEGACY_LAUNCHER_SHA256 = "5a1db3a7aa86e32067623d44f5bfb065689a6e1a6eeb7f501380e2869d0945d1"
# Reviewed migration evidence, not a general assumption about every old receipt.
REVIEWED_LEGACY_EXIT = {
    ("app_2e6acdf2e4a744029ac9e850d9a1f96f",
     "ef6327196dd47c73bd5d4cf6be4106f5736b703d64726089e6cffb1d417735d6",
     "a92ae69ba991c0e1c3863b9909de3ffcb033968b2a1a3e50b416f25293a809ce"),
}
TERMINAL_LIFECYCLE = {"CLOSED", "FAILED_CLOSED"}


def cleanup_classification(receipt, *, launcher_code=None, launcher_pid=None, legacy_known=False):
    """No signalling: distinguish a failed lifecycle from unconfirmed process exit."""
    pending = lambda reason: {"state": "CLEANUP_PENDING", "reason": reason}
    if not (type(receipt.get("app_pid")) is int and receipt["app_pid"] > 0
            and isinstance(receipt.get("app_birth_utc"), str) and receipt["app_birth_utc"]
            and type(receipt.get("app_exit_code")) is int):
        return pending("MISSING_OWNED_PROCESS_EXIT_IDENTITY")
    try:
        from mss_process import birth_ticks
        birth = birth_ticks(receipt["app_birth_utc"])
    except (ValueError, TypeError, OverflowError):
        return pending("INVALID_BIRTH_IDENTITY")
    proof = receipt.get("exit_proof")
    if isinstance(proof, dict):
        if not (proof.get("kind") == "retained_process_handle" and proof.get("exit_observed") is True
                and type(proof.get("pid")) is int and type(proof.get("birth_filetime")) is int
                and type(receipt.get("app_birth_filetime")) is int
                and proof.get("pid") == receipt["app_pid"] and proof.get("birth_filetime") == birth
                and receipt.get("app_birth_filetime") == birth
                and type(proof.get("exit_code")) is int and proof["exit_code"] == receipt["app_exit_code"]):
            return pending("RETAINED_EXIT_PROOF_MISMATCH")
        if launcher_pid is not None and receipt.get("launcher_pid") != launcher_pid:
            return pending("LAUNCHER_PROCESS_MISMATCH")
        if launcher_code is not None and receipt.get("launcher_exit_code") != launcher_code:
            return pending("LAUNCHER_EXIT_MISMATCH")
        if type(receipt.get("mcp_started")) is not bool:
            return pending("OWNED_MCP_STATE_UNCONFIRMED")
        if receipt.get("mcp_started") is True and receipt.get("mcp_exit_observed") is not True:
            return pending("OWNED_MCP_EXIT_UNCONFIRMED")
        proof_kind = "retained_process_handle_exit"
    elif (legacy_known and "exit_proof" not in receipt and "launcher_script_sha256" not in receipt
          and receipt.get("cleanup") == "GRACEFUL"):
        # The admitted legacy source writes GRACEFUL only after birth/image check
        # and WaitForExit on its retained Process.Start object. Preserve this limit.
        proof_kind = "legacy_GRACEFUL_retained_handle_branch"
    else:
        return pending("NO_BOUND_EXIT_PROOF")
    if "remote_directory" in receipt and receipt.get("remote_cleanup") != "REMOVED":
        return pending("OWNED_REMOTE_TEMP_CLEANUP_UNCONFIRMED")
    if receipt.get("status") not in {"CLOSED", "FAILED_CLOSED", "FAIL", "FAIL_APP_EXIT", "FAIL_MCP_EXIT"}:
        return pending("RECEIPT_NOT_FINAL")
    if not (type(receipt.get("launcher_exit_code")) is int and receipt.get("completed_utc")):
        return pending("FINAL_LAUNCHER_RECEIPT_MISSING")
    healthy = (receipt["status"] == "CLOSED" and receipt.get("cleanup") == "GRACEFUL"
               and bool(receipt.get("app_image"))
               and (proof_kind.startswith("legacy_") or receipt.get("startup_qualified") is True)
               and (proof_kind.startswith("legacy_") or receipt.get("app_image_verified") is True
                    and proof.get("image_verified") is True)
               and receipt["app_exit_code"] == 0 and receipt["launcher_exit_code"] == 0
               and receipt.get("mcp_exit_code") == 0 and receipt.get("log_capture") == "COMPLETE")
    return {"state": "CLOSED" if healthy else "FAILED_CLOSED", "reason": proof_kind,
            "app_pid": receipt["app_pid"], "app_birth_utc": receipt["app_birth_utc"],
            "app_exit_code": receipt["app_exit_code"], "launcher_exit_code": receipt["launcher_exit_code"],
            "app_image_observed": receipt.get("app_image"),
            "app_image_verified": receipt.get("app_image_verified", bool(receipt.get("app_image")))}


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
    if name == "mss_ui_key" and "c" in args and error == f"bad key code {args['c']}":
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
    if "if_user_seq" in args:
        require(args["if_user_seq"] >= 0, "INVALID_ARGUMENT", "Activity sequence must be nonnegative.")
    if "n" in args:
        require(1 <= args["n"] <= 500, "INVALID_ARGUMENT", "n must be 1–500.")
    if "scale" in args:
        require(0.25 <= args["scale"] <= 2, "INVALID_ARGUMENT", "scale must be 0.25–2.")
    if name == "mss_resize":
        require(args["w"] >= 0 and all(1 <= args[key] <= 16384 for key in ("width", "height")),
                "INVALID_ARGUMENT", "Use a nonnegative window ID and width/height of 1–16384 layout points.")
    if name in RAW_INPUT:
        validate_input(name, args)


def validate_input(name, args):
    require(args["w"] >= 0 and args.get("if_user_seq", 0) >= 0,
            "INVALID_ARGUMENT", "Window and activity sequence must be nonnegative.")
    geometry = INPUT_GEOMETRY.keys() & args.keys()
    require(not geometry or geometry == INPUT_GEOMETRY.keys() and all(args[key] > 0 for key in geometry),
            "INVALID_ARGUMENT", "Supply positive if_layout_width, if_layout_height and if_dpi together.")
    if name == "mss_ui_key":
        require(("c" in args) != ("t" in args), "INVALID_ARGUMENT", "Supply exactly one of c or t.")
        if "t" in args:
            require(not (args.keys() & (MODIFIERS.keys() | {"k"})),
                    "INVALID_ARGUMENT", "Text does not take a key kind or modifiers.")
            require(args["t"] and all(category(char) not in {"Cc", "Cs", "Zl", "Zp"} for char in args["t"]),
                    "INVALID_ARGUMENT", "Use nonempty text without control characters or invalid Unicode.")
            return
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
        self.terminal_receipt = None
        self.cleanup_detail = None
        self.launcher_sha256 = None
        self.launcher_start_attempted = False
        self.startup_failed = False

    def record(self):
        process = self.identity or self.terminal_receipt or {}
        return {
            "app_id": self.app_id, "profile": self.profile, "state": self.state,
            "pid": process.get("app_pid"),
            "app": self.plan.app_image.name if self.plan else None,
            "build_id": self.plan.build_id if self.plan else None,
            "app_sha256": self.plan.app_sha256 if self.plan else None,
            "app_birth_utc": process.get("app_birth_utc"),
            "artifact_dir": str(self.artifacts),
            "launcher_receipt": str(self.receipt_path) if self.receipt_path else None,
            "windows_session_id": self.os_identity["windows_session"] if self.os_identity else None,
            "cleanup_reason": self.cleanup_detail.get("reason") if self.cleanup_detail else None,
            "launcher_start_attempted": self.launcher_start_attempted,
            "startup_failed": self.startup_failed,
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
                and Path(receipt.get("app_image_expected") or receipt["app_image"]) == self.plan.app_image
                and (receipt.get("app_image") is None or Path(receipt["app_image"]) == self.plan.app_image)
                and type(receipt["app_pid"]) is int and receipt["app_pid"] > 0
                and bool(receipt["app_birth_utc"]) and bool(receipt["session_id"]),
                "IDENTITY_UNVERIFIED", "Launcher receipt does not match the admitted profile.",
            )
            require(receipt.get("status") not in {"READY", "CLOSED"} or bool(receipt.get("app_image")),
                    "IDENTITY_UNVERIFIED", "A successful lifecycle needs the observed image identity.")
            if self.launcher_sha256 and "launcher_script_sha256" in receipt:
                require(receipt["launcher_script_sha256"].lower() == self.launcher_sha256.lower(),
                        "IDENTITY_UNVERIFIED", "Launcher source binding changed.")
            if receipt.get("profile_id"):
                require(candidates[0].parent.name == receipt["profile_id"] + "-" + receipt["session_id"],
                        "IDENTITY_UNVERIFIED", "Receipt session directory changed.")
            if self.identity:
                require(all(receipt[key] == value for key, value in self.identity.items())
                        and ("remote_directory" in receipt) == ("remote_directory" in self.identity),
                        "IDENTITY_UNVERIFIED", "Owned process or Remote directory identity changed.")
            return receipt
        except (OSError, KeyError, TypeError, ValueError) as error:
            raise ToolFailure("IDENTITY_UNVERIFIED", "Owned launcher receipt is unavailable.") from error

    def start(self, catalog):
        self.launcher_sha256 = catalog.launcher_sha256
        self.directory.mkdir(parents=True, exist_ok=False)
        self.plan = self.stack.enter_context(catalog.prepare(self.profile, self.directory, self.requested_build))
        self.artifacts.mkdir()
        self.launcher_start_attempted = True
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
        if "remote_directory" in receipt:
            self.discovery_directory(receipt)
            self.identity["remote_directory"] = receipt["remote_directory"]
        self.os_identity = confirm_app(self.identity, None)
        self.state = "READY"
        write_record(self.directory / "ownership.json", self.record() | self.identity)

    def discovery_directory(self, receipt):
        """Use the immutable owned temp directory, or the documented legacy layout."""
        try:
            if "remote_directory" not in receipt:
                return local_path(self.receipt_path.parent, directory=True)
            value = receipt["remote_directory"]
            directory = local_path(value, directory=True)
            require(isinstance(value, str) and str(directory) == value
                    and directory.parent.name == "MSS-Remote"
                    and re.fullmatch(r"[a-f0-9]{32}", directory.name)
                    and directory.name == receipt["session_id"],
                    "IDENTITY_UNVERIFIED", "Launcher Remote temp directory does not match this session.")
            return directory
        except (OSError, KeyError, TypeError, ValueError) as error:
            raise ToolFailure("IDENTITY_UNVERIFIED", "Owned Remote temp directory is unavailable.") from error

    def direct_peer(self, directory):
        """A second official MCP client, bound to the owner's exact discovery directory."""
        receipt = self.receipt()
        profile_path = local_path(self.plan.cwd.parent / "profile.json")
        check_pin(profile_path, self.plan.profile_sha256)
        profile = json.loads(profile_path.read_bytes())
        remote = local_path(profile["remote_executable"])
        check_pin(remote, self.plan.remote_sha256)
        temp = self.discovery_directory(receipt)
        env = dict(self.plan.env, TEMP=str(temp), TMP=str(temp))
        try:
            discovery_file = local_path(temp / f'makepad-remote-{receipt["app_pid"]}.json')
            discovery = json.loads(discovery_file.read_bytes())
            require(isinstance(discovery, dict) and discovery.get("pid") == receipt["app_pid"]
                    and str(discovery.get("app", "")).lower() == self.plan.app_image.name.lower()
                    and re.fullmatch(r"tcp:127\.0\.0\.1:[0-9]+", discovery.get("socket", ""))
                    and re.fullmatch(r"[0-9a-f]{64}", discovery.get("token", "")),
                    "IDENTITY_UNVERIFIED", "Owned Remote discovery changed.")
        except (OSError, TypeError, ValueError):
            # Parse failures must not expose the token in error reporting.
            raise ToolFailure("IDENTITY_UNVERIFIED", "Owned Remote discovery is unavailable.") from None
        plan = replace(self.plan, command=[str(remote), "mcp", str(receipt["app_pid"])], env=env)
        peer = Peer(plan, directory / f"remote-client-{uuid4().hex}.log")
        try:
            peer.request("initialize", {"protocolVersion": VERSIONS[0], "capabilities": {},
                                       "clientInfo": {"name": "mss", "version": "1"}})
            peer.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            status = native_json(peer.call("ui__status", {}))
            require(status.get("pid") == self.identity["app_pid"]
                    and str(status.get("app", "")).lower() == self.plan.app_image.name.lower() and status.get("w"),
                    "IDENTITY_UNVERIFIED", "Attached Remote process or window changed.")
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

    def action_target(self, tool_name, args, *, allowed_press_paths=()):
        require(re.fullmatch(r"[0-9]+:[0-9]+", args["w"]) and bool(args["node"]),
                "INVALID_ARGUMENT", "Use the exact node and window from this app's tree.")
        tree = native_json(self.peer.call("ui__ui", {"node": args["node"], "w": args["w"], "json": True}))
        nodes = [node for window in tree.get("trees", []) if window.get("window") == args["w"]
                 for node in window.get("nodes", []) if node.get("id") == args["node"]]
        require(len(nodes) == 1, "UNKNOWN_NODE", "This node is absent from the selected app window.")
        if allowed_press_paths:
            require(nodes[0].get("role") == "button" and nodes[0].get("path") in allowed_press_paths,
                    "READ_ONLY_PROFILE", "This button is outside the profile's permitted semantic presses.")
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

    def preflight_user_seq(self, args, peer):
        """Read only. This observation never replaces Makepad's dispatch guard."""
        refusal = {"action_dispatched": False, "effect": "NOT_DISPATCHED"}
        if "ui__activity" not in self.native_tools:
            return result_json(refusal | {"code": "REFUSED_ACTIVITY_UNAVAILABLE"}, error=True)
        try:
            activity = native_json(peer.call("ui__activity", {}))
        except (ToolFailure, TransportFailure, AttributeError, KeyError, TypeError, ValueError, RecursionError):
            activity = None
        actual = activity.get("user_seq") if isinstance(activity, dict) else None
        if type(actual) is not int or not 0 <= actual < 2**64:
            return result_json(refusal | {"code": "REFUSED_ACTIVITY_UNAVAILABLE"}, error=True)
        if actual != args["if_user_seq"]:
            return result_json(refusal | {"code": "REFUSED_STALE_USER_SEQ",
                "expected_user_seq": args["if_user_seq"], "observed_user_seq": actual}, error=True)
        return None

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
        window = matches[0]
        if "if_dpi" in args:
            expected = [args.pop("if_layout_width"), args.pop("if_layout_height"), args.pop("if_dpi")]
            size, dpi = window.get("sz"), window.get("dpi")
            require(isinstance(size, list) and len(size) == 2
                    and all(type(value) in (int, float) for value in (*size, dpi))
                    and [*size, dpi] == expected,
                    "STALE_GEOMETRY", "The selected app window geometry changed before input dispatch.")
        if name == "mss_ui_key":
            return
        width, height = window["sz"]
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

    def resize_status(self, peer, window_id):
        status = native_json(peer.call("ui__status", {}))
        require(isinstance(status, dict) and type(status.get("pid")) is int
                and status["pid"] == self.identity["app_pid"],
                "IDENTITY_UNVERIFIED", "Makepad returned a different process identity.")
        windows = status.get("w")
        require(isinstance(windows, list), "RESIZE_STATUS_UNVERIFIED", "Window status is unavailable.")
        matches = [window for window in windows if isinstance(window, dict)
                   and type(window.get("i")) is int and window["i"] == window_id]
        require(len(matches) == 1, "UNKNOWN_WINDOW", "Use a window ID from this app's current status.")
        window = matches[0]
        size, pixels, dpi = (window.get(key) for key in ("sz", "px", "dpi"))
        require(isinstance(size, list) and len(size) == 2
                and all(type(value) in (int, float) and 0 < value <= 2**31 for value in size)
                and isinstance(pixels, list) and len(pixels) == 2
                and all(type(value) is int and 0 < value <= 2**31 for value in pixels)
                and type(dpi) in (int, float) and 0 < dpi <= 2**31,
                "RESIZE_STATUS_UNVERIFIED", "Makepad window geometry is incomplete.")
        return status, window

    def resize(self, args, peer):
        require(self.plan.access == "semantic", "READ_ONLY_PROFILE", "This profile permits inspection only.")
        require({"ui__status", "ui__grab"} <= self.native_tools,
                "UNSUPPORTED", "The admitted Makepad server lacks resize verification tools.")
        try:
            output = local_path(self.artifacts, directory=True) / f"{uuid4().hex}.png"
        except (OSError, ValueError) as error:
            raise ToolFailure("CAPTURE_UNVERIFIED", "The owned artifact directory is unavailable.") from error

        requested = [args["width"], args["height"]]
        window_id = args["w"]
        dispatched = False
        acknowledgement = None

        def geometry_matches(window):
            # Windows rounds to a physical pixel, and Remote reports points to three decimals.
            tolerance = 0.5 / window["dpi"] + 0.001
            return all(abs(actual - wanted) <= tolerance for actual, wanted in zip(window["sz"], requested))

        try:
            status, window = self.resize_status(peer, window_id)
            if not geometry_matches(window):
                dispatched = True
                self.build_postcondition = None
                acknowledgement = native_json(peer.call(
                    "ui__resize", {"w": requested[0], "h": requested[1], "window": window_id}))
                require(isinstance(acknowledgement, dict) and acknowledgement.get("resize") == requested,
                        "RESIZE_ACK_UNVERIFIED", "Makepad did not acknowledge the requested layout size.")
                status, window = self.resize_status(peer, window_id)
                require(geometry_matches(window), "RESIZE_GEOMETRY_MISMATCH",
                        "The observed layout size differs from the request.")
            frame = peer.call("ui__grab", {"w": window_id, "scale": 1, "out": str(output)})
            metadata = native_json(frame)
            require(isinstance(metadata, dict) and type(metadata.get("w")) is int and metadata["w"] == window_id
                    and metadata.get("sz") == window["px"],
                    "CAPTURE_UNVERIFIED", "The pixel frame disagrees with the verified window geometry.")
            digest = self.capture(frame, output)
            self.ensure_ready()
        except (ToolFailure, TransportFailure, OSError, TypeError, ValueError) as error:
            if dispatched or isinstance(error, TransportFailure):
                reason = error.code if isinstance(error, ToolFailure) else type(error).__name__
                self.state = "OUTCOME_UNKNOWN" if dispatched else "TRANSPORT_LOST"
                try:
                    write_record(self.directory / "channel-state.json", self.record() | {"reason": reason})
                except OSError:
                    print("[mss] Unable to save the resize channel state.", file=sys.stderr)
                raise ToolFailure(self.state, f"Resize verification failed ({reason}).") from error
            if isinstance(error, ToolFailure):
                raise
            raise ToolFailure("CAPTURE_UNVERIFIED", "The owned pixel frame could not be verified.") from error

        return result_json({
            "code": "RESIZED" if dispatched else "UNCHANGED", "effect": "VERIFIED",
            "app_id": self.app_id, "w": window_id, "layout_size": window["sz"], "dpi": window["dpi"],
            "png": str(output), "sz": metadata["sz"], "sha256": digest, "capture_kind": "pixels",
            "native_ack": acknowledgement, "status": status,
        })

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
        if name == "mss_resize":
            return self.resize(args, peer or self.peer)
        raw_input = name in RAW_INPUT
        preview = name == "mss_grab" and args.pop("preview", False)
        mutating_dispatch = False
        try:
            if not read:
                allowed_press_paths = ()
                if self.plan.access != "semantic":
                    allowed_press_paths = getattr(self.plan, "allowed_press_paths", ())
                    require(allowed_press_paths and name == "mss_ui_act" and args.get("action") == "press"
                            and args.keys() <= (TARGET.keys() | {"action", "wait"}),
                            "READ_ONLY_PROFILE", "This profile does not permit the requested mutation.")
                if raw_input:
                    self.input_target(name, args)
                else:
                    self.action_target(name, args, allowed_press_paths=allowed_press_paths)
                    args.setdefault("json", True)
                if "if_user_seq" in args:
                    refusal = self.preflight_user_seq(args, peer or self.peer)
                    if refusal is not None:
                        return refusal
            if name == "mss_ui_type":
                args.update(action="replace_text", wait=True)
            if name == "mss_ui_tree":
                args.setdefault("json", True)
            if name == "mss_ui_wait":
                args.setdefault("timeout_ms", 5000)
                if "count" in args or args.get("gone") is True or args.get("changed") is True:
                    self.build_postcondition = None
            if name == "mss_grab":
                if preview:
                    require(self.plan.access == "read-only" or (self.participant and self.plan.access == "semantic"),
                            "PREVIEW_UNAVAILABLE", "Preview requires an owned read-only profile or an admitted attachment.")
                    require(args.get("w", -1) >= 0, "INVALID_ARGUMENT", "Use the owned window ID.")
                    directory = local_path(self.artifacts, directory=True)
                    output = directory / "preview.png"
                    for path in (output, output.with_suffix(".json")):
                        if path.exists() or path.is_symlink():
                            require(local_path(path).parent == directory and path.stat().st_nlink == 1,
                                    "CAPTURE_UNVERIFIED", "Preview path must be an owned, unlinked file.")
                else:
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
            if preview:
                metadata = native_json(result)
                require(metadata.get("w") == args["w"], "CAPTURE_UNVERIFIED",
                        "Makepad returned a different window for the preview.")
            digest = self.capture(result, output)
            if preview:
                return result_json(metadata | {"app_id": self.app_id, "pid": self.identity["app_pid"],
                                               "sha256": digest})
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
        if self.cleanup_started and self.state in TERMINAL_LIFECYCLE:
            return self.record()
        require(not self.cleanup_started, "CLEANUP_PENDING", "Cleanup was already requested.")
        self.cleanup_started = True
        self.state = "CLOSING"
        code = None
        detail = {"state": "CLEANUP_PENDING", "reason": "LAUNCHER_EXIT_UNCONFIRMED"}
        try:
            if self.read_peer:
                self.read_peer.close()
            code = self.peer.close() if self.peer else None
            if self.peer is None and not self.launcher_start_attempted:
                detail = {"state": "FAILED_CLOSED", "reason": "NO_LAUNCHER_START_ATTEMPT"}
            if self.peer:
                receipt = self.receipt()
                self.terminal_receipt = receipt
                detail = cleanup_classification(receipt, launcher_code=code,
                    launcher_pid=getattr(self.peer.process, "pid", None),
                    legacy_known=self.launcher_sha256 is not None and self.launcher_sha256.lower() == LEGACY_LAUNCHER_SHA256)
                if detail["state"] == "CLOSED" and self.startup_failed:
                    detail.update(state="FAILED_CLOSED", reason="ROUTER_STARTUP_FAILED_PROCESS_CLOSED")
        except Exception as error:
            detail = {"state": "CLEANUP_PENDING", "reason": getattr(error, "code", type(error).__name__)}
        try:
            self.stack.close()
        except Exception as error:
            detail = {"state": "CLEANUP_PENDING", "reason": "RESOURCE_RELEASE_UNCONFIRMED"}
        self.cleanup_detail = detail
        self.state = detail["state"]
        if self.directory.is_dir():
            write_record(self.directory / "closure.json", self.record() | {"launcher_exit_code": code})
        if self.state == "CLEANUP_PENDING":
            raise ToolFailure("CLEANUP_PENDING", f"Cleanup is unresolved: {detail['reason']}. See the owned session directory.")
        return self.record()

    def reconcile_cleanup(self):
        """Only receipt/retained launcher observation; never send quit or repeat close."""
        with self.read_lock:
            if self.state in TERMINAL_LIFECYCLE:
                return self.record()
            require(self.state != "READY", "APP_RUNNING", "A ready app is not a cleanup record.")
            try:
                receipt = self.receipt()
                code = self.peer.process.poll() if self.peer else None
                detail = cleanup_classification(receipt, launcher_code=code,
                    launcher_pid=getattr(self.peer.process, "pid", None) if self.peer else None,
                    legacy_known=self.launcher_sha256 is not None and self.launcher_sha256.lower() == LEGACY_LAUNCHER_SHA256)
                if code is None:
                    detail = {"state": "CLEANUP_PENDING", "reason": "LAUNCHER_EXIT_UNCONFIRMED"}
                if detail["state"] == "CLOSED" and self.startup_failed:
                    detail.update(state="FAILED_CLOSED", reason="ROUTER_STARTUP_FAILED_PROCESS_CLOSED")
                if self.cleanup_detail and self.cleanup_detail.get("reason") == "RESOURCE_RELEASE_UNCONFIRMED":
                    detail = {"state": "CLEANUP_PENDING", "reason": "RESOURCE_RELEASE_UNCONFIRMED"}
                self.terminal_receipt = receipt
            except (ToolFailure, OSError, ValueError) as error:
                detail = {"state": "CLEANUP_PENDING", "reason": getattr(error, "code", type(error).__name__)}
            self.state, self.cleanup_detail = detail["state"], detail
            write_record(self.directory / ("cleanup-recheck-" + uuid4().hex + ".json"), self.record() | detail)
            return self.record()


class Router:
    def __init__(self, repo):
        self.catalog = Catalog(repo, Path(sys.executable), data_root=os.environ.get("MSS_DATA_ROOT"))
        self.root = self.data_root / "proof" / "mss-universal" / "connections" / uuid4().hex
        self.apps = {}
        self.closed_apps = {}
        self.initialized = False
        self.mcp_protocol_version = None
        self.shared = None
        self.apps_lock = RLock()
        self.stopping = False
        process = process_identity(os.getpid())
        seconds, fraction = divmod(process["birth"] - 116444736000000000, 10_000_000)
        started = datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + f".{fraction:07d}Z"
        snapshot = globals().get("_MSS_FROZEN_STARTUP")
        if snapshot is None:
            snapshot = {"capture_mode": "imported_test_context_NOT_ATTESTED", "modules": {},
                        "aggregate_sha256": None, "limitations": ["Use the actual stdio entry point for a frozen source identity."]}
        commit = None
        if (repo / ".git").exists():
            try:
                found = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, timeout=2,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                candidate = found.stdout.decode("ascii").strip()
                if found.returncode == 0 and re.fullmatch(r"[a-f0-9]{40,64}", candidate):
                    commit = candidate
            except (OSError, ValueError, subprocess.TimeoutExpired):
                pass
        self.runtime_info = {
            "server_pid": os.getpid(), "server_started_utc": started, "connection_id": self.root.name,
            "mss_version": "0.1.0-preview.1", "mss_commit": commit, "commit_is_runtime_revision": False,
            "source_manifest": snapshot,
        }

    @property
    def data_root(self):
        return getattr(self.catalog, "data_root", self.catalog.repo)

    def begin_shutdown(self):
        self.stopping = True
        if self.shared is not None:
            self.shared.cancel_pending()

    def recheck_cleanup(self, app_id):
        require(re.fullmatch(r"app_[a-f0-9]{32}", app_id) is not None,
                "INVALID_ARGUMENT", "Use an exact MSS-generated App ID.")
        completed = self.closed_apps.get(app_id)
        if completed and completed.get("state") in TERMINAL_LIFECYCLE:
            return completed | {"already_reconciled": True}
        app = self.apps.get(app_id)
        if app is not None:
            record = app.reconcile_cleanup()
            if record["state"] in TERMINAL_LIFECYCLE:
                self.closed_apps[app_id] = record
                self.apps.pop(app_id, None)
                if self.shared is not None:
                    try:
                        self.shared.update_state(app_id, "CLOSED")
                    except SharedError as error:
                        if error.code != "UNKNOWN_APP":
                            raise
            return record
        try:
            base = local_path(self.data_root / "proof/mss-universal/connections", directory=True)
        except FileNotFoundError as error:
            raise ToolFailure("UNKNOWN_APP", "No recorded MSS launch; no process was targeted.") from error
        candidates = [p for p in base.glob("*/" + app_id) if p.is_dir()]
        require(len(candidates) == 1, "UNKNOWN_APP", "Expected one recorded MSS launch; no process was targeted.")
        directory = local_path(candidates[0], directory=True)
        files = {}
        for name in ("profile.json", "closure.json", "launch-failure.json"):
            path = directory / name
            if path.exists():
                path = local_path(path)
                files[name] = path.read_bytes()
        require("profile.json" in files and any(name in files for name in ("closure.json", "launch-failure.json")),
                "OWNERSHIP_UNVERIFIED", "No MSS launch/closure evidence. No process was targeted.")
        metadata = json.loads(files.get("launch-failure.json", files.get("closure.json")))
        require(metadata.get("app_id") == app_id and metadata.get("state") in {"CLEANUP_PENDING", "FAILED_CLOSED", "CLOSED"},
                "OWNERSHIP_UNVERIFIED", "The record is not an MSS cleanup failure.")
        profile = json.loads(files["profile.json"])
        require(Path(profile["working_directory"]).parent == directory
                and Path(profile["session_root"]) == directory / "sessions"
                and profile.get("admission") == "TRUSTED_DEVELOPMENT",
                "OWNERSHIP_UNVERIFIED", "Materialized profile is outside this recorded MSS launch.")
        receipts = list((directory / "sessions").glob("*/session.json"))
        require(len(receipts) == 1, "OWNERSHIP_UNVERIFIED", "Expected one launch receipt.")
        receipt_path = local_path(receipts[0])
        files[str(receipt_path.relative_to(directory))] = receipt_path.read_bytes()
        receipt = json.loads(files[str(receipt_path.relative_to(directory))])
        require(receipt["profile_sha256"].lower() == hashlib.sha256(files["profile.json"]).hexdigest()
                and receipt["app_sha256"].lower() == profile["app_sha256"].lower()
                and receipt["remote_sha256"].lower() == profile["remote_sha256"].lower()
                and receipt["makepad_revision_declared"] == profile["makepad_revision"]
                and receipt.get("profile_id") == profile["id"]
                and receipt_path.parent.name == profile["id"] + "-" + receipt["session_id"]
                and re.fullmatch(r"[a-f0-9]{32}", receipt["session_id"]) is not None,
                "OWNERSHIP_UNVERIFIED", "Profile, receipt and launch session do not agree.")
        for field, value in (("pid", receipt.get("app_pid")), ("app_birth_utc", receipt.get("app_birth_utc"))):
            require(metadata.get(field) in (None, value), "OWNERSHIP_UNVERIFIED", "Archived process binding conflicts.")
        expected_image = profile["app_executable"]
        require(receipt.get("app_image_expected", receipt.get("app_image", expected_image)) == expected_image
                and receipt.get("app_image") in (None, expected_image),
                "OWNERSHIP_UNVERIFIED", "Archived executable binding conflicts.")
        evidence = {name: hashlib.sha256(value).hexdigest() for name, value in files.items()}
        latest_path = directory / "cleanup-reconciliation.json"
        legacy_path = self.catalog.repo / "proof/mss-cleanup-remediation/source-before/MSS_MCP/tools/Start-MakepadMcp.ps1"
        reviewed = (app_id, hashlib.sha256(files[str(receipt_path.relative_to(directory))]).hexdigest(),
                    hashlib.sha256(files["profile.json"]).hexdigest()) in REVIEWED_LEGACY_EXIT
        legacy_known = reviewed and legacy_path.is_file() and hashlib.sha256(local_path(legacy_path).read_bytes()).hexdigest() == LEGACY_LAUNCHER_SHA256
        detail = cleanup_classification(receipt, legacy_known=legacy_known)
        if not legacy_known and "exit_proof" not in receipt and receipt.get("cleanup") == "GRACEFUL":
            detail = {"state": "CLEANUP_PENDING", "reason": "LEGACY_LAUNCHER_PROVENANCE_NOT_VERIFIED"}
        if detail["state"] == "CLOSED" and metadata.get("startup_failed") is True:
            detail.update(state="FAILED_CLOSED", reason="ROUTER_STARTUP_FAILED_PROCESS_CLOSED")
        if latest_path.exists():
            previous = json.loads(local_path(latest_path).read_bytes())
            if (detail["state"] in TERMINAL_LIFECYCLE and previous.get("state") == detail["state"]
                    and previous.get("source_evidence") == evidence):
                self.closed_apps[app_id] = previous
                return previous | {"already_reconciled": True}
        observation = {"kind": "NOT_QUERIED", "no_process_action": True}
        if detail["state"] in TERMINAL_LIFECYCLE:
            try:
                from mss_process import birth_ticks
                current = process_identity(receipt["app_pid"])
                if current["birth"] == birth_ticks(receipt["app_birth_utc"]):
                    observation["kind"] = "ORIGINAL_PROCESS_STILL_LIVE"
                    detail = {"state": "CLEANUP_PENDING", "reason": "EXIT_RECEIPT_CONTRADICTS_LIVE_ORIGINAL"}
                else:
                    observation["kind"] = "PID_REUSED_NO_AUTHORITY_OVER_REPLACEMENT"
            except OSError as error:
                if error.errno == 87:  # ERROR_INVALID_PARAMETER: PID absent; receipt still supplies the exit proof.
                    observation["kind"] = "PID_ABSENT_BOUND_EXIT_RECEIPT_REQUIRED"
                else:
                    observation.update(kind="QUERY_UNAVAILABLE", error_code=error.errno)
                    detail = {"state": "CLEANUP_PENDING", "reason": "CURRENT_IDENTITY_QUERY_UNAVAILABLE"}
        record = {"app_id": app_id, "profile": metadata.get("profile"), **detail,
                  "pid": receipt.get("app_pid"), "app_birth_utc": receipt.get("app_birth_utc"),
                  "app_image_expected": expected_image, "app_sha256": receipt["app_sha256"],
                  "launcher_receipt": str(receipt_path), "source_evidence": evidence,
                  "legacy_source_sha256": LEGACY_LAUNCHER_SHA256 if legacy_known else None,
                  "observation": observation, "reviewed_utc": datetime.now(timezone.utc).isoformat(),
                  "evidence_trust": "Trusted local MSS receipt files, not a cryptographically signed OS attestation."}
        # Append immutable review evidence; preserve the original receipt/closure/failure.
        review_path = directory / ("cleanup-reconciliation-" + uuid4().hex + ".json")
        with review_path.open("xb") as stream:
            stream.write(json_bytes(record))
        if latest_path.exists():
            archive = directory / ("cleanup-reconciliation-prior-" + uuid4().hex + ".json")
            with archive.open("xb") as stream:
                stream.write(local_path(latest_path).read_bytes())
        temporary = directory / ("cleanup-reconciliation-" + uuid4().hex + ".tmp")
        with temporary.open("xb") as stream:
            stream.write(json_bytes(record))
        os.replace(temporary, latest_path)
        if record["state"] in TERMINAL_LIFECYCLE:
            self.closed_apps[app_id] = record
        return record

    def store(self):
        with self.apps_lock:
            if self.shared is None:
                base = local_directory(self.data_root / "MSS_MCP/profiles/local.shared", create=True)
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
        record = {key: value for key, value in app.record().items()
                  if key not in {"cleanup_reason", "launcher_start_attempted", "startup_failed"}}
        self.store().publish(app.app_id, record | {
            "directory": str(app.directory), "os_identity": app.os_identity,
            "identity": app.identity, "native_tools": sorted(app.native_tools),
        })

    def attach(self, app_id):
        require(app_id not in self.apps, "ALREADY_ATTACHED", "This connection already holds the app.")
        store = self.store()
        store.attach(app_id)
        try:
            row = store.app(app_id)
            base = local_path(self.data_root / "proof/mss-universal/connections", directory=True)
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
            env["PATH"] = os.pathsep.join(map(str, (windows / "System32", windows)))
            app.plan = LaunchPlan([], Path(profile["working_directory"]), env, Path(profile["session_root"]),
                                  Path(profile["app_executable"]), receipt["app_sha256"], receipt["remote_sha256"],
                                  receipt["makepad_revision_declared"], receipt["profile_sha256"],
                                  self.catalog.entries[row["profile"]]["access"], row.get("build_id"),
                                  allowed_press_paths=self.catalog.press_paths(row["profile"], receipt["app_sha256"]))
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
        return local_directory(self.root, create=True) / app_id

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
            details = result.get("structuredContent", {})
            if result.get("isError"):
                state = "OUTCOME_UNKNOWN" if details.get("code") == "OUTCOME_UNKNOWN" else "FAILED"
            else:
                state = "APPLIED"
            effect = ("VERIFIED" if name == "mss_resize" and state == "APPLIED" and details.get("effect") == "VERIFIED"
                      else "NOT_VERIFIED")
            op = store.finish(op["operation_id"], state, code=details.get("code"), effect=effect)
            try:
                data = native_json(result) if not result.get("isError") else details
            except ToolFailure:
                data = {"effect": "NOT_VERIFIED"}
            return result_json(data | {"operation_id": op["operation_id"], "operation_state": op["state"],
                                       "operation_sequence": op["sequence"], "effect": effect},
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
        if name == "mss_server_info":
            return result_json(json.loads(json.dumps(self.runtime_info)) | {
                "mcp_protocol_version": self.mcp_protocol_version,
                "mcp_supported_protocol_versions": list(VERSIONS),
                "mcp_server_version": "1.0.0",
            })
        if name == "mss_recheck_cleanup":
            return result_json(self.recheck_cleanup(args["app_id"]))
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
                if args["app_id"] in getattr(self, "closed_apps", {}):
                    return result_json({"apps": [self.closed_apps[args["app_id"]]]})
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
            if "app_id" not in args:
                records.extend(record for record in getattr(self, "closed_apps", {}).values()
                               if "profile" not in args or args["profile"] == record.get("profile"))
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
                app.startup_failed = True
                try:
                    app.close()
                    if app.state == "FAILED_CLOSED":
                        self.closed_apps[app_id] = app.record()
                    self.apps.pop(app_id)
                except ToolFailure:
                    pass
                if app.directory.is_dir():
                    write_record(app.directory / "launch-failure.json", app.record() | {
                        "error_type": type(error).__name__, "error_code": getattr(error, "code", None),
                    })
                if isinstance(error, BuildError):
                    raise
                return result_json({"code": "LAUNCH_FAILED", "message": "Launch did not qualify; no GUI action was retried.",
                                    **app.record()}, error=True)
            return result_json(app.record())
        completed = getattr(self, "closed_apps", {}).get(args["app_id"])
        if completed and name in {"mss_close_app", "mss_status"}:
            return result_json(completed | {"already_closed": True, "w": []})
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
                self.shared.update_state(app.app_id, "CLOSED" if closed["state"] == "FAILED_CLOSED" else closed["state"])
                if closed["state"] == "FAILED_CLOSED":
                    self.closed_apps[app.app_id] = closed
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
            self.mcp_protocol_version = version if version in VERSIONS else VERSIONS[0]
            self.initialized = True
            return response | {"result": {
                "protocolVersion": self.mcp_protocol_version,
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
                if app.state not in TERMINAL_LIFECYCLE:
                    try:
                        app.reconcile_cleanup()
                    except (ToolFailure, OSError):
                        pass
                ok &= app.state in TERMINAL_LIFECYCLE
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
