"""Read-only Windows PID/parent snapshots for owned-process lifecycle tests."""

import ctypes
from ctypes import wintypes
import os


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
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error())
    try:
        entry = Entry(); entry.dwSize = ctypes.sizeof(entry)
        result = {}
        active = kernel.Process32FirstW(handle, ctypes.byref(entry))
        while active:
            result[int(entry.pid)] = (int(entry.parent), entry.exe) if with_names else int(entry.parent)
            active = kernel.Process32NextW(handle, ctypes.byref(entry))
        return result
    finally:
        kernel.CloseHandle(handle)


def descendants(pid, tree):
    found = set()
    pending = [pid]
    while pending:
        parent = pending.pop()
        children = {child for child, owner in tree.items() if owner == parent} - found
        found.update(children)
        pending.extend(children)
    return found
