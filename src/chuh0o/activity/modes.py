from dataclasses import dataclass
from enum import StrEnum

from chuh0o.core.config import Settings

SLEEP_AFTER_SECONDS = 60


class Mode(StrEnum):
    NORMAL = "normal"
    FOCUS = "focus"
    GAME = "game"


@dataclass(frozen=True)
class Activity:
    fullscreen: bool = False
    idle_seconds: float = 0


@dataclass(frozen=True)
class Policy:
    mode: Mode
    hidden: bool
    click_through: bool
    sleep_requested: bool


def resolve(settings: Settings, activity: Activity, user_hidden: bool = False) -> Policy:
    if settings.mode != "auto":
        mode = Mode(settings.mode)
    elif activity.fullscreen:
        mode = Mode.GAME
    else:
        mode = Mode.NORMAL
    hidden = (
        user_hidden or mode == Mode.GAME or (settings.auto_hide_fullscreen and activity.fullscreen)
    )
    return Policy(
        mode,
        hidden,
        settings.click_through or mode == Mode.FOCUS,
        mode == Mode.FOCUS or activity.idle_seconds >= SLEEP_AFTER_SECONDS,
    )
