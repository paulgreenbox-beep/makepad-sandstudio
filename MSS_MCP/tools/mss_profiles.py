"""Prepare reviewed native app profiles for the existing MSS Makepad launcher."""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat


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
        local_path(python)
        if not (self.repo / CATALOG_PATH).exists():
            raise ValueError("Missing local app catalog. Run Initialize-MakepadProfiles.ps1 first.")
        catalog = decode_object(self.repo_file(CATALOG_PATH).read_bytes())
        if type(catalog.get("schema_version")) is not int or catalog["schema_version"] != 1:
            raise ValueError("Unsupported MSS catalog schema")
        self.launcher = self.repo_file(LAUNCHER_PATH)
        self.launcher_sha256 = catalog["launcher_sha256"]
        self.pwsh = local_path(catalog["pwsh_executable"])
        if self.pwsh.name.lower() != "pwsh.exe":
            raise ValueError("The native launcher requires PowerShell 7")
        self.pwsh_sha256 = catalog["pwsh_sha256"]
        self.entries = {}
        for entry in catalog["profiles"]:
            key = entry["profile"]
            if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", key) or key in self.entries:
                raise ValueError("Invalid or duplicate MSS profile ID")
            if not isinstance(entry.get("title"), str) or not entry["title"]:
                raise ValueError("Missing MSS profile title")
            if entry.get("kind") != "native" or entry.get("access") not in ("semantic", "read-only"):
                raise ValueError("Invalid MSS native profile capability")
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
    def prepare(self, profile_id, run: Path):
        if profile_id not in self.entries:
            raise ValueError("Unknown MSS profile")
        run = local_path(run, directory=True)
        if any(run.iterdir()):
            raise ValueError("A fresh MSS app directory is required")
        check_pin(self.launcher, self.launcher_sha256)
        check_pin(self.pwsh, self.pwsh_sha256)
        yield self.prepare_native(self.entries[profile_id], run)

    def prepare_native(self, entry, run):
        template = self.repo_file(entry["profile_file"])
        profile = decode_object(read_pinned(template, entry["profile_sha256"]))
        if (type(profile.get("schema_version")) is not int or profile["schema_version"] != 1
                or profile.get("admission") != "TRUSTED_DEVELOPMENT"
                or profile.get("remote_supported") is not True
                or profile.get("hidden_native_supported") is not True
                or not re.fullmatch(r"[a-fA-F0-9]{40}", profile["makepad_revision"])):
            raise ValueError("App profile is not admitted for native MSS")
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
        return LaunchPlan(
            command=[str(self.pwsh), "-NoLogo", "-NoProfile", "-NonInteractive",
                     "-File", str(self.launcher), "-Profile", str(profile_path)],
            cwd=work, env=isolated_environment(run), session_root=sessions,
            app_image=Path(profile["app_executable"]), app_sha256=profile["app_sha256"].upper(),
            remote_sha256=profile["remote_sha256"].upper(), makepad_revision=profile["makepad_revision"],
            profile_sha256=hashlib.sha256(profile_path.read_bytes()).hexdigest().upper(),
            access=entry["access"],
        )
