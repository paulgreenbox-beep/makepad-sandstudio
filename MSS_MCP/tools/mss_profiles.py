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


PROFILE_LAUNCH_ENV = {
    "ai-cad": {
        "AI_REVIT_ACADSHARP_DOTNET": "path",
        "AI_REVIT_ACADSHARP_DOTNET_SHA256": "sha256",
        "AI_REVIT_ACADSHARP_WORKER": "path",
        "AI_REVIT_ACADSHARP_WORKER_SHA256": "sha256",
        "AI_REVIT_FILE_ROOTS": "work_directory",
        "AI_REVIT_IMPORT_ROOTS": "work_directory",
    },
}


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
    allowed_press_paths: tuple[str, ...] = ()


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


def local_directory(value, *, create=False):
    """Validate existing ancestors before optionally creating private runtime paths."""
    path = Path(value)
    if (not path.is_absolute() or not re.fullmatch(r"[a-zA-Z]:", path.drive)
            or any(part == ".." or ":" in part or part.endswith((".", " "))
                   for part in path.parts[1:])):
        raise ValueError("A local absolute runtime directory is required")
    for part in (*reversed(path.parents), path):
        try:
            local_path(part, directory=True)
        except FileNotFoundError:
            if not create:
                return path
            part.mkdir(exist_ok=True)
            local_path(part, directory=True)
    return local_path(path, directory=True)


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
    def __init__(self, repo: Path, python: Path, data_root: Path | None = None):
        self.repo = local_path(repo, directory=True)
        self._data_root = self.repo if data_root is None else local_directory(data_root)
        python = local_path(python)
        catalog_path = self.data_root / CATALOG_PATH
        local_directory(catalog_path.parent)
        try:
            catalog = decode_object(local_path(catalog_path).read_bytes())
        except FileNotFoundError:
            catalog = {"schema_version": 1, "profiles": [], "launcher_sha256": "", "pwsh_sha256": ""}
        if type(catalog.get("schema_version")) is not int or catalog["schema_version"] != 1:
            raise ValueError("Unsupported MSS catalog schema")
        self.launcher = local_path(self.repo / LAUNCHER_PATH)
        self.launcher_sha256 = catalog["launcher_sha256"]
        # Operator-owned inputs only. Never take the executable from a tool argument or PATH.
        pwsh_override = os.environ.get("MSS_PWSH_EXE")
        if pwsh_override is not None:
            self.pwsh = Path(pwsh_override)
        elif "pwsh_executable" in catalog:
            self.pwsh = local_path(catalog["pwsh_executable"])
        else:
            self.pwsh = python.parent.parent / "native/powershell/pwsh.exe"
        self.pwsh_sha256 = catalog["pwsh_sha256"]
        self.entries = {}
        for entry in catalog["profiles"]:
            key = entry["profile"]
            if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", key) or key in self.entries:
                raise ValueError("Invalid or duplicate MSS profile ID")
            if not isinstance(entry.get("title"), str) or not entry["title"]:
                raise ValueError("Missing MSS profile title")
            kind, access = entry.get("kind"), entry.get("access")
            if (kind, access) not in (("native", "semantic"), ("native", "read-only"), ("onlyoffice", "read-only")):
                raise ValueError("Invalid MSS profile capability")
            if "allowed_presses" in entry:
                self.validate_allowed_presses(key, kind, access, entry["allowed_presses"])
            self.configured_builds(entry)
            self.entries[key] = entry

    @property
    def data_root(self):
        return getattr(self, "_data_root", self.repo)

    @staticmethod
    def validate_allowed_presses(profile_id, kind, access, policy):
        if ((profile_id, kind, access) != ("ai-cad", "native", "read-only")
                or not isinstance(policy, dict) or set(policy) != {"app_sha256", "paths"}):
            raise ValueError("Invalid MSS read-only semantic press policy")
        digest, paths = policy["app_sha256"], policy["paths"]
        if (not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", digest)
                or not isinstance(paths, list) or len(paths) != 2
                or any(not isinstance(path, str)
                       or not re.fullmatch(r"[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)+", path) for path in paths)
                or paths[0] == paths[1]):
            raise ValueError("Invalid pinned MSS semantic press paths")

    def press_paths(self, profile_id, app_sha256):
        policy = self.entries[profile_id].get("allowed_presses")
        if policy is not None and app_sha256.upper() == policy["app_sha256"].upper():
            return tuple(policy["paths"])
        return ()

    def repo_file(self, relative):
        path = Path(relative)
        if path.anchor or ".." in path.parts:
            raise ValueError("Catalog paths must be relative to MSS")
        return local_path(self.data_root / path)

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
        pwsh = local_path(self.pwsh)
        if pwsh.suffix.lower() != ".exe":
            raise ValueError("The operator PowerShell runtime must be an EXE")
        check_pin(pwsh, self.pwsh_sha256)
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

    @staticmethod
    def configured_builds(entry):
        from mss_builds import _digest, _local_shape

        if "configured_builds" not in entry:
            return None
        rows = entry["configured_builds"]
        if (entry["kind"] != "native" or "build_roots" not in entry
                or not isinstance(rows, list) or len(rows) > 128):
            raise ValueError("Invalid native build configuration allowlist")
        result = {}
        for row in rows:
            if not isinstance(row, dict) or set(row) != {
                    "exe_path", "sha256", "launch_config_file", "launch_config_sha256"}:
                raise ValueError("Invalid configured build entry")
            identity = (_local_shape(row["exe_path"]), _digest(row["sha256"], (64,), "app SHA-256"))
            if identity in result:
                raise ValueError("Duplicate configured build identity")
            result[identity] = (row["launch_config_file"],
                                _digest(row["launch_config_sha256"], (64,), "launch configuration SHA-256"))
        return result

    def apply_build_configuration(self, profile_id, build, profile, work):
        from mss_builds import BuildError, _digest, _existing, _local_shape, _no_duplicate_keys

        expected = build.get("launch_config_sha256")
        if expected is None:
            return {}
        binding = self.configured_builds(self.entries[profile_id])
        identity = (Path(build["exe_path"]), build["sha256"])
        if binding is None or identity not in binding or binding[identity][1] != expected:
            raise BuildError("BUILD_NOT_ADMITTED", "This build's launch configuration is not admitted.")
        relative, _ = binding[identity]
        try:
            path = _existing(_local_shape(self.repo_file(relative)), single_link=True)
            config = json.loads(read_pinned(path, expected).decode("utf-8-sig"),
                                object_pairs_hook=_no_duplicate_keys)
            if (not isinstance(config, dict) or set(config) != {
                    "schema_version", "profile", "makepad_revision", "app_arguments", "files", "environment"}
                    or type(config["schema_version"]) is not int or config["schema_version"] != 1
                    or config["profile"] != profile_id):
                raise ValueError("Configuration must identify its exact native profile.")
            if config["makepad_revision"] != profile["makepad_revision"]:
                raise BuildError("BUILD_CONFIG_INCOMPATIBLE", "The build's Makepad revision does not match its admitted Remote profile.")
            arguments = config["app_arguments"]
            if (not isinstance(arguments, list) or len(arguments) > 64
                    or any(not isinstance(arg, str) or len(arg) > 4096 or "\0" in arg
                           or re.match(r"^--(?:remote|stdin-loop)(?:=|$)", arg, re.I) for arg in arguments)):
                raise ValueError("Launch arguments must be literal and cannot override Remote.")
            files = config["files"]
            if not isinstance(files, dict) or len(files) > 32:
                raise ValueError("Invalid pinned launch files.")
            for key, pin in files.items():
                if (not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", key) or not isinstance(pin, dict)
                        or set(pin) != {"path", "sha256"}):
                    raise ValueError("Invalid launch file pin.")
                file = _existing(_local_shape(pin["path"]), single_link=True)
                digest = _digest(pin["sha256"], (64,), "launch file SHA-256")
                check_pin(file, digest)
                files[key] = {"path": str(file), "sha256": digest}
            environment = config["environment"]
            policy = PROFILE_LAUNCH_ENV.get(profile_id, {})
            if not isinstance(environment, dict) or environment.keys() - policy.keys():
                raise ValueError("Environment keys must be explicitly allowed for this profile.")
            env = {}
            for name, reference in environment.items():
                if not isinstance(reference, dict) or len(reference) != 1:
                    raise ValueError("Invalid launch environment reference.")
                kind, key = next(iter(reference.items()))
                if (kind != policy[name] or not isinstance(key, str)
                        or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", key)):
                    raise ValueError("Invalid launch environment reference.")
                if kind == "work_directory":
                    directory = work / key
                    directory.mkdir(exist_ok=True)
                    env[name] = str(directory)
                elif kind in {"path", "sha256"} and key in files:
                    env[name] = files[key][kind]
                else:
                    raise ValueError("Unknown launch environment reference.")
            worker_paths = ("AI_REVIT_ACADSHARP_DOTNET", "AI_REVIT_ACADSHARP_WORKER")
            if any(name in env or f"{name}_SHA256" in env for name in worker_paths):
                for name in worker_paths:
                    path_ref = environment.get(name, {}).get("path")
                    if path_ref is None or environment.get(f"{name}_SHA256", {}).get("sha256") != path_ref:
                        raise ValueError("The runtime and worker must each use one matching file and hash pin.")
            profile.update(app_arguments=arguments, launch_config_sha256=expected,
                           launch_files=files, launch_environment=env)
            return env
        except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
            raise BuildError("BUILD_CONFIG_INVALID", f"Invalid pinned launch configuration: {error}") from error
    def build_registry(self, profile_id, template=None):
        from mss_builds import BuildError, BuildRegistry

        entry = self.entries.get(profile_id)
        if entry is None:
            raise BuildError("UNKNOWN_PROFILE", "Choose an admitted profile from mss_list_apps.")
        if entry["kind"] != "native" or "build_roots" not in entry:
            raise BuildError("BUILDS_DISABLED", "This profile has no operator-admitted build roots.")
        configured = self.configured_builds(entry)
        return BuildRegistry(self.data_root, profile_id, entry["build_roots"],
                             self.native_template(entry) if template is None else template,
                             admissions=None if configured is None else {
                                 identity: pin[1] for identity, pin in configured.items()
                             })

    def prepare_native(self, profile_id, entry, run, build_id):
        profile = self.native_template(entry)
        build = None
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
        env = isolated_environment(run)
        if build is not None:
            env.update(self.apply_build_configuration(profile_id, build, profile, work))
        write_object(profile_path, profile)
        return self.plan(profile, profile_path, env, entry["access"], build_id,
                         allowed_press_paths=self.press_paths(profile_id, profile["app_sha256"]))

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

    def plan(self, profile, path, env, access, build_id=None, *, allowed_press_paths=()):
        return LaunchPlan(
            command=[str(self.pwsh), "-NoLogo", "-NoProfile", "-NonInteractive",
                     "-File", str(self.launcher), "-Profile", str(path)],
            cwd=Path(profile["working_directory"]), env=env,
            session_root=Path(profile["session_root"]), app_image=Path(profile["app_executable"]),
            app_sha256=profile["app_sha256"].upper(), remote_sha256=profile["remote_sha256"].upper(),
            makepad_revision=profile["makepad_revision"],
            profile_sha256=hashlib.sha256(path.read_bytes()).hexdigest().upper(), access=access, build_id=build_id,
            allowed_press_paths=allowed_press_paths,
        )
