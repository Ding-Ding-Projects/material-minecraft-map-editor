"""Read-only Windows PID/parent snapshots for owned-process lifecycle tests."""

import ctypes
from ctypes import wintypes
import os
import sys

ERROR_NO_MORE_FILES = 18
MAX_PROCESS_ENTRIES = 65536


def snapshot(with_names=False):
    if os.name != "nt":
        raise RuntimeError("Windows process snapshot required for this test")

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("pid", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                    ("parent", wintypes.DWORD), ("priority", wintypes.LONG),
                    ("flags", wintypes.DWORD), ("exe", wintypes.WCHAR * 260)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.Process32FirstW.restype = wintypes.BOOL
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.Process32NextW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    ctypes.set_last_error(0)
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle in (None, 0, ctypes.c_void_p(-1).value):
        raise OSError(ctypes.get_last_error(), "CreateToolhelp32Snapshot failed")
    try:
        entry = Entry(); entry.dwSize = ctypes.sizeof(entry)
        result = {}
        ctypes.set_last_error(0)
        active = kernel.Process32FirstW(handle, ctypes.byref(entry))
        if not active and ctypes.get_last_error() != ERROR_NO_MORE_FILES:
            raise OSError(ctypes.get_last_error(), "Process32FirstW did not produce a complete inventory")
        while active:
            pid = int(entry.pid)
            if pid in result or len(result) >= MAX_PROCESS_ENTRIES:
                raise RuntimeError("Process snapshot contains duplicate identities or exceeds its bound")
            result[pid] = (int(entry.parent), entry.exe) if with_names else int(entry.parent)
            ctypes.set_last_error(0)
            active = kernel.Process32NextW(handle, ctypes.byref(entry))
            if not active and ctypes.get_last_error() != ERROR_NO_MORE_FILES:
                raise OSError(ctypes.get_last_error(), "Process32NextW stopped before a complete inventory")
        if os.getpid() not in result:
            raise RuntimeError("Complete process inventory did not observe its own running process")
        return result
    finally:
        already_raising = sys.exc_info()[0] is not None
        ctypes.set_last_error(0)
        if not kernel.CloseHandle(handle) and not already_raising:
            raise OSError(ctypes.get_last_error(), "Process snapshot handle release failed")


def descendants(pid, tree):
    """Reachability in this completed snapshot, not historical orphan proof.

    A process whose intermediate parent exited before observation may not have
    a chain back to pid in this inventory. Do not relabel this as job-tree
    containment or evidence that no descendant ever existed.
    """
    found = set()
    pending = [pid]
    while pending:
        parent = pending.pop()
        children = {child for child, owner in tree.items() if owner == parent} - found
        found.update(children)
        pending.extend(children)
    return found


def process_identity(pid):
    """Read creation time and image path from one live, query-only handle."""
    if os.name != "nt" or type(pid) is not int or not 1 <= pid <= 2**32 - 1:
        raise ValueError("A native process identifier is required")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    ctypes.set_last_error(0)
    handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        raise OSError(ctypes.get_last_error(), "Owned process identity is unavailable")
    try:
        creation, exited, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
        ctypes.set_last_error(0)
        if not kernel.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exited),
                                      ctypes.byref(kernel_time), ctypes.byref(user_time)):
            raise OSError(ctypes.get_last_error(), "Owned process creation time is unavailable")
        created = (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)
        if created == 0:
            raise RuntimeError("Owned process creation time is invalid")
        capacity = 32768
        buffer = ctypes.create_unicode_buffer(capacity)
        length = wintypes.DWORD(capacity)
        ctypes.set_last_error(0)
        if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
            raise OSError(ctypes.get_last_error(), "Owned process executable identity is unavailable")
        if not 0 < length.value < capacity or not buffer.value:
            raise RuntimeError("Owned process executable identity is invalid")
        return {"pid": pid, "creationTimeFileTime": created, "imagePath": buffer.value}
    finally:
        already_raising = sys.exc_info()[0] is not None
        ctypes.set_last_error(0)
        if not kernel.CloseHandle(handle) and not already_raising:
            raise OSError(ctypes.get_last_error(), "Owned process query handle release failed")
