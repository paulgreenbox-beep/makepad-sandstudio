"""Prepare reviewed app profiles for the existing MSS Makepad launcher."""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from types import ModuleType


CATALOG_PATH = Path("MSS_MCP/profiles/local.apps.json")
LAUNCHER_PATH = Path("MSS_MCP/tools/Start-MakepadMcp.ps1")
SYSTEM_KEYS = (
    "SystemRoot", "WINDIR", "SystemDrive", "COMSPEC", "OS", "PATHEXT",
    "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER", "NUMBER_OF_PROCESSORS",
)


@dataclass(frozen=True)
class LaunchPlan:
    command: list[str]
    cwd: Path
    env: dict[str, str]
    session_root: Path
    app_image: Path
    app_sha256: str
    remote_sha256: str
    makepad_revision: str
    profile_sha256: str
    access: str
    build_id: str | None = None


def local_path(value, *, directory=False):
    path = Path(value)
    if not path.is_absolute() or path.drive.startswith("\\\\"):
        raise ValueError("A local absolute Windows path is required")
    for part in (path, *path.parents):
        attributes = getattr(part.lstat(), "st_file_attributes", 0)
        if part.is_symlink() or attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("Reparse paths cannot be admitted")
    if not (path.is_dir() if directory else path.is_file()):
        raise ValueError(f"Unexpected path type: {path.name}")
    return path.resolve(strict=True)


def read_pinned(path, expected):
    data = path.read_bytes()
    verify_digest(path, hashlib.sha256(data).hexdigest(), expected)
    return data


def check_pin(path, expected):
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    verify_digest(path, actual, expected)


def verify_digest(path, actual, expected):
    if not isinstance(expected, str) or actual != expected.lower():
        raise ValueError(f"SHA-256 mismatch: {path.name}")


