import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    scale: float = 0.75
    speed: float = 45.0
    tick_fps: int = 10
    mode: str = "auto"
    click_through: bool = False
    auto_hide_fullscreen: bool = True

    @classmethod
    def parse(cls, data: dict) -> "Settings":
        if not isinstance(data, dict):
            raise ValueError("Settings must be a JSON object")
        values = asdict(cls())
        values.update({k: v for k, v in data.items() if k in values})
        for key, low, high in (
            ("scale", 0.5, 2),
            ("speed", 10, 150),
            ("tick_fps", 8, 12),
        ):
            value = values[key]
            if type(value) not in (int, float) or not low <= value <= high:
                raise ValueError(f"Invalid {key}: expected {low}–{high}")
        if type(values["tick_fps"]) is not int:
            raise ValueError("tick_fps must be an integer")
        for key in ("click_through", "auto_hide_fullscreen"):
            if type(values[key]) is not bool:
                raise ValueError(f"{key} must be boolean")
        if values["mode"] not in ("auto", "normal", "focus", "game"):
            raise ValueError("Unknown mode")
        return cls(**values)


class ConfigStore:
    def __init__(self, path: Path, defaults: Path | None = None):
        self.path = path
        self.defaults = defaults

    def load(self) -> Settings:
        source = self.path if self.path.exists() else self.defaults
        if source is None or not source.exists():
            return Settings()
        try:
            return Settings.parse(json.loads(source.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            log.exception("Cannot load settings from %s; using defaults", source)
            return Settings()

    def save(self, settings: Settings) -> None:
        Settings.parse(asdict(settings))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(asdict(settings), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(self.path)
