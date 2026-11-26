"""Portapapeles del sistema sin dependencias: API Win32 en Windows, wl-copy/xclip en Linux."""
import shutil
import subprocess

from . import IS_WINDOWS

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def _win():
    import ctypes
    from ctypes import wintypes

    u32 = ctypes.WinDLL("user32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    u32.OpenClipboard.argtypes = [wintypes.HWND]
    u32.GetClipboardData.restype = wintypes.HANDLE
    u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    u32.SetClipboardData.restype = wintypes.HANDLE
    k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k32.GlobalAlloc.restype = wintypes.HGLOBAL
    k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    return ctypes, u32, k32


def set_text(text):
    if IS_WINDOWS:
        ctypes, u32, k32 = _win()
        data = text.encode("utf-16-le") + b"\0\0"
        if not u32.OpenClipboard(None):
            return False
        try:
            u32.EmptyClipboard()
            h = k32.GlobalAlloc(GMEM_MOVEABLE, len(data))
            p = k32.GlobalLock(h)
            ctypes.memmove(p, data, len(data))
            k32.GlobalUnlock(h)
            return bool(u32.SetClipboardData(CF_UNICODETEXT, h))
        finally:
            u32.CloseClipboard()
    for argv in (["wl-copy"], ["xclip", "-selection", "clipboard"]):
        if shutil.which(argv[0]):
            return subprocess.run(argv, input=text.encode(), timeout=3).returncode == 0
    return False


def get_text():
    if IS_WINDOWS:
        ctypes, u32, k32 = _win()
        if not u32.OpenClipboard(None):
            return None
        try:
            h = u32.GetClipboardData(CF_UNICODETEXT)
            if not h:
                return ""
            p = k32.GlobalLock(h)
            try:
                return ctypes.wstring_at(p)
            finally:
                k32.GlobalUnlock(h)
        finally:
            u32.CloseClipboard()
    for argv in (["wl-paste", "-n"], ["xclip", "-selection", "clipboard", "-o"]):
        if shutil.which(argv[0]):
            r = subprocess.run(argv, capture_output=True, timeout=3)
            return r.stdout.decode(errors="replace") if r.returncode == 0 else None
    return None
