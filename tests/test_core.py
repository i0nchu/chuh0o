import json
import random
from dataclasses import replace

import pytest

from chuh0o.activity.modes import Activity, Mode, resolve
from chuh0o.core.behavior import Behavior, Event, State
from chuh0o.core.config import ConfigStore, Settings
from chuh0o.core.geometry import Area, covers_monitor, pet_menu_position


@pytest.mark.parametrize(
    "data",
    [
        {"scale": 0},
        {"speed": -10},
        {"tick_fps": 30},
        {"tick_fps": 10.5},
        {"scale": True},
        {"speed": float("nan")},
        {"scale": float("inf")},
        {"click_through": "false"},
        {"mode": "other"},
        [],
    ],
)
def test_bad_settings_rejected(data):
    with pytest.raises(ValueError):
        Settings.parse(data)


def test_settings_persistence_and_corrupt_recovery(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    chosen = replace(Settings(), scale=1.5, click_through=True, mode="focus")
    store.save(chosen)
    assert store.load() == chosen
    assert not (tmp_path / "config.tmp").exists()
    store.path.write_text("{broken", encoding="utf-8")
    assert store.load() == Settings()
    assert store.path.read_text() == "{broken"  # Do not destroy a user's damaged settings.


def test_defaults_and_unknown_future_keys(tmp_path):
    defaults = tmp_path / "defaults.json"
    defaults.write_text(json.dumps({"speed": 60, "future_feature": True}))
    assert ConfigStore(tmp_path / "missing.json", defaults).load().speed == 60


def test_visibility_reasons_restore_independently():
    settings = Settings()
    assert resolve(settings, Activity(True)).hidden
    assert not resolve(settings, Activity(False)).hidden
    assert resolve(settings, Activity(False), user_hidden=True).hidden
    assert resolve(settings, Activity(True), user_hidden=True).hidden
    assert resolve(settings, Activity(False), user_hidden=True).hidden


def test_manual_override_and_fullscreen_safety():
    manual = replace(Settings(), mode="normal")
    assert resolve(manual, Activity(False, 9999)).mode == Mode.NORMAL
    assert resolve(manual, Activity(True)).hidden
    assert not resolve(replace(manual, auto_hide_fullscreen=False), Activity(True)).hidden
    assert resolve(replace(manual, mode="game"), Activity()).hidden


def test_idle_sleep_does_not_change_mode_or_mouse_passthrough():
    awake = resolve(Settings(), Activity(False, 59.999))
    assert awake.mode == Mode.NORMAL and not awake.sleep_requested
    sleeping = resolve(Settings(), Activity(False, 60))
    assert sleeping.mode == Mode.NORMAL and sleeping.sleep_requested
    assert not sleeping.click_through and not sleeping.hidden
    assert resolve(Settings(), Activity(False, 9999)).mode == Mode.NORMAL
    assert resolve(Settings(), Activity(True, 400)).mode == Mode.GAME
    assert not resolve(Settings(), Activity(False, 0)).sleep_requested
    focused = resolve(replace(Settings(), mode="focus"), Activity())
    assert focused.sleep_requested and focused.click_through


def test_old_idle_focus_setting_is_ignored_without_discarding_other_preferences(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.path.write_text(json.dumps({"scale": 1.5, "idle_focus_minutes": 10}))
    settings = store.load()
    assert settings.scale == 1.5 and settings.mode == "auto"
    store.save(settings)
    assert "idle_focus_minutes" not in json.loads(store.path.read_text())


def test_drag_click_sleep_and_walk_transitions():
    behavior = Behavior(random.Random(3))
    behavior.enter(State.WALK, 5)
    behavior.direction = 1
    behavior.update(0.1)
    assert behavior.desired_velocity(40) == 40
    behavior.bounce()
    assert behavior.desired_velocity(40) == -40
    assert behavior.animation == "walk_left"
    behavior.begin_drag()
    behavior.update(100)
    assert behavior.desired_velocity(40) == 0 and behavior.state == State.DRAG
    behavior.end_drag()
    assert behavior.state == State.FALL
    behavior.dispatch(Event.LANDED)
    assert behavior.state == State.LAND
    behavior.update(0.31)
    assert behavior.state == State.IDLE
    behavior.click()
    assert behavior.animation == "wave"
    behavior.update(0.7)
    assert behavior.state == State.WAVE
    behavior.dispatch(Event.ANIMATION_FINISHED)
    assert behavior.state == State.IDLE
    behavior.set_sleep_requested(True)
    behavior.update(1)
    assert behavior.desired_velocity(40) == 0
    assert behavior.state == State.SLEEP
    behavior.set_sleep_requested(False)
    assert behavior.state == State.WAVE


def test_active_fsm_uses_predictable_movement_and_rest_without_random_sleep():
    behavior = Behavior(random.Random(42))
    seen = set()
    movements = []
    previous = behavior.state
    for _ in range(3000):
        behavior.update(0.1)
        seen.add(behavior.state)
        if previous != behavior.state and behavior.state in (State.WALK, State.JUMP):
            movements.append(behavior.state)
        previous = behavior.state
        if behavior.state in (State.JUMP, State.LIE_DOWN, State.GET_UP):
            behavior.dispatch(Event.ANIMATION_FINISHED)
    assert State.SLEEP not in seen
    assert {State.IDLE, State.WALK, State.JUMP, State.LIE_DOWN, State.LIE, State.GET_UP} <= seen
    assert movements[:4] == [State.WALK, State.WALK, State.JUMP, State.WALK]


def test_clamp_negative_monitor_and_taskbar_workarea():
    area = Area(-1920, -200, 1920, 1040)
    assert area.clamp(-2000, 2000, 144, 198) == (-1920, 642)
    assert area.clamp(500, -500, 144, 198) == (-144, -200)
    assert Area(0, 0, 100, 80).clamp(5, 5, 200, 200) == (0, 0)


def test_fullscreen_compares_monitor_not_workarea():
    monitor = (-1920, 0, 0, 1080)
    assert covers_monitor(monitor, monitor)
    assert covers_monitor((-1920, 0, 0, 1079), monitor)
    assert not covers_monitor((-1920, 0, 0, 1040), monitor)
    assert not covers_monitor((0, 0, 1920, 1080), monitor)


@pytest.mark.parametrize(
    "pet,work",
    [
        (Area(200, 600, 144, 198), Area(0, 0, 1200, 800)),
        (Area(1056, 602, 144, 198), Area(0, 0, 1200, 800)),
        (Area(-1920, -100, 144, 198), Area(-1920, -200, 1200, 800)),
        (Area(70, 602, 144, 198), Area(0, 0, 300, 800)),
    ],
)
def test_pet_menu_position_avoids_sprite_and_stays_in_workarea(pet, work):
    width, height = 180, 220
    x, y = pet_menu_position(pet, width, height, work, pet.y + 100)
    assert work.x <= x <= work.x + work.width - width
    assert work.y <= y <= work.y + work.height - height
    assert (
        x + width <= pet.x
        or x >= pet.x + pet.width
        or y + height <= pet.y
        or y >= pet.y + pet.height
    )
