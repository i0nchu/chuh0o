import logging
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QDialog

from chuh0o.activity.modes import Activity, resolve
from chuh0o.activity.updates import UpdateManager, installed_app_directory, launch_update_helper
from chuh0o.core.animator import Animator, SpriteBank
from chuh0o.core.behavior import Behavior, Event, State
from chuh0o.core.config import ConfigStore, Settings
from chuh0o.core.geometry import Area, pet_menu_position
from chuh0o.core.physics import PhysicsBody
from chuh0o.platform.windows.backend import WindowsBackend
from chuh0o.ui.pet_window import PetWindow
from chuh0o.ui.settings_dialog import SettingsDialog
from chuh0o.ui.tray import Tray

log = logging.getLogger(__name__)


class Controller(QObject):
    def __init__(
        self,
        app: QApplication,
        bank: SpriteBank,
        settings: Settings,
        store: ConfigStore,
        backend: WindowsBackend | None = None,
        clock: Callable[[], float] = monotonic,
        development_actions: bool = False,
    ):
        super().__init__(app)
        self.app, self.bank, self.settings, self.store = app, bank, settings, store
        self.backend = backend or WindowsBackend()
        self.clock = clock
        self.activity = Activity()
        self.user_hidden = False
        self.paused = False
        self._menu_open = False
        self.dialog: SettingsDialog | None = None
        self.behavior = Behavior(
            jump_durations={
                name: sum(bank.clips[name].durations) / 1000 for name in ("jump_left", "jump_right")
            }
        )
        self.physics = PhysicsBody()
        self.animator = Animator(bank.scaled(settings.scale))
        self._scale = settings.scale
        self.window = PetWindow()
        self.window.set_frame(self.animator.frame)
        self._through: bool | None = None
        self._last_tick = self.clock()
        self._animation_elapsed = 0.0
        self._animation_budget = 0.0
        self._screen = app.primaryScreen()
        self._connected_screens: set = set()
        self.updates = UpdateManager(
            store.path.parent, self, install_directory=installed_app_directory()
        )
        self.tray = Tray(
            QIcon(bank.clips["idle"].frames[0]),
            self.toggle_visible,
            self.toggle_pause,
            self.set_mode,
            self.toggle_through,
            self.open_settings,
            self.quit,
            perform_action=self.perform_action
            if development_actions and not getattr(sys, "frozen", False)
            else None,
            check_updates=self.updates.activate,
        )
        self.updates.changed.connect(self.tray.set_update_state)
        self.updates.ready.connect(self.apply_update)
        self.window.clicked.connect(self.click)
        self.window.drag_started.connect(self.begin_drag)
        self.window.drag_to.connect(self.drag_to)
        self.window.drag_finished.connect(self.end_drag)
        self.window.menu_requested.connect(self.show_pet_menu)
        self.tray.menu.aboutToShow.connect(self.menu_opened)
        self.tray.menu.aboutToHide.connect(self.menu_closed)
        self.render_timer = QTimer(self)
        self.render_timer.setTimerType(Qt.TimerType.CoarseTimer)
        self.render_timer.setInterval(33)  # ~30 Hz motion; animation sampling stays at 8–12 Hz.
        self.render_timer.timeout.connect(self.tick)
        self.activity_timer = QTimer(self)
        self.activity_timer.setInterval(1000)
        self.activity_timer.timeout.connect(self.poll_activity)
        app.screenAdded.connect(self.screen_added)
        app.screenRemoved.connect(self.screen_removed)
        for screen in app.screens():
            self.screen_added(screen)
        self.place_initially()
        self.policy = resolve(settings, self.activity)

    def start(self) -> None:
        self.tray.icon.show()
        # Inspect before showing, so launch during a game does not flash the pet.
        self.poll_activity()
        if not self.policy.sleep_requested:
            self.behavior.request_action("wave")
            self.sync_animation()
        self.activity_timer.start()

    def area(self) -> Area:
        screens = self.app.screens()
        if self._screen not in screens:
            self._screen = self.app.primaryScreen()
        rect = self._screen.availableGeometry()
        return Area(rect.x(), rect.y(), rect.width(), rect.height())

    def place_initially(self) -> None:
        area = self.area()
        self.move_to(area.x + area.width * 0.72, area.y + area.height - self.window.height())

    def screen_added(self, screen) -> None:
        if screen not in self._connected_screens:
            screen.availableGeometryChanged.connect(self.reclamp)
            screen.geometryChanged.connect(self.reclamp)
            self._connected_screens.add(screen)

    def screen_removed(self, screen) -> None:
        self._connected_screens.discard(screen)
        if self._screen is screen:
            self._screen = self.app.primaryScreen()
        self.reclamp()

    def reclamp(self, *_args) -> None:
        self.physics.stop()
        self.ensure_scale()
        self.physics.place(
            self.physics.x, self.physics.y, self.area(), self.window.width(), self.window.height()
        )
        self.sync_position()
        if not self.physics.dragging:
            self.behavior.dispatch(Event.LANDED if self.physics.grounded else Event.AIRBORNE)

    def move_to(self, x: float, y: float) -> None:
        self.ensure_scale()
        self.physics.place(x, y, self.area(), self.window.width(), self.window.height())
        self.sync_position()

    def ground_point(self) -> tuple[float, float]:
        ax, ay = self.animator.clip.ground_anchor
        return self.physics.x + ax, self.physics.y + ay

    def install_frame(self, ground: tuple[float, float]) -> None:
        previous_origin = self.window.pos()
        self.window.set_frame(self.animator.frame)
        ax, ay = self.animator.clip.ground_anchor
        self.physics.place(
            ground[0] - ax, ground[1] - ay, self.area(), self.window.width(), self.window.height()
        )
        self.sync_position()
        self.window.rebase_pointer(previous_origin)

    def ensure_scale(self) -> None:
        area = self.area()
        scale = min(
            self.settings.scale,
            area.width / self.bank.max_width,
            area.height / self.bank.max_height,
        )
        if abs(scale - self._scale) > 1e-9:
            ground = self.ground_point()
            self.animator.clips = self.bank.scaled(scale)
            self._scale = scale
            self.physics.stop()
            self.install_frame(ground)

    def sync_position(self) -> None:
        self.window.move(round(self.physics.x), round(self.physics.y))

    def sync_animation(self) -> None:
        name = self.behavior.animation
        repeat_jump = self.behavior.state == State.JUMP and self.animator.finished
        if name != self.animator.name or repeat_jump:
            gx, gy = self.ground_point()
            if self.animator.name.startswith("jump_") and name == "drag":
                # A grabbed mid-hop bunny keeps its visible feet position, not the baked arc floor.
                gy -= self.animator.clip.foot_lifts[self.animator.index]
            self.animator.play(name, restart=repeat_jump)
            self._animation_elapsed = 0
            self._animation_budget = 0
            self.install_frame((gx, gy))
            if self.physics.grounded and self.behavior.state != State.WALK:
                self.physics.stop()

    def refresh_action_context(self) -> None:
        gx, _ = self.ground_point()
        area = self.area()
        directions = []
        for direction, name in ((-1, "jump_left"), (1, "jump_right")):
            clip = self.animator.clips[name]
            x = gx - clip.ground_anchor[0]
            positions = [x]
            for dx, _ in clip.offsets:
                x += dx
                positions.append(x)
            if min(positions) >= area.x and max(positions) + clip.width <= area.x + area.width:
                directions.append(direction)
        self.behavior.jump_directions = tuple(directions)
        available = (
            self.physics.grounded
            and not self.paused
            and not self.policy.hidden
            and not self.policy.sleep_requested
        )
        self.tray.sync_actions(available, self.behavior.state.value, bool(directions))

    def perform_action(self, action: str) -> None:
        self.register_pointer_activity()
        self.refresh_action_context()
        if (
            not self.physics.grounded
            or self.paused
            or self.policy.hidden
            or self.policy.sleep_requested
        ):
            return
        self.behavior.request_action(action)
        self.sync_animation()
        self.refresh_action_context()

    def poll_activity(self) -> None:
        self.activity = self.backend.sample()
        self.apply_policy()

    def register_pointer_activity(self) -> None:
        # Local clicks/drags wake immediately instead of waiting for the next OS poll.
        self.activity = replace(self.activity, idle_seconds=0)
        self.apply_policy()

    def show_pet_menu(self, position: QPoint) -> None:
        self.register_pointer_activity()
        self.tray.menu.ensurePolished()
        size = self.tray.menu.sizeHint()
        frame = self.window.frameGeometry()
        pet = Area(frame.x(), frame.y(), frame.width(), frame.height())
        x, y = pet_menu_position(pet, size.width(), size.height(), self.area(), position.y())
        self.tray.menu.popup(QPoint(x, y))

    def menu_opened(self) -> None:
        self.updates.reset_menu()
        self._menu_open = True
        self.cancel_drag()
        self.apply_policy()

    def menu_closed(self) -> None:
        self._menu_open = False
        self.register_pointer_activity()

    def apply_policy(self) -> None:
        self.policy = resolve(self.settings, self.activity, self.user_hidden)
        if self.policy.hidden or self.policy.click_through:
            self.cancel_drag()
        self.behavior.set_sleep_requested(self.policy.sleep_requested)
        if self.behavior.state == State.SLEEP and self.physics.grounded:
            self.physics.stop()
        self.sync_animation()
        if self.policy.hidden:
            self.window.hide()
        else:
            self.window.show()
        # Qt may recreate a handle after a screen/style change; restyle after show.
        if not self._menu_open and (
            self._through != self.policy.click_through or not self.policy.hidden
        ):
            if not self.backend.available:
                self.window.setWindowFlag(
                    Qt.WindowType.WindowTransparentForInput, self.policy.click_through
                )
                self.window.setVisible(not self.policy.hidden)
            self.backend.configure_window(int(self.window.winId()), self.policy.click_through)
            self._through = self.policy.click_through
        should_run = not self.policy.hidden and not self.paused and not self._menu_open
        if should_run and not self.render_timer.isActive():
            self._last_tick = self.clock()
            self._animation_elapsed = 0
            self._animation_budget = 0
            self.render_timer.start()
        elif not should_run:
            self.render_timer.stop()
        self.tray.sync(self.settings, self.policy, self.user_hidden, self.paused)
        self.refresh_action_context()

    def tick(self) -> None:
        now = self.clock()
        dt = min(max(now - self._last_tick, 0), 0.1)
        self._last_tick = now
        if self.paused or self.policy.hidden or self._menu_open:
            return
        # Hold still between mouse-down and the drag threshold so the cursor keeps its grip.
        if not self.window.pointer_pressed or self.physics.dragging:
            self.refresh_action_context()
            if not self.physics.grounded and not self.physics.dragging:
                self.behavior.dispatch(Event.AIRBORNE)
            self.behavior.update(dt)
            self.sync_animation()
            contact = self.physics.advance(
                dt,
                self.area(),
                self.window.width(),
                self.window.height(),
                self.behavior.desired_velocity(self.settings.speed),
            )
            if contact.wall_hits % 2:
                self.behavior.bounce()
            if contact.landed:
                self.behavior.dispatch(Event.LANDED)
            self.sync_position()
        self.sync_animation()
        self._animation_elapsed += dt
        self._animation_budget += dt
        interval = 1 / self.settings.tick_fps
        if not self.animator.clip.loop or self._animation_budget + 1e-9 >= interval:
            changed = self.animator.advance(self._animation_elapsed * 1000)
            if self.behavior.state == State.JUMP:
                dx, dy = self.animator.motion
                self.physics.place(
                    self.physics.x + dx,
                    self.physics.y + dy,
                    self.area(),
                    self.window.width(),
                    self.window.height(),
                )
                self.sync_position()
            if changed:
                self.window.set_frame(self.animator.frame)
            self._animation_elapsed = 0
            self._animation_budget = max(0.0, self._animation_budget - interval)
            if self.animator.just_finished:
                # Each landing must check the next hop from its new position.
                self.refresh_action_context()
                self.behavior.dispatch(Event.ANIMATION_FINISHED)
                self.sync_animation()
                self.refresh_action_context()

    def click(self) -> None:
        self.register_pointer_activity()
        if not self.paused:
            self.behavior.click()
            self.sync_animation()

    def begin_drag(self) -> None:
        self.register_pointer_activity()
        self.physics.grab()
        self.behavior.begin_drag()
        if not self.paused:
            self.sync_animation()

    def drag_to(self, position: QPoint) -> None:
        cursor = position + self.window.drag_offset
        self._screen = QGuiApplication.screenAt(cursor) or self._screen
        self.ensure_scale()
        position = cursor - self.window.drag_offset
        self.move_to(position.x(), position.y())

    def end_drag(self) -> None:
        if not self.physics.dragging:
            return
        self.register_pointer_activity()
        self.physics.release()
        self.behavior.end_drag()
        if not self.paused:
            self.sync_animation()

    def cancel_drag(self) -> None:
        self.window.cancel_pointer()
        if self.physics.dragging:
            self.physics.release()
            self.behavior.end_drag()

    def toggle_visible(self) -> None:
        self.user_hidden = not self.user_hidden
        self.apply_policy()

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        self.apply_policy()

    def update_settings(self, settings: Settings) -> None:
        self.cancel_drag()
        old_scale = self.settings.scale
        self.settings = settings
        if old_scale != settings.scale:
            self.ensure_scale()
            self.reclamp()
        try:
            self.store.save(settings)
        except OSError:
            log.exception("Cannot save settings; changes apply for this session")
        self.apply_policy()

    def set_mode(self, mode: str) -> None:
        self.update_settings(replace(self.settings, mode=mode))

    def toggle_through(self) -> None:
        self.update_settings(replace(self.settings, click_through=not self.settings.click_through))

    def open_settings(self) -> None:
        if self.dialog is not None:
            self.dialog.raise_()
            self.dialog.activateWindow()
            return
        self.dialog = SettingsDialog(self.settings)
        self.dialog.finished.connect(self.finish_settings)
        self.dialog.show()
        self.dialog.activateWindow()  # Only an explicit user action opens a focused dialog.

    def finish_settings(self, result: int) -> None:
        dialog = self.dialog
        self.dialog = None
        if result == QDialog.DialogCode.Accepted:
            # Preserve a tray mode change made while the dialog was open.
            chosen = replace(dialog.settings(), mode=self.settings.mode)
            self.update_settings(chosen)
        dialog.deleteLater()

    def apply_update(self, plan: Path) -> None:
        try:
            self.store.save(self.settings)
            launch_update_helper(plan)
        except (OSError, ValueError) as error:
            log.exception("Cannot start update helper")
            self.updates.fail(str(error))
            return
        self.quit()

    def quit(self) -> None:
        self.updates.close()
        self.render_timer.stop()
        self.activity_timer.stop()
        self.tray.icon.hide()
        self.window.hide()
        self.app.quit()
