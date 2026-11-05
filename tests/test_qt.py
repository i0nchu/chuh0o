from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QSignalSpy, QTest

from chuh0o.activity.modes import Activity
from chuh0o.core.animator import Animator, SpriteBank
from chuh0o.core.behavior import State
from chuh0o.core.config import ConfigStore, Settings
from chuh0o.core.controller import Controller
from chuh0o.ui.pet_window import PetWindow

ASSETS = Path(__file__).resolve().parents[1] / "assets"


class FakeBackend:
    available = True

    def __init__(self):
        self.activity = Activity()
        self.styles = []

    def sample(self):
        return self.activity

    def configure_window(self, hwnd, click_through):
        self.styles.append(click_through)


def make_controller(app, tmp_path):
    return Controller(
        app, SpriteBank(ASSETS), Settings(), ConfigStore(tmp_path / "config.json"), FakeBackend()
    )


def cleanup(controller):
    controller.updates.close()
    controller.tray.menu.close()
    controller.render_timer.stop()
    controller.activity_timer.stop()
    controller.tray.icon.hide()
    controller.window.hide()
    controller.window.deleteLater()
    controller.tray.menu.deleteLater()
    controller.deleteLater()


def test_real_asset_frames_timing_and_pixel_scale(app):
    bank = SpriteBank(ASSETS)
    assert len(bank.clips["sleep"].frames) == 8
    assert bank.clips["idle"].durations == (450, 450, 450, 180)
    animator = Animator(bank.scaled(0.75))
    assert animator.frame.size().toTuple() == (144, 198)
    assert not animator.advance(449)
    assert animator.advance(1) and animator.index == 1
    assert animator.advance(900) and animator.index == 3
    assert animator.advance(180) and animator.index == 0
    assert animator.play("sleep") and animator.index == 0
    assert not animator.play("sleep")
    animator.advance(260 * 8 + 260)
    assert animator.index == 1


def test_controller_visibility_pause_and_idle_sleep_restore(app, tmp_path):
    c = make_controller(app, tmp_path)
    try:
        c.apply_policy()
        assert c.window.isVisible() and c.render_timer.isActive()
        c.toggle_pause()
        assert not c.render_timer.isActive() and c.window.isVisible()
        c.backend.activity = Activity(True)
        c.poll_activity()
        assert not c.window.isVisible()
        c.backend.activity = Activity(False)
        c.poll_activity()
        assert c.window.isVisible() and not c.render_timer.isActive()
        c.toggle_visible()
        c.backend.activity = Activity(True)
        c.poll_activity()
        c.backend.activity = Activity(False)
        c.poll_activity()
        assert not c.window.isVisible()  # Fullscreen exit cannot undo explicit hiding.
        c.toggle_visible()
        c.toggle_pause()
        c.backend.activity = Activity(False, 400)
        c.poll_activity()
        assert c.behavior.state == State.SLEEP and not c.backend.styles[-1]
        c.backend.activity = Activity()
        c.poll_activity()
        assert c.behavior.state == State.WAVE and not c.backend.styles[-1]
    finally:
        cleanup(c)


def test_drag_clamp_resize_and_cancel_on_hide(app, tmp_path):
    c = make_controller(app, tmp_path)
    try:
        c.apply_policy()
        c.begin_drag()
        c.drag_to(QPoint(-100000, 100000))
        area = c.area()
        assert c.window.x() == area.x
        assert c.window.y() + c.window.height() <= area.y + area.height
        c.toggle_visible()
        assert c.behavior.state != State.DRAG
        c.update_settings(replace(c.settings, scale=2))
        assert c.window.x() + c.window.width() <= area.x + area.width
        assert c.window.y() + c.window.height() <= area.y + area.height
        assert not c.window.isVisible()
    finally:
        cleanup(c)


