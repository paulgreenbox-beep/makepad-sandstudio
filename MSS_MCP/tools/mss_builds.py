"""Local, profile-scoped executable selection for the existing MSS launcher."""

from contextlib import contextmanager
import ctypes
import hashlib
import json
import msvcrt
import os
from pathlib import Path
import re
import stat
import tempfile
from time import monotonic, sleep


BASELINE = "baseline"
MAX_BUILDS = 128
MAX_STATE_BYTES = 2 * 1024 * 1024


class BuildError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _local_shape(value):
    if not isinstance(value, (str, Path)):
        raise BuildError("BUILD_PATH_DENIED", "A local absolute path is required.")
    raw = str(value).replace("/", "\\")
    if not re.fullmatch(r"[a-zA-Z]:\\[^:\x00-\x1f\ud800-\udfff<>\"|?*]+", raw):
        raise BuildError("BUILD_PATH_DENIED", "Use a local drive path without streams or device syntax.")
    parts = raw[3:].split("\\")
    if any(not part or part.endswith((".", " ")) or Path(part).is_reserved() for part in parts):
        raise BuildError("BUILD_PATH_DENIED", "Path contains traversal, aliases, or reserved names.")
    return Path(raw)


def _existing(path, *, directory=False, single_link=False):
    if ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(path.anchor)) not in (2, 3, 6):
        raise BuildError("BUILD_PATH_DENIED", "The path must be on a local filesystem.")
    try:
        for component in (*reversed(path.parents), path):
            attributes = component.lstat().st_file_attributes
            if attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise BuildError("BUILD_PATH_DENIED", "Reparse points are not allowed in build paths.")
        info = path.stat()
        expected = stat.S_ISDIR if directory else stat.S_ISREG
        if not expected(info.st_mode) or (single_link and info.st_nlink != 1):
            raise BuildError("BUILD_PATH_DENIED", "Expected a regular local path without file aliases.")
        return path.resolve(strict=True)
    except FileNotFoundError as error:
        raise BuildError("BUILD_MISSING", "The build path does not exist.") from error
    except OSError as error:
        raise BuildError("BUILD_PATH_DENIED", "The build path cannot be checked.") from error


def _digest(value, widths, label):
    if not isinstance(value, str) or len(value) not in widths or not re.fullmatch(r"[0-9a-fA-F]+", value):
        raise BuildError("BUILD_ARGUMENT_INVALID", f"Invalid {label}.")
    return value.upper()


def _build_id(path, sha256, launch_config_sha256=None):
    name = os.path.normcase(str(path))
    identity = f"{name}\0{sha256}"
    if launch_config_sha256 is not None:
        identity += f"\0{launch_config_sha256}"
    return "build_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _verification(value):
    if (not isinstance(value, dict) or not {"statement", "launcher_receipt"} <= value.keys()
            or len(value) > 12
            or any(not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key)
                   or not isinstance(item, str) or not item.strip() or len(item) > 4096 or "\0" in item
                   for key, item in value.items())):
        raise BuildError("BUILD_VERIFICATION_REQUIRED", "Activation requires reviewed launch evidence and a statement.")
    return dict(value)


def _no_duplicate_keys(pairs):
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError("Duplicate state key")
    return value


