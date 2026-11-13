"""Bounded same-user coordination for existing local MSS stdio connections.

This registry is coordination between trusted local clients, not an OS sandbox.
It stores no Remote credentials, command arguments, clipboard data or document text.
Native commands continue to use the existing Makepad Remote client.
"""

from contextlib import contextmanager
import json
from pathlib import Path
import re
import sqlite3
from time import monotonic, sleep, time
from uuid import uuid4


TERMINAL = {"APPLIED", "FAILED", "CANCELLED", "OUTCOME_UNKNOWN"}
MUTATIONS = {
    "mss_ui_act", "mss_ui_type", "mss_ui_key", "mss_ui_mouse",
    "mss_ui_drop", "mss_resize", "mss_transfer_fragment",
    "mss_close_app",
    "mss_activate_build",
}


class SharedError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def require(condition, code, message):
    if not condition:
        raise SharedError(code, message)


class Store:
    """Short SQLite transactions; waiting never retains a database write lock."""

    def __init__(self, path, connection_id, identity, is_live, queue_limit=8):
        require(isinstance(connection_id, str) and 1 <= len(connection_id) <= 128,
                "INVALID_ARGUMENT", "Invalid connection identity.")
        require(isinstance(identity, dict) and all(type(identity.get(k)) is int for k in
                ("pid", "birth", "windows_session")) and identity["pid"] > 0 and identity["birth"] > 0
                and identity["windows_session"] >= 0, "IDENTITY_UNVERIFIED", "Missing process identity.")
        require(type(queue_limit) is int and 1 <= queue_limit <= 64,
                "INVALID_ARGUMENT", "Invalid pending queue limit.")
        self.path = Path(path)
        self.connection_id = connection_id
        self.identity = dict(identity)
        self.is_live = is_live
        self.queue_limit = queue_limit
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS connections (
                    connection_id TEXT PRIMARY KEY, identity TEXT NOT NULL,
                    active INTEGER NOT NULL, created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS apps (
                    app_id TEXT PRIMARY KEY, owner TEXT NOT NULL, record TEXT NOT NULL,
                    mode TEXT NOT NULL, state TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS participants (
                    app_id TEXT NOT NULL, connection_id TEXT NOT NULL, mode TEXT NOT NULL,
                    PRIMARY KEY(app_id, connection_id));
                CREATE TABLE IF NOT EXISTS operations (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, operation_id TEXT UNIQUE NOT NULL,
                    app_id TEXT NOT NULL, connection_id TEXT NOT NULL, tool TEXT NOT NULL,
                    state TEXT NOT NULL, queued_at REAL NOT NULL, deadline REAL NOT NULL,
                    started_at REAL, completed_at REAL, code TEXT, effect TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS operation_app_order ON operations(app_id, sequence);
                CREATE TABLE IF NOT EXISTS meta_clockversion (version TEXT PRIMARY KEY);
            """)
            db.execute("BEGIN IMMEDIATE")
            clock_versions = [row["version"] for row in db.execute("SELECT version FROM meta_clockversion")]
            require(clock_versions in ([], ["monotonic-v1"]),
                    "CLOCK_VERSION_MISMATCH", "The coordination deadline version is unsupported.")
            if not clock_versions:
                # Old queued tickets used UTC epoch deadlines. Never reinterpret them
                # as monotonic deadlines and accidentally dispatch expired work.
                db.execute("UPDATE operations SET state='CANCELLED',completed_at=?,code='DEADLINE_CLOCK_MIGRATED' "
                           "WHERE state='QUEUED'", (time(),))
                db.execute("INSERT INTO meta_clockversion VALUES('monotonic-v1')")
            encoded = json.dumps(self.identity, sort_keys=True, separators=(",", ":"))
            previous = db.execute("SELECT identity,active FROM connections WHERE connection_id=?",
                                  (connection_id,)).fetchone()
            require(previous is None or (previous["identity"] == encoded and previous["active"]),
                    "CONNECTION_CONFLICT", "Connection identity cannot be reused.")
            db.execute("INSERT OR IGNORE INTO connections VALUES(?,?,1,?)", (connection_id, encoded, time()))

    @contextmanager
    def _transaction(self):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA busy_timeout=5000")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _connection_live(self, db, connection_id):
        row = db.execute("SELECT identity,active FROM connections WHERE connection_id=?", (connection_id,)).fetchone()
        if row is None or not row["active"]:
            return False
        try:
            return bool(self.is_live(json.loads(row["identity"])))
        except Exception:
            return False

    def _current(self, db):
        require(self._connection_live(db, self.connection_id), "CONNECTION_CLOSED", "Connection is unavailable.")

    def _row(self, db, app_id):
        row = db.execute("SELECT * FROM apps WHERE app_id=?", (app_id,)).fetchone()
        require(row is not None, "UNKNOWN_APP", "Unknown managed app ID.")
        return row

    def _record(self, row):
        return json.loads(row["record"]) | {
            "app_id": row["app_id"], "owner_connection_id": row["owner"],
            "share_mode": row["mode"], "state": row["state"],
        }

    def _authorize(self, db, app_id, control=False, owner=False):
        self._current(db)
        row = self._row(db, app_id)
        if row["owner"] == self.connection_id:
            mode = "owner"
        else:
            member = db.execute("SELECT mode FROM participants WHERE app_id=? AND connection_id=?",
                                (app_id, self.connection_id)).fetchone()
            require(member is not None, "NOT_ATTACHED", "Attach through an owner-enabled share first.")
            mode = member["mode"]
        require(not owner or mode == "owner", "OWNER_REQUIRED", "Only the process owner may perform this operation.")
        require(not control or mode in {"owner", "control"}, "CONTROL_REQUIRED", "Shared control was not granted.")
        return row, mode

    def _cancel_queued(self, db, where, params, code):
        db.execute("UPDATE operations SET state='CANCELLED',completed_at=?,code=? "
                   "WHERE state='QUEUED' AND " + where, (time(), code, *params))

    def _sweep(self, db, app_id):
        row = self._row(db, app_id)
        now = time()
        if not self._connection_live(db, row["owner"]) and row["state"] != "CLOSED":
            db.execute("UPDATE apps SET state='OWNER_LOST' WHERE app_id=?", (app_id,))
        active = db.execute("SELECT * FROM operations WHERE app_id=? AND state IN ('QUEUED','RUNNING')",
                            (app_id,)).fetchall()
        for op in active:
            live = self._connection_live(db, op["connection_id"])
            if op["state"] == "RUNNING" and not live:
                db.execute("UPDATE operations SET state='OUTCOME_UNKNOWN',completed_at=?,code='CALLER_LOST' "
                           "WHERE operation_id=?", (now, op["operation_id"]))
                if row["state"] != "CLOSED":
                    db.execute("UPDATE apps SET state='OUTCOME_UNKNOWN' WHERE app_id=?", (app_id,))
            elif op["state"] == "QUEUED" and (not live or monotonic() >= op["deadline"]):
                db.execute("UPDATE operations SET state='CANCELLED',completed_at=?,code=? WHERE operation_id=?",
                           (now, "DEADLINE_EXPIRED" if live else "CALLER_LOST", op["operation_id"]))
        state = self._row(db, app_id)["state"]
        if state != "READY":
            if state in {"OUTCOME_UNKNOWN", "TRANSPORT_LOST"} and self._connection_live(db, row["owner"]):
                self._cancel_queued(db, "app_id=? AND tool<>'mss_close_app'", (app_id,), state)
            else:
                self._cancel_queued(db, "app_id=?", (app_id,), state)
        self._prune(db, app_id)

    def _prune(self, db, app_id):
        db.execute("DELETE FROM operations WHERE app_id=? AND state IN "
                   "('APPLIED','FAILED','CANCELLED','OUTCOME_UNKNOWN') AND sequence NOT IN "
                   "(SELECT sequence FROM operations WHERE app_id=? AND state IN "
                   "('APPLIED','FAILED','CANCELLED','OUTCOME_UNKNOWN') ORDER BY sequence DESC LIMIT 128)",
                   (app_id, app_id))

    def publish(self, app_id, record):
        require(isinstance(app_id, str) and re.fullmatch(r"app_[a-zA-Z0-9_-]{1,128}", app_id),
                "INVALID_ARGUMENT", "Invalid managed app ID.")
        require(isinstance(record, dict), "INVALID_ARGUMENT", "Expected an app record.")
        # Only admitted metadata fields can enter the shared coordination database.
        allowed = {"app_id", "profile", "state", "pid", "app", "build_id", "app_sha256",
                   "app_birth_utc", "artifact_dir", "launcher_receipt", "directory", "windows_session",
                   "app_image", "app_birth", "remote_sha256", "makepad_revision", "windows_session_id",
                   "os_identity", "identity", "native_tools"}
        require(set(record) <= allowed, "INVALID_ARGUMENT", "Only process metadata may be published.")
        encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        with self._transaction() as db:
            self._current(db)
            require(db.execute("SELECT 1 FROM apps WHERE app_id=?", (app_id,)).fetchone() is None,
                    "APP_EXISTS", "An app ID cannot be republished or taken over.")
            db.execute("INSERT INTO apps VALUES(?,?,?,'private',?)",
                       (app_id, self.connection_id, encoded, record.get("state", "READY")))
            return self._record(self._row(db, app_id))

    def app(self, app_id):
        with self._transaction() as db:
            self._current(db)
            self._sweep(db, app_id)
            return self._record(self._row(db, app_id))

    def list_instances(self):
        with self._transaction() as db:
            self._current(db)
            for row in db.execute("SELECT app_id FROM apps").fetchall():
                self._sweep(db, row["app_id"])
            return [self._record(row) for row in db.execute("SELECT * FROM apps ORDER BY app_id")]

    def share(self, app_id, mode):
        require(mode in {"read", "control", "private"}, "INVALID_ARGUMENT", "Share mode must be read, control or private.")
        with self._transaction() as db:
            self._authorize(db, app_id, owner=True)
            self._sweep(db, app_id)
            require(self._row(db, app_id)["state"] == "READY", "APP_UNAVAILABLE", "Only a live ready app can be shared.")
            db.execute("UPDATE apps SET mode=? WHERE app_id=?", (mode, app_id))
            if mode == "private":
                db.execute("DELETE FROM participants WHERE app_id=?", (app_id,))
                self._cancel_queued(db, "app_id=? AND connection_id<>?", (app_id, self.connection_id), "SHARE_REVOKED")
            else:
                db.execute("UPDATE participants SET mode=? WHERE app_id=?", (mode, app_id))
                if mode == "read":
                    self._cancel_queued(db, "app_id=? AND connection_id<>?", (app_id, self.connection_id), "CONTROL_REVOKED")
            return self._record(self._row(db, app_id))

    def attach(self, app_id):
        with self._transaction() as db:
            self._current(db)
            row = self._row(db, app_id)
            require(row["owner"] != self.connection_id, "ALREADY_OWNER", "The owner does not need to attach.")
            require(row["mode"] in {"read", "control"}, "SHARE_DISABLED", "The owner has not shared this app.")
            owner = db.execute("SELECT identity FROM connections WHERE connection_id=?", (row["owner"],)).fetchone()
            require(owner is not None and json.loads(owner["identity"])["windows_session"] == self.identity["windows_session"],
                    "SESSION_MISMATCH", "Shared attachment requires the same Windows session.")
            self._sweep(db, app_id)
            require(self._row(db, app_id)["state"] == "READY", "APP_UNAVAILABLE", "The app owner or channel is unavailable.")
            db.execute("INSERT INTO participants VALUES(?,?,?) ON CONFLICT(app_id,connection_id) DO UPDATE SET mode=excluded.mode",
                       (app_id, self.connection_id, row["mode"]))
            return {"app_id": app_id, "connection_id": self.connection_id, "mode": row["mode"]}

    def detach(self, app_id):
        with self._transaction() as db:
            row, _ = self._authorize(db, app_id)
            require(row["owner"] != self.connection_id, "OWNER_CANNOT_DETACH", "The process owner must close its own app.")
            db.execute("DELETE FROM participants WHERE app_id=? AND connection_id=?", (app_id, self.connection_id))
            self._cancel_queued(db, "app_id=? AND connection_id=?", (app_id, self.connection_id), "DETACHED")
            return {"app_id": app_id, "connection_id": self.connection_id, "state": "DETACHED"}

    def participants(self, app_id):
        with self._transaction() as db:
            row, _ = self._authorize(db, app_id)
            members = [{"connection_id": row["owner"], "mode": "owner", "owner": True,
                        "live": self._connection_live(db, row["owner"])}]
            members.extend({"connection_id": part["connection_id"], "mode": part["mode"], "owner": False,
                            "live": self._connection_live(db, part["connection_id"])}
                           for part in db.execute("SELECT * FROM participants WHERE app_id=? ORDER BY connection_id", (app_id,)))
            return {"app_id": app_id, "owner_connection_id": row["owner"], "share_mode": row["mode"], "participants": members}

    def permission(self, app_id, control=False, owner=False):
        with self._transaction() as db:
            _, mode = self._authorize(db, app_id, control=control, owner=owner)
            self._sweep(db, app_id)
            row = self._row(db, app_id)
            if control:
                require(row["state"] == "READY", row["state"] if row["state"] == "OUTCOME_UNKNOWN" else "APP_UNAVAILABLE",
                        "The managed app is not ready for mutations.")
            return mode

    def update_state(self, app_id, state):
        require(state in {"STARTING", "READY", "CLOSED", "OUTCOME_UNKNOWN", "TRANSPORT_LOST", "CLEANUP_PENDING", "OWNER_LOST"},
                "INVALID_ARGUMENT", "Invalid managed app state.")
        with self._transaction() as db:
            row, _ = self._authorize(db, app_id, owner=True)
            require(not (row["state"] in {"CLOSED", "OUTCOME_UNKNOWN", "OWNER_LOST"} and state == "READY"),
                    "RECOVERY_REQUIRED", "A terminal or quarantined instance cannot be silently reopened.")
            db.execute("UPDATE apps SET state=? WHERE app_id=?", (state, app_id))
            if state != "READY":
                self._cancel_queued(db, "app_id=?", (app_id,), state)
            return self._record(self._row(db, app_id))

    def retire_connection(self):
        with self._transaction() as db:
            db.execute("UPDATE connections SET active=0 WHERE connection_id=?", (self.connection_id,))
            for row in db.execute("SELECT app_id FROM apps").fetchall():
                self._sweep(db, row["app_id"])

    def cancel_pending(self):
        """Stop waiting work at EOF while retaining authority for owner cleanup.

        Already running actions have crossed the dispatch boundary. Close tickets
        remain available to the process owner until retire_connection is called.
        """
        with self._transaction() as db:
            self._current(db)
            count = db.execute("SELECT count(*) FROM operations WHERE connection_id=? "
                               "AND state='QUEUED' AND tool<>'mss_close_app'", (self.connection_id,)).fetchone()[0]
            self._cancel_queued(db, "connection_id=? AND tool<>'mss_close_app'",
                                (self.connection_id,), "CONNECTION_CLOSING")
            return {"connection_id": self.connection_id, "cancelled": count}

    def _operation(self, db, operation_id):
        row = db.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        require(row is not None, "UNKNOWN_OPERATION", "Unknown operation ID.")
        return dict(row) | {"deadline_clock": "monotonic"}

    def enqueue(self, app_id, tool, timeout_ms=10000):
        require(tool in MUTATIONS, "INVALID_ARGUMENT", "Only supported GUI mutations may enter this queue.")
        require(type(timeout_ms) is int and 1 <= timeout_ms <= 60000, "INVALID_ARGUMENT", "Invalid queue deadline.")
        with self._transaction() as db:
            closing = tool == "mss_close_app"
            owner_only = tool in {"mss_close_app", "mss_activate_build"}
            self._authorize(db, app_id, control=not owner_only, owner=owner_only)
            self._sweep(db, app_id)
            state = self._row(db, app_id)["state"]
            require(state == "READY" or closing and state in {"OUTCOME_UNKNOWN", "TRANSPORT_LOST"},
                    state if state == "OUTCOME_UNKNOWN" else "APP_UNAVAILABLE", "The app cannot accept mutations.")
            count = db.execute("SELECT count(*) FROM operations WHERE app_id=? AND state='QUEUED'", (app_id,)).fetchone()[0]
            require(count < self.queue_limit, "QUEUE_FULL", "The app's pending queue is full.")
            operation_id = "op_" + uuid4().hex
            now = time()
            db.execute("INSERT INTO operations(operation_id,app_id,connection_id,tool,state,queued_at,deadline,effect) "
                       "VALUES(?,?,?,?,'QUEUED',?,?,'NOT_VERIFIED')",
                       (operation_id, app_id, self.connection_id, tool, now, monotonic() + timeout_ms / 1000))
            return self._operation(db, operation_id)

    def wait_turn(self, operation_id):
        while True:
            with self._transaction() as db:
                op = self._operation(db, operation_id)
                require(op["connection_id"] == self.connection_id, "OPERATION_OWNER_REQUIRED", "Only the submitting connection may dispatch.")
                self._sweep(db, op["app_id"])
                op = self._operation(db, operation_id)
                if op["state"] != "QUEUED":
                    return op
                # Membership may have been revoked after the request was queued.
                owner_only = op["tool"] in {"mss_close_app", "mss_activate_build"}
                self._authorize(db, op["app_id"], control=not owner_only, owner=owner_only)
                head = db.execute("SELECT operation_id FROM operations WHERE app_id=? AND state IN ('QUEUED','RUNNING') "
                                  "ORDER BY sequence LIMIT 1", (op["app_id"],)).fetchone()
                if head["operation_id"] == operation_id:
                    db.execute("UPDATE operations SET state='RUNNING',started_at=? WHERE operation_id=?", (time(), operation_id))
                    return self._operation(db, operation_id)
            sleep(0.01)

    def finish(self, operation_id, state, code=None, effect="NOT_VERIFIED"):
        require(state in {"APPLIED", "FAILED", "OUTCOME_UNKNOWN"}, "INVALID_ARGUMENT", "Invalid completion state.")
        require(code is None or isinstance(code, str) and re.fullmatch(r"[A-Z0-9_]{1,80}", code),
                "INVALID_ARGUMENT", "Completion codes must contain metadata only.")
        require(effect in {"NOT_VERIFIED", "VERIFIED", "NOT_APPLIED", "OUTCOME_UNKNOWN"},
                "INVALID_ARGUMENT", "Invalid effect classification.")
        with self._transaction() as db:
            op = self._operation(db, operation_id)
            require(op["connection_id"] == self.connection_id, "OPERATION_OWNER_REQUIRED", "Only the submitting connection may complete.")
            require(op["state"] == "RUNNING", "OPERATION_NOT_RUNNING", "Only running operations may complete.")
            db.execute("UPDATE operations SET state=?,completed_at=?,code=?,effect=? WHERE operation_id=?",
                       (state, time(), code, effect, operation_id))
            if state == "OUTCOME_UNKNOWN":
                db.execute("UPDATE apps SET state='OUTCOME_UNKNOWN' WHERE app_id=?", (op["app_id"],))
                self._cancel_queued(db, "app_id=?", (op["app_id"],), "OUTCOME_UNKNOWN")
            self._prune(db, op["app_id"])
            return self._operation(db, operation_id)

    def operations(self, app_id):
        with self._transaction() as db:
            self._authorize(db, app_id)
            self._sweep(db, app_id)
            return [dict(row) | {"deadline_clock": "monotonic"}
                    for row in db.execute("SELECT * FROM operations WHERE app_id=? ORDER BY sequence", (app_id,))]

    def operation(self, app_id, operation_id):
        with self._transaction() as db:
            self._authorize(db, app_id)
            op = self._operation(db, operation_id)
            require(op["app_id"] == app_id, "UNKNOWN_OPERATION", "This operation does not belong to the selected app.")
            self._sweep(db, app_id)
            return self._operation(db, operation_id)

    def cancel(self, app_id, operation_id):
        with self._transaction() as db:
            row, _ = self._authorize(db, app_id)
            op = self._operation(db, operation_id)
            require(op["app_id"] == app_id, "UNKNOWN_OPERATION", "This operation does not belong to the selected app.")
            require(op["connection_id"] == self.connection_id or row["owner"] == self.connection_id,
                    "OPERATION_OWNER_REQUIRED", "Only the submitter or app owner may cancel.")
            require(op["state"] != "RUNNING", "CANNOT_CANCEL", "An already dispatched action cannot be cancelled.")
            if op["state"] == "QUEUED":
                db.execute("UPDATE operations SET state='CANCELLED',completed_at=?,code='CANCELLED_BY_CALLER' "
                           "WHERE operation_id=?", (time(), operation_id))
            return self._operation(db, operation_id)