def test_pointer_distinguishes_click_and_drag(app):
    window = PetWindow()
    window.set_frame(SpriteBank(ASSETS).clips["idle"].frames[0])
    click = QSignalSpy(window.clicked)
    drag = QSignalSpy(window.drag_started)
    finish = QSignalSpy(window.drag_finished)
    window.show()
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=QPoint(96, 100))
    assert click.count() == 1 and drag.count() == 0
    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=QPoint(96, 100))
    origin = window.mapToGlobal(QPoint(96, 100))
    event = QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPoint(126, 130),
        origin + QPoint(30, 30),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    app.sendEvent(window, event)
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=QPoint(126, 130))
    assert drag.count() == 1 and finish.count() == 1 and click.count() == 1
    assert window.focusPolicy() == Qt.FocusPolicy.NoFocus
    window.hide()
    window.deleteLater()


def test_settings_save_and_cancel(app, tmp_path):
    c = make_controller(app, tmp_path)
    try:
        c.open_settings()
        dialog = c.dialog
        c.open_settings()
        assert c.dialog is dialog
        dialog.speed.setValue(70)
        dialog.scale.setCurrentIndex(dialog.scale.findData(1.25))
        dialog.through.setChecked(True)
        dialog.accept()
        assert c.dialog is None
        assert c.settings.speed == 70 and c.settings.scale == 1.25
        assert c.store.load() == c.settings
        c.open_settings()
        c.dialog.speed.setValue(20)
        c.dialog.reject()
        assert c.settings.speed == 70
    finally:
        cleanup(c)


def physics_controller(app, tmp_path):
    now = [0.0]
    c = Controller(
        app,
        SpriteBank(ASSETS),
        Settings(mode="normal"),
        ConfigStore(tmp_path / "config.json"),
        FakeBackend(),
        clock=lambda: now[0],
    )
    c.apply_policy()
    return c, now


def advance_controller(c, now, frames=1):
    for _ in range(frames):
        now[0] += 1 / 30
        c.tick()


def test_fast_drag_release_drops_straight_down_and_returns_to_idle(app, tmp_path):
    c, now = physics_controller(app, tmp_path)
    try:
        area = c.area()
        x, y = area.x + 120, area.y + 180
        c.move_to(x, y)
        c.begin_drag()
        now[0] = 0.05
        c.drag_to(QPoint(x + 30, y - 20))
        now[0] = 0.1
        c.drag_to(QPoint(x + 60, y - 40))
        c.end_drag()
        assert c.behavior.state == State.FALL
        assert c.physics.vx == c.physics.vy == 0
        release_x = c.physics.x
        states = set()
        for _ in range(200):
            advance_controller(c, now)
            states.add(c.behavior.state)
            assert c.physics.x == release_x
            assert c.window.y() >= area.y
            assert c.window.y() + c.window.height() <= area.y + area.height
            if State.LAND in states and c.behavior.state == State.IDLE:
                break
        assert {State.FALL, State.LAND, State.IDLE} <= states
        assert c.physics.grounded
    finally:
        cleanup(c)


def test_pausing_and_fullscreen_freeze_flight_without_catchup(app, tmp_path):
    c, now = physics_controller(app, tmp_path)
    try:
        area = c.area()
        c.move_to(area.x + 100, area.y + 100)
        c.begin_drag()
        c.end_drag()
        advance_controller(c, now)
        c.toggle_pause()
        snapshot = c.physics.x, c.physics.y, c.physics.vx, c.physics.vy
        now[0] += 3600
        c.tick()
        assert (c.physics.x, c.physics.y, c.physics.vx, c.physics.vy) == snapshot
        c.toggle_pause()
        advance_controller(c, now)
        assert 0 < c.physics.y - snapshot[1] < 10
        c.backend.activity = Activity(True)
        c.poll_activity()
        y = c.physics.y
        now[0] += 3600
        c.tick()
        assert c.physics.y == y and not c.window.isVisible()
        c.backend.activity = Activity()
        c.poll_activity()
        advance_controller(c, now)
        assert c.window.isVisible() and 0 < c.physics.y - y < 10
    finally:
        cleanup(c)