class BuildRegistry:
    def __init__(self, repo, profile_id, build_roots, template, admissions=None):
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", profile_id):
            raise BuildError("BUILD_ARGUMENT_INVALID", "Invalid build profile ID.")
        if not isinstance(build_roots, list) or not 1 <= len(build_roots) <= 16:
            raise BuildError("BUILD_PATH_DENIED", "This profile needs explicit local build roots.")
        self.profile = profile_id
        self.roots = [_local_shape(root) for root in build_roots]
        self.admissions = None if admissions is None else dict(admissions)
        self.directory = repo / "MSS_MCP" / "profiles" / "local.builds"
        self.state_path = self.directory / f"{profile_id}.json"
        self.baseline = self._record(BASELINE, _local_shape(template["app_executable"]),
                                     _digest(template["app_sha256"], (64,), "baseline SHA-256"), None)

    def _record(self, build_id, exe_path, sha256, git_sha, launch_config_sha256=None):
        record = {
            "build_id": build_id, "profile": self.profile, "exe_path": str(exe_path),
            "sha256": sha256, "git_sha": git_sha, "verification": None,
        }
        if launch_config_sha256 is not None:
            record["launch_config_sha256"] = launch_config_sha256
        return record

    def _admission_digest(self, path, sha256):
        if self.admissions is None:
            return None
        digest = self.admissions.get((path, sha256))
        if digest is None:
            raise BuildError("BUILD_NOT_ADMITTED", "The executable path and SHA-256 lack current launch admission.")
        return _digest(digest, (64,), "launch configuration SHA-256")

    def _candidate_path(self, value):
        path = _local_shape(value)
        if path.name.casefold() != Path(self.baseline["exe_path"]).name.casefold() or path.suffix.lower() != ".exe":
            raise BuildError("BUILD_PATH_DENIED", "The candidate EXE name must match the profile executable.")
        for root in self.roots:
            if path.is_relative_to(root):
                root = _existing(root, directory=True)
                path = _existing(path, single_link=True)
                if path.is_relative_to(root):
                    return path
        raise BuildError("BUILD_PATH_DENIED", "The candidate is outside this profile's allowed build roots.")

    def _check_pin(self, record):
        recorded_path = _local_shape(record["exe_path"])
        if record["build_id"] == BASELINE:
            path = _existing(recorded_path)
        else:
            admitted = self._admission_digest(recorded_path, record["sha256"])
            if record.get("launch_config_sha256") != admitted:
                raise BuildError("BUILD_NOT_ADMITTED", "The registered launch configuration is no longer admitted.")
            path = self._candidate_path(recorded_path)
            if self.admissions is not None and path != recorded_path:
                raise BuildError("BUILD_NOT_ADMITTED", "The executable no longer resolves to its admitted path.")
        if path.suffix.lower() != ".exe":
            raise BuildError("BUILD_PATH_DENIED", "The profile executable must be an EXE.")
        try:
            with path.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest().upper()
        except OSError as error:
            raise BuildError("BUILD_MISSING", "The executable cannot be read.") from error
        if actual != record["sha256"]:
            raise BuildError("BUILD_HASH_MISMATCH", "The executable does not match its registered SHA-256.")
        return dict(record)

    @contextmanager
    def _locked(self):
        try:
            _existing(self.directory.parent, directory=True)
            self.directory.mkdir(exist_ok=True)
            _existing(self.directory, directory=True)
            lock_path = self.directory / f"{self.profile}.lock"
            if os.path.lexists(lock_path):
                _existing(lock_path, single_link=True)
            with lock_path.open("a+b") as stream:
                stream.seek(0)
                deadline = monotonic() + 8
                while True:
                    try:
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError as error:
                        if monotonic() >= deadline:
                            raise BuildError("BUILD_STATE_BUSY", "The build registry is locked by another client.") from error
                        sleep(0.05)
                yield
        except OSError as error:
            raise BuildError("BUILD_STATE_UNAVAILABLE", "The build registry cannot be read or updated.") from error

    def _load(self):
        if not os.path.lexists(self.state_path):
            return {
                "schema_version": 1, "profile": self.profile, "active_build_id": BASELINE,
                "previous_build_id": None, "builds": {BASELINE: dict(self.baseline)},
            }
        try:
            path = _existing(self.state_path, single_link=True)
            with path.open("rb") as stream:
                data = stream.read(MAX_STATE_BYTES + 1)
            if len(data) > MAX_STATE_BYTES:
                raise ValueError("State exceeds size limit")
            state = json.loads(data, object_pairs_hook=_no_duplicate_keys)
            self._validate_state(state)
            return state
        except (BuildError, ValueError, TypeError, KeyError, RecursionError) as error:
            raise BuildError("BUILD_STATE_INVALID", "The build registry is invalid. Preserve it for operator review.") from error

    def _validate_state(self, state):
        keys = {"schema_version", "profile", "active_build_id", "previous_build_id", "builds"}
        if (not isinstance(state, dict) or state.keys() != keys or type(state["schema_version"]) is not int
                or state["schema_version"] != 1 or state["profile"] != self.profile):
            raise ValueError("Invalid state header")
        builds = state["builds"]
        if not isinstance(builds, dict) or not 1 <= len(builds) <= MAX_BUILDS or BASELINE not in builds:
            raise ValueError("Invalid builds")
        paths = set()
        for key, record in builds.items():
            if not isinstance(record, dict):
                raise ValueError("Invalid build record")
            fields = self.baseline.keys()
            launch_config_sha256 = None
            if self.admissions is not None and key != BASELINE and "launch_config_sha256" in record:
                fields = fields | {"launch_config_sha256"}
                launch_config_sha256 = _digest(record["launch_config_sha256"], (64,), "launch configuration SHA-256")
                if record["launch_config_sha256"] != launch_config_sha256:
                    raise ValueError("Invalid launch configuration digest")
            if record.keys() != fields:
                raise ValueError("Invalid build record")
            path = _local_shape(record["exe_path"])
            sha = _digest(record["sha256"], (64,), "SHA-256")
            git = record["git_sha"]
            expected_id = BASELINE if key == BASELINE else _build_id(path, sha, launch_config_sha256)
            if (record["build_id"] != key or key != expected_id or record["profile"] != self.profile
                    or record["exe_path"] != str(path) or record["sha256"] != sha
                    or path in paths
                    or (git is not None and git != _digest(git, (40, 64), "Git SHA").lower())):
                raise ValueError("Invalid build identity")
            paths.add(path)
            if key == BASELINE and (record | {"verification": None}) != self.baseline:
                raise ValueError("Baseline profile pin changed")
            if record["verification"] is not None:
                _verification(record["verification"])
        active, previous = state["active_build_id"], state["previous_build_id"]
        if active not in builds or previous == active or (previous is not None and previous not in builds):
            raise ValueError("Invalid active or previous build")
        for selected in (active, previous):
            if selected not in (None, BASELINE) and builds[selected]["verification"] is None:
                raise ValueError("Unreviewed active or previous build")

    def _save(self, state):
        data = (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if len(data) > MAX_STATE_BYTES:
            raise BuildError("BUILD_STATE_LIMIT", "The build registry reached its size limit.")
        temp = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=self.directory, delete=False) as stream:
                temp = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.state_path)
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)

    def _selection(self, state):
        return {key: state[key] for key in ("profile", "active_build_id", "previous_build_id")}

    def _get(self, state, build_id):
        if build_id not in state["builds"]:
            raise BuildError("UNKNOWN_BUILD", "This build is not registered for the profile.")
        return state["builds"][build_id]

    def _expect_active(self, state, expected_active):
        if state["active_build_id"] != expected_active:
            raise BuildError("BUILD_CONFLICT", "The active build changed. List builds before deciding again.")

    def list(self):
        with self._locked():
            state = self._load()
            return self._selection(state) | {"builds": list(state["builds"].values())}

    def register(self, exe_path, sha256, git_sha=None):
        sha256 = _digest(sha256, (64,), "SHA-256")
        git_sha = _digest(git_sha, (40, 64), "Git SHA").lower() if git_sha is not None else None
        path = self._candidate_path(exe_path)
        registering_baseline = self.admissions is not None and path == Path(self.baseline["exe_path"]).resolve(strict=False)
        launch_config_sha256 = None if registering_baseline else self._admission_digest(path, sha256)
        build_id = BASELINE if registering_baseline else _build_id(path, sha256, launch_config_sha256)
        record = self._check_pin(self._record(build_id, path, sha256, git_sha, launch_config_sha256))
        with self._locked():
            state = self._load()
            for existing in state["builds"].values():
                existing_path = Path(existing["exe_path"])
                if existing["build_id"] == BASELINE:
                    existing_path = existing_path.resolve(strict=False)
                if existing_path != path:
                    continue
                if existing["sha256"] != sha256 or existing.get("launch_config_sha256") != launch_config_sha256:
                    raise BuildError("BUILD_CONFLICT", "This path is already pinned. Use a separate path for each build.")
                if git_sha is not None and existing["git_sha"] != git_sha:
                    raise BuildError("BUILD_CONFLICT", "The registered build has different Git provenance.")
                return existing
            if len(state["builds"]) >= MAX_BUILDS:
                raise BuildError("BUILD_STATE_LIMIT", "This profile reached its build count limit.")
            state["builds"][build_id] = record
            self._save(state)
            return record

    def select(self, build_id=None):
        with self._locked():
            state = self._load()
            record = self._get(state, state["active_build_id"] if build_id is None else build_id)
            return self._check_pin(record)

    def activate(self, build_id, expected_active, verification):
        evidence = _verification(verification)
        with self._locked():
            state = self._load()
            self._expect_active(state, expected_active)
            if build_id == expected_active:
                raise BuildError("BUILD_CONFLICT", "This build is already active.")
            record = self._get(state, build_id)
            self._check_pin(record)
            record["verification"] = evidence
            state.update(active_build_id=build_id, previous_build_id=expected_active)
            self._save(state)
            return self._selection(state)

    def rollback(self, expected_active):
        with self._locked():
            state = self._load()
            self._expect_active(state, expected_active)
            previous = state["previous_build_id"]
            if previous is None:
                raise BuildError("NO_PREVIOUS_BUILD", "There is no previous active build to restore.")
            self._check_pin(self._get(state, previous))
            state.update(active_build_id=previous, previous_build_id=None)
            self._save(state)
            return self._selection(state)
