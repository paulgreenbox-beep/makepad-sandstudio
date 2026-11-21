"""Owned native Linux process boundary for a local Makepad demo.

The operator supplies exact local ELF files. This module launches the official
Makepad Remote MCP stdio client; it does not implement its wire protocol,
provide OS sandboxing, discover unrelated apps, or qualify the Windows runtime.
"""

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time


class LinuxProcessError(RuntimeError):
    """Admission, ownership, readiness, or cleanup could not be verified."""


@dataclass(frozen=True)
class PinnedExecutable:
    path: Path | str
    sha256: str


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    start_ticks: int
    executable: str
    device: int
    inode: int
    sha256: str


def _file_tuple(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _canonical(value, *, directory=False):
    path = Path(value)
    try:
        canonical = path.resolve(strict=True) if path.is_absolute() else None
    except (OSError, RuntimeError) as error:
        raise LinuxProcessError("use an existing canonical absolute local path") from error
    if canonical != path:
        raise LinuxProcessError("use an existing canonical absolute local path")
    if directory and not path.is_dir():
        raise LinuxProcessError("working directory is not a directory")
    return path


def _start_ticks(pid):
    # The comm field is parenthesized and may itself contain spaces or ')'.
    # The remaining fields start with state (field 3); starttime is field 22.
    with open(f"/proc/{pid}/stat", "rb") as record:
        _, separator, fields = record.read(8192).rpartition(b")")
    if not separator:
        raise LinuxProcessError("invalid /proc process identity")
    return int(fields.split()[19])


def _require_pidfds():
    if sys.platform != "linux" or not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        raise LinuxProcessError("native Linux with pidfd support is required")
    # Fail before spawning if the kernel or execution environment denies pidfds.
    try:
        fd = os.pidfd_open(os.getpid())
        try:
            signal.pidfd_send_signal(fd, 0)
        finally:
            os.close(fd)
    except OSError as error:
        raise LinuxProcessError("Linux pidfds are not available in this environment") from error


def _require_unix_sockets():
    # The official Linux Remote uses a local Unix-domain socket. Do not launch
    # a guest if the current host policy cannot even create that socket type.
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM):
            pass
    except OSError as error:
        raise LinuxProcessError("Local Unix sockets are unavailable; Makepad Remote cannot start here.") from error


class _OwnedProcess:
    """Retain the direct Popen child and a pidfd; never signal by numeric PID."""

    def __init__(self, process, path, expected, sha256):
        self.process = process
        self.path = path
        self.expected = expected
        self.sha256 = sha256
        self.pidfd = None
        self.identity = None

    def bind(self):
        self.pidfd = os.pidfd_open(self.process.pid)
        self.identity = self.verify()

    def verify(self):
        pid = self.process.pid
        if self.process.poll() is not None:
            raise LinuxProcessError(f"owned process {pid} exited ({self.process.returncode})")
        try:
            first = _start_ticks(pid)
            exe = f"/proc/{pid}/exe"
            image = os.readlink(exe)
            info = os.stat(exe)
            last = _start_ticks(pid)
        except (OSError, IndexError, ValueError) as error:
            raise LinuxProcessError(f"could not verify owned process {pid}") from error
        current = ProcessIdentity(pid, first, image, info.st_dev, info.st_ino, self.sha256)
        if (self.pidfd is None or first != last or image != str(self.path)
                or _file_tuple(info) != self.expected
                or (self.identity is not None and current != self.identity)):
            raise LinuxProcessError(f"owned process {pid} executable/birth identity changed")
        return current

    def _signal(self, value):
        if self.process.poll() is not None:
            return
        try:
            self.verify()
            signal.pidfd_send_signal(self.pidfd, value)
        except ProcessLookupError:
            # The former child exited between the check and the signal.
            pass
        except LinuxProcessError:
            if self.process.poll() is None:
                raise

    def finish(self, *, signal_owned):
        code = self.process.poll()
        if code is None and signal_owned:
            self.verify()
            if self.process.stdin is not None:
                self.process.stdin.close()
            try:
                # The router may already have delivered an official ui__quit.
                # Allow the guest (or EOF-driven client) to exit cleanly first.
                code = self.process.wait(timeout=0.65)
            except subprocess.TimeoutExpired:
                pass
            if code is None:
                self._signal(signal.SIGTERM)
                try:
                    code = self.process.wait(timeout=1.25)
                except subprocess.TimeoutExpired:
                    self._signal(signal.SIGKILL)
                    try:
                        code = self.process.wait(timeout=1.25)
                    except subprocess.TimeoutExpired:
                        pass
        if code is None:
            raise LinuxProcessError(f"owned process {self.process.pid} exit not verified")
        for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
            if pipe is not None and not pipe.closed:
                pipe.close()
        if self.pidfd is not None:
            os.close(self.pidfd)
            self.pidfd = None
        return code


