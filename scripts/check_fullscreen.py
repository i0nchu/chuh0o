"""Exercise a separate real Win32 Qt window: maximized -> fullscreen -> normal."""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pywintypes
import win32gui
import win32process
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel

from chuh0o.core.animator import SpriteBank
from chuh0o.core.config import ConfigStore, Settings
from chuh0o.core.controller import Controller
from chuh0o.paths import resource_root


def fixture():
    app = QApplication([])
    window = QLabel("chuh0o fullscreen acceptance fixture — closes automatically")
    window.setWindowTitle("chuh0o · Fullscreen test")
    window.resize(640, 360)
    window.showMaximized()
    QTimer.singleShot(5000, window.showFullScreen)
    QTimer.singleShot(15000, window.showNormal)
    QTimer.singleShot(22000, app.quit)
    return app.exec()


def check():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    output = resource_root() / "qa-output"
    output.mkdir(exist_ok=True)
    controller = Controller(
        app,
        SpriteBank(resource_root() / "assets"),
        Settings(),
        ConfigStore(output / "fullscreen-config.json"),
    )
    controller.start()
    child = subprocess.Popen([sys.executable, __file__, "--fixture"])
    results = {
        "observed_fullscreen": False,
        "hidden_during_fullscreen": True,
        "animation_stopped": True,
        "restored_after_fullscreen": False,
        "fixture_foreground_seen": False,
    }

    def sample():
        controller.poll_activity()
        hwnd = win32gui.GetForegroundWindow()
        try:
            fixture_is_foreground = bool(hwnd) and (
                win32process.GetWindowThreadProcessId(hwnd)[1] == child.pid
            )
        except pywintypes.error:
            fixture_is_foreground = False  # The fixture can exit between inspection calls.
        results["fixture_foreground_seen"] |= fixture_is_foreground
        if fixture_is_foreground and controller.activity.fullscreen:
            results["observed_fullscreen"] = True
            results["hidden_during_fullscreen"] &= not controller.window.isVisible()
            results["animation_stopped"] &= not controller.render_timer.isActive()
        elif fixture_is_foreground and results["observed_fullscreen"]:
            results["restored_after_fullscreen"] |= controller.window.isVisible()
        if child.poll() is not None:
            timer.stop()
            controller.quit()

    timer = QTimer()
    timer.setInterval(100)
    timer.timeout.connect(sample)
    timer.start()
    QTimer.singleShot(27000, controller.quit)
    app.exec()
    child.wait(timeout=5)
    (output / "fullscreen-smoke.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results))
    if not results["fixture_foreground_seen"]:
        print("SKIP: leave the current fullscreen app and give the test window foreground focus.")
        return 2
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(fixture() if "--fixture" in sys.argv else check())
