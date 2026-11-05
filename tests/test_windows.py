import ctypes
import os
import sys

import pytest

from chuh0o.activity.modes import Activity
from chuh0o.platform.windows import backend as native

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Win32 boundary")


@pytest.fixture
def windows(monkeypatch):
    backend = native.WindowsBackend()
    monkeypatch.setattr(native.win32gui, "GetForegroundWindow", lambda: 123)
    monkeypatch.setattr(native.win32gui, "IsWindowVisible", lambda hwnd: True)
    monkeypatch.setattr(native.win32gui, "IsIconic", lambda hwnd: False)
    monkeypatch.setattr(native.win32gui, "GetClassName", lambda hwnd: "TestWindow")
    monkeypatch.setattr(native.win32process, "GetWindowThreadProcessId", lambda hwnd: (1, 999999))
    monkeypatch.setattr(native.win32api, "MonitorFromWindow", lambda hwnd, flag: 456)
    monkeypatch.setattr(
        native.win32api,
        "GetMonitorInfo",
        lambda monitor: {"Monitor": (-1920, 0, 0, 1080), "Work": (-1920, 0, 0, 1040)},
    )
    monkeypatch.setattr(native.win32gui, "GetClientRect", lambda hwnd: (0, 0, 1920, 1080))
    monkeypatch.setattr(native.win32gui, "ClientToScreen", lambda hwnd, pt: (pt[0] - 1920, pt[1]))
    monkeypatch.setattr(native.win32gui, "GetWindowLong", lambda hwnd, flag: 0)

    class Dwm:
        def DwmGetWindowAttribute(self, hwnd, attribute, pointer, size):
            if attribute == 14:
                ctypes.cast(pointer, ctypes.POINTER(native.wintypes.DWORD))[0] = 0
            else:
                rect = ctypes.cast(pointer, ctypes.POINTER(native.wintypes.RECT)).contents
                rect.left, rect.top, rect.right, rect.bottom = -1920, 0, 0, 1080
            return 0

    backend.dwm = Dwm()
    return backend


def test_native_fullscreen_and_maximized_workarea(windows, monkeypatch):
    assert windows._fullscreen()
    monkeypatch.setattr(native.win32gui, "GetClientRect", lambda hwnd: (0, 0, 1920, 1040))
    monkeypatch.setattr(
        native.win32gui, "GetWindowLong", lambda hwnd, flag: native.win32con.WS_CAPTION
    )
    assert not windows._fullscreen()
    monkeypatch.setattr(native.win32gui, "GetWindowLong", lambda hwnd, flag: 0)
    assert windows._fullscreen()  # Borderless DWM fallback.


def test_native_shell_minimized_and_own_windows_ignored(windows, monkeypatch):
    monkeypatch.setattr(native.win32gui, "GetClassName", lambda hwnd: "Progman")
    assert not windows._fullscreen()
    monkeypatch.setattr(native.win32gui, "GetClassName", lambda hwnd: "TestWindow")
    monkeypatch.setattr(native.win32gui, "IsIconic", lambda hwnd: True)
    assert not windows._fullscreen()
    monkeypatch.setattr(native.win32gui, "IsIconic", lambda hwnd: False)
    monkeypatch.setattr(
        native.win32process, "GetWindowThreadProcessId", lambda hwnd: (1, os.getpid())
    )
    assert not windows._fullscreen()


def test_native_api_race_and_tick_wrap(windows, monkeypatch):
    monkeypatch.setattr(native.win32api, "GetTickCount", lambda: 500)
    monkeypatch.setattr(native.win32api, "GetLastInputInfo", lambda: 0xFFFFFF00)
    assert windows.sample().idle_seconds == 0.756

    def vanished():
        raise native.pywintypes.error(1400, "GetForegroundWindow", "Invalid window handle")

    monkeypatch.setattr(native.win32gui, "GetForegroundWindow", vanished)
    assert windows.sample() == Activity()


def test_native_styles_dont_activate_and_toggle_passthrough(windows, monkeypatch):
    styles, positions = [], []
    monkeypatch.setattr(
        native.win32gui,
        "GetWindowLong",
        lambda hwnd, key: (
            styles[-1]
            if styles
            else native.win32con.WS_EX_LAYERED | native.win32con.WS_EX_APPWINDOW
        ),
    )
    monkeypatch.setattr(
        native.win32gui, "SetWindowLong", lambda hwnd, key, value: styles.append(value)
    )
    monkeypatch.setattr(native.win32gui, "SetWindowPos", lambda *args: positions.append(args))
    windows.configure_window(123, True)
    assert styles[-1] & native.win32con.WS_EX_TRANSPARENT
    assert styles[-1] & native.win32con.WS_EX_NOACTIVATE
    assert styles[-1] & native.win32con.WS_EX_TOOLWINDOW
    assert not styles[-1] & native.win32con.WS_EX_APPWINDOW
    assert positions[-1][-1] & native.win32con.SWP_NOACTIVATE
    windows.configure_window(123, False)
    assert not styles[-1] & native.win32con.WS_EX_TRANSPARENT
    assert styles[-1] & native.win32con.WS_EX_LAYERED
