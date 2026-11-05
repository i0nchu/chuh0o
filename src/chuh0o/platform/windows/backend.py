"""Small Win32 boundary. Qt coordinates never mix with native physical coordinates."""

import ctypes
import logging
import os
import sys
from ctypes import wintypes

from chuh0o.activity.modes import Activity
from chuh0o.core.geometry import covers_monitor

log = logging.getLogger(__name__)

if sys.platform == "win32":
    import pywintypes
    import win32api
    import win32con
    import win32gui
    import win32process


class WindowsBackend:
    def __init__(self):
        self.available = sys.platform == "win32"
        self._failure_logged = False
        if self.available:
            self.dwm = ctypes.WinDLL("dwmapi")
            self.dwm.DwmGetWindowAttribute.argtypes = (
                wintypes.HWND,
                wintypes.DWORD,
                ctypes.c_void_p,
                wintypes.DWORD,
            )
            self.dwm.DwmGetWindowAttribute.restype = ctypes.c_long

    def configure_window(self, hwnd: int, click_through: bool) -> None:
        if not self.available:
            return
        try:
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            style |= win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_NOACTIVATE
            style &= ~win32con.WS_EX_APPWINDOW
            if click_through:
                style |= win32con.WS_EX_TRANSPARENT | win32con.WS_EX_LAYERED
            else:
                style &= ~win32con.WS_EX_TRANSPARENT
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style)
            win32gui.SetWindowPos(
                hwnd,
                win32con.HWND_TOPMOST,
                0,
                0,
                0,
                0,
                win32con.SWP_NOMOVE
                | win32con.SWP_NOSIZE
                | win32con.SWP_NOACTIVATE
                | win32con.SWP_FRAMECHANGED,
            )
        except pywintypes.error:
            log.exception("Cannot update desktop pet window styles")

    def sample(self) -> Activity:
        if not self.available:
            return Activity()
        try:
            # Both values are DWORD milliseconds; subtraction handles the 49.7-day wrap.
            idle = ((win32api.GetTickCount() - win32api.GetLastInputInfo()) & 0xFFFFFFFF) / 1000
            return Activity(self._fullscreen(), idle)
        except (pywintypes.error, OSError):
            # Foreground windows can disappear between any two Win32 calls.
            if not self._failure_logged:
                log.warning("Activity inspection failed; will retry", exc_info=True)
                self._failure_logged = True
            return Activity()

    def _fullscreen(self) -> bool:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd or not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
            return False
        if win32process.GetWindowThreadProcessId(hwnd)[1] == os.getpid():
            return False
        if win32gui.GetClassName(hwnd) in (
            "Progman",
            "WorkerW",
            "Shell_TrayWnd",
            "Shell_SecondaryTrayWnd",
        ):
            return False
        cloaked = wintypes.DWORD()
        result = self.dwm.DwmGetWindowAttribute(
            hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
        )
        if result == 0 and cloaked.value:
            return False
        monitor = win32api.GetMonitorInfo(win32api.MonitorFromWindow(hwnd, 2))["Monitor"]
        client = win32gui.GetClientRect(hwnd)
        top_left = win32gui.ClientToScreen(hwnd, client[:2])
        bottom_right = win32gui.ClientToScreen(hwnd, client[2:])
        if covers_monitor((*top_left, *bottom_right), monitor):
            return True
        # DWM excludes invisible resize borders, avoiding maximized-window false positives.
        bounds = wintypes.RECT()
        result = self.dwm.DwmGetWindowAttribute(
            hwnd, 9, ctypes.byref(bounds), ctypes.sizeof(bounds)
        )
        caption = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE) & win32con.WS_CAPTION
        return (
            result == 0
            and not caption
            and covers_monitor((bounds.left, bounds.top, bounds.right, bounds.bottom), monitor)
        )