def test_focus_cancels_drag_and_waits_to_sleep_until_landed(app, tmp_path):
    c, now = physics_controller(app, tmp_path)
    try:
        area = c.area()
        c.begin_drag()
        now[0] = 0.1
        c.drag_to(QPoint(area.x + 150, area.y + 100))
        c.set_mode("focus")
        assert not c.physics.dragging and c.physics.vx == c.physics.vy == 0
        assert c.behavior.state == State.FALL and c.policy.click_through
        for _ in range(200):
            advance_controller(c, now)
            if c.behavior.state == State.SLEEP:
                break
        assert c.behavior.state == State.SLEEP and c.physics.grounded
        c.set_mode("normal")
        assert c.behavior.state == State.WAVE
    finally:
        cleanup(c)


def test_reclamp_onto_floor_finishes_fall_and_animation_setting_preserves_physics_rate(
    app, tmp_path
):
    c, now = physics_controller(app, tmp_path)
    try:
        c.begin_drag()
        c.end_drag()
        assert c.behavior.state == State.FALL
        c.update_settings(replace(c.settings, scale=2, tick_fps=8))
        assert c.physics.grounded and c.behavior.state == State.LAND
        assert c.render_timer.interval() == 33
        advance_controller(c, now, 10)
        assert c.behavior.state == State.IDLE
    finally:
        cleanup(c)


def test_animation_keeps_manifest_time_with_separate_physics_ticks(app, tmp_path):
    c, now = physics_controller(app, tmp_path)
    try:
        advance_controller(c, now, 30)
        assert c.animator.name == "idle" and c.animator.index == 2
        assert abs(c.animator.elapsed_ms - 100) < 1e-6
        assert c.physics.grounded and c.render_timer.interval() == 33
    finally:
        cleanup(c)


def test_os_inactivity_sleeps_until_new_input_without_enabling_passthrough(app, tmp_path):
    c, now = physics_controller(app, tmp_path)
    try:
        c.behavior.enter(State.WALK, 5)
        c.physics.vx = 45
        c.backend.activity = Activity(False, 59.999)
        c.poll_activity()
        assert c.behavior.state == State.WALK
        c.backend.activity = Activity(False, 60)
        c.poll_activity()
        assert c.behavior.state == State.SLEEP and c.physics.vx == 0
        assert not c.policy.click_through and c.policy.mode.value == "normal"
        advance_controller(c, now, 1500)
        assert c.behavior.state == State.SLEEP
        c.backend.activity = Activity(False, 600)
        c.poll_activity()
        assert c.behavior.state == State.SLEEP
        c.backend.activity = Activity(False, 0)
        c.poll_activity()
        assert c.behavior.state == State.WAVE
    finally:
        cleanup(c)


def test_click_wakes_immediately_without_waiting_for_os_poll(app, tmp_path):
    c, _ = physics_controller(app, tmp_path)
    try:
        c.backend.activity = Activity(False, 60)
        c.poll_activity()
        assert c.behavior.state == State.SLEEP
        c.click()
        assert c.behavior.state == State.WAVE and not c.policy.sleep_requested
    finally:
        cleanup(c)


def test_pet_menu_is_beside_sprite_and_suspends_motion_without_toggling_pause(app, tmp_path):
    c, now = physics_controller(app, tmp_path)
    try:
        c.behavior.enter(State.WALK, 5)
        point = c.window.mapToGlobal(QPoint(72, 100))
        c.window.menu_requested.emit(point)
        app.processEvents()
        assert c.tray.menu.isVisible() and c._menu_open
        assert not c.tray.menu.frameGeometry().intersects(c.window.frameGeometry())
        assert not c.paused and not c.render_timer.isActive()
        style_calls = len(c.backend.styles)
        x, y = c.physics.x, c.physics.y
        c.poll_activity()
        advance_controller(c, now, 30)
        assert (c.physics.x, c.physics.y) == (x, y)
        assert len(c.backend.styles) == style_calls  # Pet must not raise above open menus.
        c.tray.menu.close()
        assert not c._menu_open and c.render_timer.isActive() and not c.paused
        c.toggle_pause()
        c.show_pet_menu(point)
        c.tray.menu.close()
        assert c.paused and not c.render_timer.isActive()
    finally:
        cleanup(c)


def advance_until(c, now, state, limit=180):
    for _ in range(limit):
        if c.behavior.state == state:
            return
        advance_controller(c, now)
    raise AssertionError(f"Did not reach {state}, current state: {c.behavior.state}")


