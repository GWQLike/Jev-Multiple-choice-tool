"""Small Windows helpers; coordinates are physical virtual-desktop pixels."""

from __future__ import annotations

import ctypes
import logging
import os
from ctypes import wintypes
from functools import lru_cache
from typing import TYPE_CHECKING

from models import CaptureError, CaptureRegion

if TYPE_CHECKING:
    import tkinter as tk

_LOG = logging.getLogger(__name__)


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


@lru_cache(maxsize=1)
def _user32():
    if os.name != "nt":
        raise OSError("This application requires Windows.")
    api = ctypes.WinDLL("user32", use_last_error=True)
    api.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    api.GetCursorPos.restype = wintypes.BOOL
    api.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    api.MonitorFromPoint.restype = wintypes.HANDLE
    api.MonitorFromRect.argtypes = [ctypes.POINTER(wintypes.RECT), wintypes.DWORD]
    api.MonitorFromRect.restype = wintypes.HANDLE
    api.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MONITORINFO)]
    api.GetMonitorInfoW.restype = wintypes.BOOL
    api.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    api.GetAncestor.restype = wintypes.HWND
    api.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    api.SetWindowPos.restype = wintypes.BOOL
    api.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    api.ShowWindow.restype = wintypes.BOOL
    # The Ptr names are macros on 32-bit Windows, and exported on 64-bit Windows.
    ptr_suffix = "PtrW" if ctypes.sizeof(ctypes.c_void_p) == 8 else "W"
    get_style = getattr(api, "GetWindowLong" + ptr_suffix)
    set_style = getattr(api, "SetWindowLong" + ptr_suffix)
    get_style.argtypes = [wintypes.HWND, ctypes.c_int]
    get_style.restype = ctypes.c_ssize_t
    set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    set_style.restype = ctypes.c_ssize_t
    if hasattr(api, "GetDpiForWindow"):
        api.GetDpiForWindow.argtypes = [wintypes.HWND]
        api.GetDpiForWindow.restype = wintypes.UINT
    return api


def enable_dpi_awareness() -> None:
    """Call before creating Tk, MSS, or any screen-related resources."""
    api = _user32()
    if hasattr(api, "SetProcessDpiAwarenessContext"):
        setter = api.SetProcessDpiAwarenessContext
        setter.argtypes = [ctypes.c_void_p]
        setter.restype = wintypes.BOOL
        if setter(ctypes.c_void_p(-4)):  # PER_MONITOR_AWARE_V2
            return
        error = ctypes.get_last_error()
        if error == 5:  # The launcher or another library already set awareness.
            _LOG.debug("Process DPI awareness was already configured by the host.")
            return
        _LOG.warning(
            "Per-monitor V2 DPI awareness unavailable (Windows error %s).", error
        )
    try:
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        setter = shcore.SetProcessDpiAwareness
        setter.argtypes = [ctypes.c_int]
        setter.restype = ctypes.c_long
        result = setter(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        if result not in (0, -2147024891):  # S_OK or E_ACCESSDENIED (already set)
            _LOG.warning("Could not set per-monitor DPI awareness: HRESULT %s.", result)
    except (AttributeError, OSError):
        api.SetProcessDPIAware.argtypes = []
        api.SetProcessDPIAware.restype = wintypes.BOOL
        api.SetProcessDPIAware()


def _monitor_info(region: CaptureRegion | None = None) -> _MONITORINFO:
    api = _user32()
    if region is None:
        point = wintypes.POINT()
        if not api.GetCursorPos(ctypes.byref(point)):
            raise CaptureError("Windows could not read the cursor position.")
        monitor = api.MonitorFromPoint(point, 2)  # MONITOR_DEFAULTTONEAREST
    else:
        rect = wintypes.RECT(
            region.left,
            region.top,
            region.left + region.width,
            region.top + region.height,
        )
        monitor = api.MonitorFromRect(ctypes.byref(rect), 2)
    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(info)
    if not monitor or not api.GetMonitorInfoW(monitor, ctypes.byref(info)):
        raise CaptureError("Windows could not read monitor information.")
    return info


def _region_from_rect(rect: wintypes.RECT) -> CaptureRegion:
    return CaptureRegion(
        rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
    )


def monitor_at_cursor() -> CaptureRegion:
    return _region_from_rect(_monitor_info().rcMonitor)


def work_area_for_region(region: CaptureRegion | None = None) -> CaptureRegion:
    """Return the nearest monitor's work area, excluding its taskbar."""
    return _region_from_rect(_monitor_info(region).rcWork)


def window_handle(window: tk.Misc) -> int:
    """Tk's content HWND can differ from the outer top-level HWND."""
    handle = _user32().GetAncestor(window.winfo_id(), 2)  # GA_ROOT, not ROOTOWNER
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    return int(handle)


def configure_tool_window(window: tk.Misc, *, no_activate: bool) -> None:
    api = _user32()
    hwnd = window_handle(window)
    ptr_suffix = "PtrW" if ctypes.sizeof(ctypes.c_void_p) == 8 else "W"
    get_style = getattr(api, "GetWindowLong" + ptr_suffix)
    set_style = getattr(api, "SetWindowLong" + ptr_suffix)
    style = get_style(hwnd, -20)
    style = (style | 0x00000080) & ~0x00040000  # TOOLWINDOW, no APPWINDOW
    if no_activate:
        style |= 0x08000000  # NOACTIVATE
    else:
        style &= ~0x08000000
    ctypes.set_last_error(0)
    previous = set_style(hwnd, -20, style)
    if previous == 0 and ctypes.get_last_error():
        raise ctypes.WinError(ctypes.get_last_error())
    flags = 0x0001 | 0x0002 | 0x0004 | 0x0020
    if no_activate:
        flags |= 0x0010  # SWP_NOACTIVATE; selectors must be focusable.
    if not api.SetWindowPos(hwnd, None, 0, 0, 0, 0, flags):
        raise ctypes.WinError(ctypes.get_last_error())


def position_window(
    window: tk.Misc,
    region: CaptureRegion,
    *,
    no_activate: bool,
    show: bool = True,
) -> None:
    flags = 0x0200  # NOOWNERZORDER
    if no_activate:
        flags |= 0x0010
    if show:
        flags |= 0x0040
    if not _user32().SetWindowPos(
        window_handle(window),
        wintypes.HWND(-1),
        region.left,
        region.top,
        region.width,
        region.height,
        flags,
    ):
        raise ctypes.WinError(ctypes.get_last_error())


def show_without_activation(window: tk.Misc) -> None:
    # ShowWindow's return value reports previous visibility, not success/failure.
    _user32().ShowWindow(window_handle(window), 4)  # SW_SHOWNOACTIVATE


def dpi_for_window(window: tk.Misc) -> int:
    api = _user32()
    return (
        (api.GetDpiForWindow(window_handle(window)) or 96)
        if hasattr(api, "GetDpiForWindow")
        else 96
    )
