import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication

root = Path(__file__).resolve().parents[1]
app = QApplication(sys.argv)
source = QPixmap(str(root / "assets" / "idle.png")).copy(0, 0, 192, 264)
icon = QIcon()
for size in (16, 24, 32, 48, 64, 128, 256):
    icon.addPixmap(
        source.scaled(
            size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation
        )
    )
if not icon.pixmap(256, 256).save(str(root / "assets" / "bunny.ico"), "ICO"):
    raise SystemExit("Could not save icon")