def test_lie_getup_wave_resize_preserves_floor_anchor_and_stays_stationary(app, tmp_path):
    c, now = physics_controller(app, tmp_path)
    try:
        area = c.area()
        c.move_to(area.x + 200, area.y + area.height - c.window.height())
        ground = c.ground_point()
        c.perform_action("lie")
        assert c.behavior.state == State.LIE_DOWN
        assert c.window.size().toTuple() == (216, 216)
        advance_until(c, now, State.LIE)
        assert c.window.size().toTuple() == (216, 120)
        assert c.ground_point() == ground and c.physics.grounded
        advance_controller(c, now, 30)
        c.perform_action("wave")
        assert c.behavior.state == State.GET_UP
        advance_until(c, now, State.WAVE)
        assert c.window.size().toTuple() == (168, 198)
        assert c.ground_point() == ground
        advance_until(c, now, State.IDLE)
        assert c.window.size().toTuple() == (144, 198)
        assert c.ground_point() == ground
    finally:
        cleanup(c)


def test_jump_translates_on_ground_plane_without_double_applying_vertical_arc(app, tmp_path):
    c, now = physics_controller(app, tmp_path)
    try:
        area = c.area()
        c.move_to(area.x + 200, area.y + area.height - c.window.height())
        c.behavior.direction = 1
        before_x, floor = c.ground_point()
        c.perform_action("jump")
        assert c.behavior.state == State.JUMP and c.window.height() == 258
        for _ in range(150):
            advance_controller(c, now)
            assert c.ground_point()[1] == floor and c.physics.grounded
            if c.behavior.state != State.JUMP:
                break
        assert c.behavior.state == State.IDLE
        assert abs(c.ground_point()[0] - before_x - 3 * 66) < 1e-6
        assert c.behavior.movements == 1
        assert c.window.height() == 198
    finally:
        cleanup(c)


def test_jump_near_right_edge_selects_left_and_lie_resize_stays_inside(app, tmp_path):
    c, now = physics_controller(app, tmp_path)
    try:
        area = c.area()
        c.move_to(area.x + area.width - c.window.width(), area.y + area.height - c.window.height())
        c.behavior.direction = 1
        c.perform_action("jump")
        assert c.animator.name == "jump_left"
        advance_until(c, now, State.IDLE)
        c.perform_action("lie")
        advance_until(c, now, State.LIE)
        index = c.animator.index
        c.update_settings(replace(c.settings, scale=1.25))
        assert c.animator.name.startswith("lie_") and c.animator.index == index
        assert c.window.width() == 360 and c.window.height() == 200
        assert c.window.x() >= area.x and c.window.y() >= area.y
        assert c.window.x() + c.window.width() <= area.x + area.width
        assert c.window.y() + c.window.height() <= area.y + area.height
        assert c.ground_point()[1] == area.y + area.height
    finally:
        cleanup(c)


def test_continuous_hops_turn_at_landing_and_take_the_same_time_as_walking(app, tmp_path):
    c, now = physics_controller(app, tmp_path)
    try:
        area = c.area()
        c.move_to(
            area.x + area.width - c.window.width() - 100,
            area.y + area.height - c.window.height(),
        )
        c.behavior.direction = 1
        before_x = c.ground_point()[0]
        c.perform_action("jump")
        clips = set()
        started = now[0]
        while c.behavior.state == State.JUMP and now[0] - started < 5:
            clips.add(c.animator.name)
            advance_controller(c, now)
            assert c.window.x() >= area.x
            assert c.window.x() + c.window.width() <= area.x + area.width
        jump_time = now[0] - started
        assert c.behavior.state == State.IDLE
        assert clips == {"jump_right", "jump_left"}
        assert abs(c.ground_point()[0] - before_x + 66) < 1e-6
        assert c.behavior.movements == 1
        c.behavior.enter(State.WALK)
        c.sync_animation()
        started = now[0]
        advance_until(c, now, State.IDLE)
        walk_time = now[0] - started
        assert abs(walk_time - 3.09) <= 1 / 30
        # Non-looping clips end on rendering ticks, so three landings can add three ticks.
        assert abs(jump_time - walk_time) <= 3 / 30 + 1e-9
        assert c.behavior.movements == 2
    finally:
        cleanup(c)