def _spawn(pin, args, *, cwd, env, stdio, log):
    if not isinstance(pin, PinnedExecutable):
        raise LinuxProcessError("an operator-pinned executable is required")
    if not isinstance(pin.sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", pin.sha256):
        raise LinuxProcessError("an exact executable SHA-256 is required")
    path = _canonical(pin.path)
    sha256 = pin.sha256.lower()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as executable:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not info.st_mode & 0o111:
            raise LinuxProcessError("pin does not name an executable regular file")
        if executable.read(4) != b"\x7fELF":
            raise LinuxProcessError("only a native ELF executable may be pinned")
        executable.seek(0)
        if hashlib.file_digest(executable, "sha256").hexdigest() != sha256:
            raise LinuxProcessError("executable SHA-256 mismatch")
        expected = _file_tuple(info)
        if _file_tuple(os.fstat(fd)) != expected or _file_tuple(path.stat()) != expected:
            raise LinuxProcessError("executable changed during admission")
        with log.open("xb") as output:
            # Exec the file we hashed, not a pathname that can be replaced
            # between admission and fork/exec. A single inherited read-only fd
            # is intentionally passed to the native binary.
            proc = subprocess.Popen(
                [str(path), *args], executable=f"/proc/self/fd/{fd}", pass_fds=(fd,),
                cwd=cwd, env=env, stdin=subprocess.PIPE if stdio else subprocess.DEVNULL,
                stdout=subprocess.PIPE if stdio else output,
                stderr=output if stdio else subprocess.STDOUT,
            )
    return _OwnedProcess(proc, path, expected, sha256)


def _environment(directory):
    # Pass the necessary display/session settings, not arbitrary loader options,
    # service credentials, Makepad host/agent variables or inherited FDs.
    names = {
        "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_SESSION_TYPE",
        "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LIBGL_ALWAYS_SOFTWARE",
    }
    env = {name: os.environ[name] for name in names if name in os.environ}
    old_runtime = os.environ.get("XDG_RUNTIME_DIR")
    display = env.get("WAYLAND_DISPLAY", "wayland-0")
    if old_runtime and not Path(display).is_absolute() and Path(old_runtime).is_absolute():
        original_socket = Path(old_runtime) / display
        if original_socket.is_socket():
            # Wayland resolves relative display names under XDG_RUNTIME_DIR.
            # Preserve the host display socket when switching to private discovery.
            env["WAYLAND_DISPLAY"] = str(original_socket)
    env.update(PATH=os.defpath, TMPDIR=str(directory), XDG_RUNTIME_DIR=str(directory))
    return env


class OwnedLinuxApp:
    """One demo-owned guest plus at most one official Remote stdio child."""

    @classmethod
    def launch(cls, guest, *, cwd=None, hidden=True, startup_timeout=15.0):
        _require_pidfds()
        _require_unix_sockets()
        if not math.isfinite(startup_timeout) or not 0 < startup_timeout <= 120:
            raise LinuxProcessError("startup timeout must be >0 and <=120 seconds")
        if not isinstance(guest, PinnedExecutable):
            raise LinuxProcessError("an operator-pinned guest executable is required")
        cwd = _canonical(cwd if cwd is not None else Path(guest.path).parent, directory=True)
        app = cls()
        app.directory = Path(tempfile.mkdtemp(prefix="mss-", dir="/tmp"))
        info = app.directory.lstat()
        app._directory_identity = (info.st_dev, info.st_ino)
        app._env = _environment(app.directory)
        app._guest = app._remote = None
        app._cleanup_started = False
        app._receipt = None
        try:
            env = app._env.copy()
            if hidden:
                env["MAKEPAD_HIDE_WINDOWS"] = "1"
                env["MAKEPAD_HAL_BACKEND"] = "gl"
            app._guest = _spawn(
                guest, ["--remote"], cwd=cwd, env=env, stdio=False,
                log=app.directory / "guest.log",
            )
            app._guest.bind()
            app._wait_discovery(startup_timeout)
        except (OSError, LinuxProcessError, ValueError) as error:
            details = str(error)
            try:
                app.close()
            except LinuxProcessError as cleanup:
                details += f"\n{cleanup}"
            raise LinuxProcessError(details) from error
        return app

    @property
    def pid(self):
        return self._guest.process.pid

    @property
    def identity(self):
        return self._guest.identity

    def _check_directory(self):
        info = self.directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700
                or info.st_uid != os.getuid() or (info.st_dev, info.st_ino) != self._directory_identity):
            raise LinuxProcessError("private runtime directory identity changed")

    def _check_discovery(self):
        self._check_directory()
        discover = self.directory / f"makepad-remote-{self.pid}.json"
        socket = self.directory / f"makepad-remote-{self.pid}.sock"
        with os.fdopen(os.open(discover, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > 65536:
                raise LinuxProcessError("unexpected Makepad discovery file")
            raw = source.read(65537)
        if len(raw) > 65536:
            raise LinuxProcessError("oversized Makepad discovery file")
        record = json.loads(raw)
        if (not isinstance(record, dict) or type(record.get("pid")) is not int
                or record["pid"] != self.pid or record.get("socket") != str(socket)):
            raise LinuxProcessError("Makepad discovery does not match the owned guest/socket")
        info = socket.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise LinuxProcessError("Makepad socket is not a mode-0600 owned Unix socket")

    def _wait_discovery(self, timeout):
        deadline = time.monotonic() + timeout
        while True:
            self._guest.verify()
            try:
                self._check_discovery()
                return
            except (FileNotFoundError, json.JSONDecodeError):
                if time.monotonic() >= deadline:
                    raise LinuxProcessError("owned guest did not publish Makepad Remote discovery before timeout")
                time.sleep(0.025)

    def verify(self):
        """Revalidate the exact guest and its official Remote child before use."""
        if self._cleanup_started:
            raise LinuxProcessError("the owned demo session is closing or closed")
        identity = self._guest.verify()
        try:
            self._check_discovery()
        except (OSError, ValueError) as error:
            raise LinuxProcessError("owned Makepad Remote discovery is unavailable") from error
        if self._remote is not None:
            self._remote.verify()
        return identity

    def start_remote(self, remote):
        """Return the official client's binary stdio pipes, bound to this guest."""
        if self._remote is not None:
            raise LinuxProcessError("a Remote companion was already started for this session")
        self.verify()
        try:
            self._remote = _spawn(
                remote, ["mcp", str(self.pid)], cwd=self.directory, env=self._env,
                stdio=True, log=self.directory / "remote.stderr.log",
            )
            self._remote.bind()
            self.verify()
        except OSError as error:
            raise LinuxProcessError("could not start the pinned Makepad Remote companion") from error
        return self._remote.process

    def close(self, *, signal_owned=True):
        """Stop only verified owned children; retries merely reconcile exits."""
        if self._receipt is not None:
            return self._receipt.copy()
        signal_owned = signal_owned and not self._cleanup_started
        self._cleanup_started = True
        codes, issues = {}, []
        for name, child in (("remote", self._remote), ("guest", self._guest)):
            try:
                codes[name] = None if child is None else child.finish(signal_owned=signal_owned)
            except (OSError, LinuxProcessError, ValueError) as error:
                issues.append(f"{name}: {error}")
        if issues:
            raise LinuxProcessError(f"CLEANUP_PENDING at {self.directory}: " + "; ".join(issues))
        try:
            self._check_directory()
            shutil.rmtree(self.directory)
        except (OSError, LinuxProcessError) as error:
            raise LinuxProcessError(f"CLEANUP_PENDING at {self.directory}: {error}") from error
        self._receipt = {
            "cleanup": "CLOSED", "exit_code": codes["guest"], "guest_exit_code": codes["guest"],
            "remote_exit_code": codes["remote"], "directory_removed": True,
        }
        return self._receipt.copy()

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        try:
            self.close()
        except LinuxProcessError as cleanup:
            if error is None:
                raise
            error.add_note(str(cleanup))
