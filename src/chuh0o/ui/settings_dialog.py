from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSlider,
    QSpinBox,
    QStyleFactory,
    QVBoxLayout,
)

from chuh0o.core.config import Settings
from chuh0o.paths import resource_root


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings):
        super().__init__()
        self.original = settings
        self.setWindowTitle("chuh0o · 設定")
        self.setMinimumWidth(380)
        # Native dark-theme controls otherwise inherit white text on the pink surface.
        self._control_style = QStyleFactory.create("Fusion")
        self.setStyle(self._control_style)
        palette = QPalette()
        for role, color in (
            (QPalette.ColorRole.Window, "#fff8fb"),
            (QPalette.ColorRole.WindowText, "#4a3a3d"),
            (QPalette.ColorRole.Base, "#ffffff"),
            (QPalette.ColorRole.Text, "#4a3a3d"),
            (QPalette.ColorRole.Button, "#f6e7ed"),
            (QPalette.ColorRole.ButtonText, "#4a3a3d"),
            (QPalette.ColorRole.Highlight, "#bd6386"),
            (QPalette.ColorRole.HighlightedText, "#ffffff"),
        ):
            palette.setColor(role, QColor(color))
        self.setPalette(palette)
        self.setStyleSheet(
            """
            QDialog { background: #fff8fb; color: #4a3a3d; }
            QLabel { color: #4a3a3d; }
            QCheckBox { color: #4a3a3d; spacing: 8px; }
            QCheckBox::indicator {
                width: 14px; height: 14px; background: #ffffff;
                border: 1px solid #a98f9b; border-radius: 3px;
            }
            QCheckBox::indicator:checked {
                background: #bd6386; border-color: #bd6386; image: url(CHECK_ICON);
            }
            QComboBox, QSpinBox {
                color: #4a3a3d; background: #ffffff;
                border: 1px solid #cbb9c1; border-radius: 3px; padding: 4px;
            }
            QComboBox QAbstractItemView {
                color: #4a3a3d; background: #ffffff;
                selection-background-color: #f6d7e4; selection-color: #4a3a3d;
            }
            QPushButton {
                color: #4a3a3d; background: #f6e7ed;
                border: 1px solid #cbb9c1; border-radius: 4px; padding: 6px 16px;
            }
            QPushButton:hover { background: #f6d7e4; }
            QPushButton:focus { border: 1px solid #bd6386; }
        """.replace("CHECK_ICON", (resource_root() / "assets" / "check.svg").as_posix())
        )
        layout = QVBoxLayout(self)
        title = QLabel("粉紅兔兔的日常")
        title.setStyleSheet("font-size: 20px; font-weight: 600; padding: 8px 0;")
        layout.addWidget(title)
        form = QFormLayout()
        self.scale = QComboBox()
        for value in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0):
            self.scale.addItem(f"{value * 100:g}%", value)
        if self.scale.findData(settings.scale) < 0:
            self.scale.addItem(f"{settings.scale * 100:g}%", settings.scale)
        self.scale.setCurrentIndex(self.scale.findData(settings.scale))
        form.addRow("角色大小", self.scale)
        self.speed = QSlider(Qt.Orientation.Horizontal)
        self.speed.setRange(10, 150)
        self.speed.setValue(round(settings.speed))
        self.speed_label = QLabel()
        self.speed.valueChanged.connect(lambda value: self.speed_label.setText(f"{value} px/s"))
        self.speed_label.setText(f"{self.speed.value()} px/s")
        form.addRow("移動速度", self.speed)
        form.addRow("", self.speed_label)
        self.fps = QSpinBox()
        self.fps.setRange(8, 12)
        self.fps.setValue(settings.tick_fps)
        form.addRow("動畫取樣（FPS）", self.fps)
        self.through = QCheckBox("滑鼠穿透角色（可由系統匣關閉）")
        self.through.setChecked(settings.click_through)
        form.addRow(self.through)
        self.fullscreen = QCheckBox("全螢幕時自動隱藏")
        self.fullscreen.setChecked(settings.auto_hide_fullscreen)
        form.addRow(self.fullscreen)
        layout.addLayout(form)
        note = QLabel(
            "一般：自主活動　專注：睡眠與穿透　遊戲：隱藏\n"
            "一般模式：無輸入 1 分鐘就睡覺，有輸入便醒來。\n"
            "物理移動約 30 Hz；動畫保留素材的逐格時間。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #857e81; padding: 10px 0;")
        layout.addWidget(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("儲存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def settings(self) -> Settings:
        return replace(
            self.original,
            scale=self.scale.currentData(),
            speed=self.speed.value(),
            tick_fps=self.fps.value(),
            click_through=self.through.isChecked(),
            auto_hide_fullscreen=self.fullscreen.isChecked(),
        )