def test_grabbing_mid_jump_preserves_visible_height_and_releases_without_throw(app, tmp_path):
    c, now = physics_controller(app, tmp_path)
    try:
        c.perform_action("jump")
        while c.animator.index < 5:
            advance_controller(c, now)
        gx, gy = c.ground_point()
        lift = c.animator.clip.foot_lifts[c.animator.index]
        assert lift > 0
        c.begin_drag()
        assert c.behavior.state == State.DRAG
        assert c.ground_point() == (gx, gy - lift)
        c.end_drag()
        assert c.physics.vx == c.physics.vy == 0 and not c.physics.grounded
        advance_until(c, now, State.IDLE)
    finally:
        cleanup(c)


def test_idle_sleep_while_lying_gets_up_then_sleeps_and_new_input_greets(app, tmp_path):
    c, now = physics_controller(app, tmp_path)
    try:
        c.perform_action("lie")
        advance_until(c, now, State.LIE)
        ground = c.ground_point()
        c.backend.activity = Activity(False, 60)
        c.poll_activity()
        assert c.behavior.state == State.GET_UP
        advance_until(c, now, State.SLEEP)
        assert c.ground_point() == ground
        advance_controller(c, now, 300)
        assert c.behavior.state == State.SLEEP
        c.backend.activity = Activity(False, 0)
        c.poll_activity()
        assert c.behavior.state == State.WAVE
        advance_until(c, now, State.IDLE)
    finally:
        cleanup(c)


def test_drag_from_wide_lying_pose_rebases_cursor_without_teleporting(app, tmp_path):
    c, now = physics_controller(app, tmp_path)
    try:
        c.perform_action("lie")
        advance_until(c, now, State.LIE)
        ground = c.ground_point()
        local = QPoint(100, 60)
        origin = c.window.mapToGlobal(local)
        QTest.mousePress(c.window, Qt.MouseButton.LeftButton, pos=local)
        delta = QPoint(30, -30)
        move = QMouseEvent(
            QMouseEvent.Type.MouseMove,
            local + delta,
            origin + delta,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        app.sendEvent(c.window, move)
        assert c.behavior.state == State.DRAG
        assert c.ground_point() == (ground[0] + delta.x(), ground[1] + delta.y())
        release_point = origin + delta
        release = QMouseEvent(
            QMouseEvent.Type.MouseButtonRelease,
            c.window.mapFromGlobal(release_point),
            release_point,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        app.sendEvent(c.window, release)
        assert c.behavior.state == State.FALL and c.physics.vx == c.physics.vy == 0
    finally:
        cleanup(c)


def test_active_animation_program_reaches_hop_rest_and_getup_without_sleep(app, tmp_path):
    c, now = physics_controller(app, tmp_path)
    try:
        seen = set()
        area = c.area()
        for _ in range(2700):
            advance_controller(c, now)
            seen.add(c.behavior.state)
            assert c.window.x() >= area.x and c.window.y() >= area.y
            assert c.window.x() + c.window.width() <= area.x + area.width
            assert c.window.y() + c.window.height() <= area.y + area.height
        assert {State.IDLE, State.WALK, State.JUMP, State.LIE_DOWN, State.LIE, State.GET_UP} <= seen
        assert State.SLEEP not in seen
    finally:
        cleanup(c)


def test_jump_requested_while_lying_rechecks_direction_after_getup(app, tmp_path):
    c, now = physics_controller(app, tmp_path)
    try:
        area = c.area()
        c.move_to(area.x + area.width - c.window.width(), area.y + area.height - c.window.height())
        c.behavior.direction = 1
        c.perform_action("lie")
        advance_until(c, now, State.LIE)
        c.perform_action("jump")
        assert c.behavior.state == State.GET_UP
        advance_until(c, now, State.JUMP)
        assert c.animator.name == "jump_left"
        before_x = c.ground_point()[0]
        advance_until(c, now, State.IDLE)
        assert abs(c.ground_point()[0] - before_x + 3 * 66) < 1e-6
    finally:
        cleanup(c)
