from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QIcon, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from chuh0o.activity.modes import Policy
from chuh0o.core.config import Settings

MODE_LABELS = {"auto": "自動切換", "normal": "一般", "focus": "專注", "game": "遊戲"}

UPDATE_LABELS = {
    "ready": "檢查更新",
    "checking": "檢查中…",
    "available": "更新",
    "current": "已為最新版本",
    "no_release": "尚無發布版本",
    "error": "檢查失敗，請重試",
    "update_error": "更新失敗，請重試",
    "downloading": "下載中…",
    "preparing": "準備更新…",
    "installing": "正在更新…",
    "development": "請使用發布版更新",
}


class PetMenu(QMenu):
    """The update row keeps the menu open so asynchronous results are visible."""

    persistent_action: QAction | None = None

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        action = self.actionAt(event.position().toPoint())
        if (
            event.button() == Qt.MouseButton.LeftButton
            and action is not None
            and action is self.persistent_action
        ):
            if action.isEnabled():
                action.trigger()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space)
            and self.persistent_action is not None
            and self.activeAction() is self.persistent_action
        ):
            if self.persistent_action is not None and self.persistent_action.isEnabled():
                self.persistent_action.trigger()
            event.accept()
            return
        super().keyPressEvent(event)


class Tray:
    def __init__(
        self,
        icon: QIcon,
        toggle_visible: Callable,
        toggle_pause: Callable,
        set_mode: Callable,
        toggle_through: Callable,
        settings: Callable,
        quit_app: Callable,
        perform_action: Callable | None = None,
        check_updates: Callable | None = None,
    ):
        self.icon = QSystemTrayIcon(icon)
        self.menu = PetMenu()
        self.menu.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.status = self.menu.addAction("chuh0o")
        self.status.setEnabled(False)
        self.menu.addSeparator()
        self.visibility = self.menu.addAction("隱藏", toggle_visible)
        self.pause = self.menu.addAction("暫停", toggle_pause)
        self.pause.setCheckable(True)
        self.actions = {}
        if perform_action is not None:
            actions = self.menu.addMenu("動作")
            actions.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            for key, label in (("wave", "打招呼"), ("lie", "側躺／起身"), ("jump", "跳躍")):
                action = actions.addAction(label)
                action.triggered.connect(lambda checked=False, name=key: perform_action(name))
                self.actions[key] = action
        modes = self.menu.addMenu("運行模式")
        modes.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.group = QActionGroup(modes)
        self.mode_actions = {}
        for key, label in MODE_LABELS.items():
            action = QAction(label, modes, checkable=True)
            action.triggered.connect(lambda checked=False, mode=key: set_mode(mode))
            self.group.addAction(action)
            modes.addAction(action)
            self.mode_actions[key] = action
        self.through = self.menu.addAction("滑鼠穿透", toggle_through)
        self.through.setCheckable(True)
        self.menu.addSeparator()
        self.menu.addAction("設定…", settings)
        self.update = self.menu.addAction("檢查更新")
        if check_updates is not None:
            self.update.triggered.connect(check_updates)
        self.menu.persistent_action = self.update
        self.menu.addSeparator()
        self.menu.addAction("退出", quit_app)
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(
            lambda reason: (
                toggle_visible() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None
            )
        )

    def sync(self, settings: Settings, policy: Policy, user_hidden: bool, paused: bool) -> None:
        state = MODE_LABELS[policy.mode.value]
        if settings.mode == "auto":
            state += "（自動）"
        if policy.hidden:
            state += " · 已隱藏"
        if paused:
            state += " · 已暫停"
        self.status.setText("chuh0o · " + state)
        self.icon.setToolTip("chuh0o · " + state)
        self.visibility.setText("顯示" if user_hidden else "隱藏")
        self.pause.setChecked(paused)
        self.pause.setText("繼續活動" if paused else "暫停")
        self.mode_actions[settings.mode].setChecked(True)
        self.through.setChecked(policy.click_through)
        self.through.setEnabled(policy.mode.value != "focus")
        self.through.setText("滑鼠穿透（專注模式）" if policy.mode.value == "focus" else "滑鼠穿透")

    def sync_actions(self, available: bool, state: str, can_jump: bool) -> None:
        for key, action in self.actions.items():
            action.setEnabled(available and (key != "jump" or (can_jump and state != "jump")))
        if self.actions:
            self.actions["lie"].setText(
                "起身" if state in ("lie", "lie_down", "get_up") else "側躺"
            )
            self.actions["lie"].setEnabled(available and state != "get_up")

    def set_update_state(self, state: str, message: str = "") -> None:
        label = UPDATE_LABELS[state]
        if state == "downloading" and message.isdecimal():
            label = f"下載中… {message}%"
        self.update.setText(label)
        self.update.setToolTip(message if state != "downloading" else "")
        self.update.setEnabled(
            state in ("ready", "available", "error", "update_error", "no_release", "development")
        )
