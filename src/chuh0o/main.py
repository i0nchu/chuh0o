import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from chuh0o.activity.updates import write_ready_marker
from chuh0o.core.animator import SpriteBank
from chuh0o.core.config import ConfigStore
from chuh0o.core.controller import Controller
from chuh0o.paths import data_root, resource_root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="chuh0o · 粉紅兔兔桌寵")
    parser.add_argument("--data-dir", type=Path, help="Override settings/log directory")
    parser.add_argument("--quit-after", type=float, help="Exit after N seconds (smoke testing)")
    parser.add_argument("--settings", action="store_true", help="Open settings on launch")
    parser.add_argument(
        "--demo-drop", action="store_true", help="Start above the floor to preview physics"
    )
    parser.add_argument("--dev-actions", action="store_true", help="Show source-only test actions")
    parser.add_argument("--update-ready-file", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    app = QApplication([sys.argv[0]])
    app.setApplicationName("chuh0o")
    app.setOrganizationName("chuh0o")
    app.setQuitOnLastWindowClosed(False)
    directory = args.data_dir or data_root()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            directory / "chuh0o.log", maxBytes=512_000, backupCount=2, encoding="utf-8"
        )
        logging.basicConfig(
            level=logging.INFO,
            handlers=[handler],
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        lock = QLockFile(str(directory / "chuh0o.lock"))
        lock.setStaleLockTime(0)
        if not lock.tryLock(100):
            logging.info("Another instance is already running")
            return 0
        if not QSystemTrayIcon.isSystemTrayAvailable():
            raise RuntimeError("找不到 Windows 系統匣，請在桌面工作階段啟動。")
        root = resource_root()
        store = ConfigStore(directory / "config.json", root / "config.json")
        controller = Controller(
            app,
            SpriteBank(root / "assets"),
            store.load(),
            store,
            development_actions=args.dev_actions and not getattr(sys, "frozen", False),
        )
        app.aboutToQuit.connect(lock.unlock)
        controller.start()
        if args.demo_drop:
            area = controller.area()
            floor = area.y + area.height - controller.window.height()
            controller.move_to(controller.physics.x, floor - min(360, max(0, (floor - area.y) / 2)))
        logging.info("chuh0o started")
        if args.update_ready_file is not None and getattr(sys, "frozen", False):

            def acknowledge_startup() -> None:
                try:
                    write_ready_marker(args.update_ready_file, directory)
                except (OSError, ValueError):
                    logging.exception("Cannot acknowledge updated startup")
                    controller.quit()

            QTimer.singleShot(800, acknowledge_startup)
        if args.settings:
            QTimer.singleShot(0, controller.open_settings)
        if args.quit_after is not None:
            QTimer.singleShot(max(1, round(args.quit_after * 1000)), controller.quit)
        return app.exec()
    except Exception as error:
        logging.exception("Startup failed")
        QMessageBox.critical(None, "chuh0o 無法啟動", f"{error}\n\n記錄檔：{directory}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
