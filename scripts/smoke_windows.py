"""Native-window assertions and a local render snapshot; run outside pytest/offscreen."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import win32con
import win32gui
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from chuh0o.core.animator import SpriteBank
from chuh0o.core.config import ConfigStore, Settings
from chuh0o.core.controller import Controller
from chuh0o.paths import resource_root


def main():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    output = resource_root() / "qa-output"
    output.mkdir(exist_ok=True)
    controller = Controller(
        app,
        SpriteBank(resource_root() / "assets"),
        Settings(mode="normal", auto_hide_fullscreen=False),
        ConfigStore(output / "config.json"),
    )
    foreground_before = win32gui.GetForegroundWindow()
    controller.start()
    results = {}

    def verify():
        try:
            hwnd = int(controller.window.winId())
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            results["visible"] = controller.window.isVisible()
            results["tool_window"] = bool(style & win32con.WS_EX_TOOLWINDOW)
            results["no_activate"] = bool(style & win32con.WS_EX_NOACTIVATE)
            results["layered"] = bool(style & win32con.WS_EX_LAYERED)
            results["topmost"] = bool(style & win32con.WS_EX_TOPMOST)
            results["kept_foreground"] = foreground_before == win32gui.GetForegroundWindow()
            results["native_region"] = not controller.window.mask().isEmpty()
            controller.toggle_through()
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            results["passthrough_on"] = bool(style & win32con.WS_EX_TRANSPARENT)
            controller.toggle_through()
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            results["passthrough_off"] = not bool(style & win32con.WS_EX_TRANSPARENT)
            for name in controller.bank.clips:
                controller.animator.play(name)
                controller.window.set_frame(controller.animator.frame)
                controller.window.grab().save(str(output / f"{name}.png"))
            (output / "native-smoke.json").write_text(json.dumps(results, indent=2))
            print(json.dumps(results))
            if not all(results.values()):
                app.exit(1)
                return
            controller.quit()
        except Exception:
            import traceback

            traceback.print_exc()
            app.exit(1)

    QTimer.singleShot(700, verify)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