def decode_object(data):
    value = json.loads(data.decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def write_object(path, value):
    data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(data)


def isolated_environment(run):
    env = {key: os.environ[key] for key in SYSTEM_KEYS if key in os.environ}
    windows = Path(env["SystemRoot"])
    env["PATH"] = os.pathsep.join(map(str, (windows / "System32", windows)))
    home, local, roaming, temp = (run / "profile" / name for name in (
        "home", "local", "roaming", "temp",
    ))
    for path in (home, local, roaming, temp):
        path.mkdir(parents=True)
    env.update({
        "USERPROFILE": str(home), "HOME": str(home), "HOMEDRIVE": home.drive,
        "HOMEPATH": str(home)[len(home.drive):], "LOCALAPPDATA": str(local),
        "APPDATA": str(roaming), "TEMP": str(temp), "TMP": str(temp),
    })
    return env


class Catalog:
    def __init__(self, repo: Path, python: Path):
        self.repo = local_path(repo, directory=True)
        python = local_path(python)
        catalog = decode_object(self.repo_file(CATALOG_PATH).read_bytes())
        if type(catalog.get("schema_version")) is not int or catalog["schema_version"] != 1:
            raise ValueError("Unsupported MSS catalog schema")
        self.launcher = self.repo_file(LAUNCHER_PATH)
        self.launcher_sha256 = catalog["launcher_sha256"]
        # Operator-owned catalog, never a tool argument or a PATH lookup.
        # Retain the established bundled-runtime default for existing catalogs.
        self.pwsh = local_path(catalog.get(
            "pwsh_executable", python.parent.parent / "native/powershell/pwsh.exe"))
        self.pwsh_sha256 = catalog["pwsh_sha256"]
        self.entries = {}
        for entry in catalog["profiles"]:
            key = entry["profile"]
            if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", key) or key in self.entries:
                raise ValueError("Invalid or duplicate MSS profile ID")
            if not isinstance(entry.get("title"), str) or not entry["title"]:
                raise ValueError("Missing MSS profile title")
            expected = {"native": "semantic", "onlyoffice": "read-only"}.get(entry.get("kind"))
            if expected is None or entry.get("access") != expected:
                raise ValueError("Invalid MSS profile capability")
            self.entries[key] = entry

    def repo_file(self, relative):
        path = Path(relative)
        if path.anchor or ".." in path.parts:
            raise ValueError("Catalog paths must be relative to MSS")
        return local_path(self.repo / path)

    def apps(self):
        return [{key: entry[key] for key in ("profile", "title", "access")}
                for entry in self.entries.values()]

    @contextmanager
    def prepare(self, profile_id, run: Path, build_id=None):
        if profile_id not in self.entries:
            raise ValueError("Unknown MSS profile")
        run = local_path(run, directory=True)
        if any(run.iterdir()):
            raise ValueError("A fresh MSS app directory is required")
        check_pin(self.launcher, self.launcher_sha256)
        check_pin(self.pwsh, self.pwsh_sha256)
        entry = self.entries[profile_id]
        if entry["kind"] == "native":
            yield self.prepare_native(profile_id, entry, run, build_id)
        else:
            if build_id is not None:
                self.build_registry(profile_id)  # Reject explicit builds on read-only profiles.
            with self.prepare_onlyoffice(entry, run) as plan:
                yield plan

    def native_template(self, entry):
        template = self.repo_file(entry["profile_file"])
        profile = decode_object(read_pinned(template, entry["profile_sha256"]))
        if (type(profile.get("schema_version")) is not int or profile["schema_version"] != 1
                or profile.get("admission") != "TRUSTED_DEVELOPMENT"
                or profile.get("remote_supported") is not True
                or profile.get("hidden_native_supported") is not True
                or not re.fullmatch(r"[a-fA-F0-9]{40}", profile["makepad_revision"])):
            raise ValueError("App profile is not admitted for native MSS")
        return profile

    def build_registry(self, profile_id, template=None):
        from mss_builds import BuildError, BuildRegistry

        entry = self.entries.get(profile_id)
        if entry is None:
            raise BuildError("UNKNOWN_PROFILE", "Choose an admitted profile from mss_list_apps.")
        if entry["kind"] != "native" or "build_roots" not in entry:
            raise BuildError("BUILDS_DISABLED", "This profile has no operator-admitted build roots.")
        return BuildRegistry(self.repo, profile_id, entry["build_roots"],
                             self.native_template(entry) if template is None else template)

    def prepare_native(self, profile_id, entry, run, build_id):
        profile = self.native_template(entry)
        if build_id is not None or "build_roots" in entry:
            build = self.build_registry(profile_id, profile).select(build_id)
            build_id = build["build_id"]
            profile.update(app_executable=build["exe_path"], app_sha256=build["sha256"])
        for key in ("app", "remote"):
            exe = local_path(profile[f"{key}_executable"])
            if exe.suffix.lower() != ".exe":
                raise ValueError("Native MSS requires an executable")
            check_pin(exe, profile[f"{key}_sha256"])
            profile[f"{key}_executable"] = str(exe)
        args = profile.get("app_arguments", [])
        if not isinstance(args, list) or any(not isinstance(arg, str) or "\0" in arg for arg in args):
            raise ValueError("Native profile app_arguments must be literal strings")
        work, sessions = run / "work", run / "sessions"
        work.mkdir()
        sessions.mkdir()
        profile.update(working_directory=str(work), session_root=str(sessions))
        profile_path = run / "profile.json"
        write_object(profile_path, profile)
        return self.plan(profile, profile_path, isolated_environment(run), entry["access"], build_id)

    @contextmanager
    def prepare_onlyoffice(self, entry, run):
        bootstrap = self.repo_file(entry["bootstrap_file"])
        source = read_pinned(bootstrap, entry["bootstrap_sha256"])
        base = bootstrap.parent
        config_path = local_path(base / "integration.json")
        check_pin(config_path, entry["integration_sha256"])
        adapter = ModuleType("mss_reviewed_onlyoffice_bootstrap")
        adapter.__file__ = str(bootstrap)
        exec(compile(source, str(bootstrap), "exec"), adapter.__dict__)
        config = adapter.read_config(base)
        if Path(config["launcher"]) != self.launcher or Path(config["pwsh_executable"]) != self.pwsh:
            raise ValueError("ONLYOFFICE launcher does not match the MSS catalog")
        fixture = adapter.load_fixture(base, config["fixture_sha256"])
        profile_path = adapter.stage_profile(base, run, config)
        profile = decode_object(profile_path.read_bytes())
        evidence = {"fixture_listeners_closed": False}
        try:
            with adapter.loopback_fixture(fixture, run / "fixture", evidence) as endpoints:
                env = adapter.isolated_environment(run, endpoints)
                yield self.plan(profile, profile_path, env, entry["access"])
        finally:
            write_object(run / "fixture-lifecycle.json", evidence)
        if evidence["fixture_listeners_closed"] is not True:
            raise RuntimeError("ONLYOFFICE fixture cleanup was not confirmed")

    def plan(self, profile, path, env, access, build_id=None):
        return LaunchPlan(
            command=[str(self.pwsh), "-NoLogo", "-NoProfile", "-NonInteractive",
                     "-File", str(self.launcher), "-Profile", str(path)],
            cwd=Path(profile["working_directory"]), env=env,
            session_root=Path(profile["session_root"]), app_image=Path(profile["app_executable"]),
            app_sha256=profile["app_sha256"].upper(), remote_sha256=profile["remote_sha256"].upper(),
            makepad_revision=profile["makepad_revision"],
            profile_sha256=hashlib.sha256(path.read_bytes()).hexdigest().upper(), access=access, build_id=build_id,
        )
