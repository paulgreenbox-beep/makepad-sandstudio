"""Read-only Windows process binding for MSS-created native applications."""

import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import os


def process_identity(pid):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                               ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000 | 0x100000, False, pid)  # QUERY_LIMITED_INFORMATION + SYNCHRONIZE
    if not handle:
        raise OSError(ctypes.get_last_error(), 'Owned process identity unavailable')
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        size, session, exit_code = wintypes.DWORD(32768), wintypes.DWORD(), wintypes.DWORD()
        image = ctypes.create_unicode_buffer(size.value)
        if not (kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times))
                and kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size))
                and kernel.ProcessIdToSessionId(pid, ctypes.byref(session))
                and kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                and kernel.WaitForSingleObject(handle, 0) == 258):  # WAIT_TIMEOUT = not exited
            raise OSError(ctypes.get_last_error(), 'Owned process is not live and identifiable')
        return {'pid': pid, 'birth': (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime,
                'image': image.value, 'windows_session': session.value}
    finally:
        kernel.CloseHandle(handle)


def is_live(identity):
    try:
        current = process_identity(identity['pid'])
        return all(current[key] == identity[key] for key in ('pid', 'birth', 'windows_session'))
    except (OSError, KeyError, TypeError):
        return False


def birth_ticks(utc):
    whole, _, fraction = utc.rstrip('Z').partition('.')
    instant = datetime.strptime(whole, '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
    return int(instant.timestamp()) * 10_000_000 + 116444736000000000 + int((fraction + '0000000')[:7])


def confirm_app(identity, expected):
    current = process_identity(identity['app_pid'])
    if (current['birth'] != birth_ticks(identity['app_birth_utc'])
            or os.path.normcase(current['image']) != os.path.normcase(identity['app_image'])
            or (expected is not None and current != expected)):
        raise OSError('App PID, birth, image or Windows session changed')
    return current
