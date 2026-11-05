import json
from dataclasses import dataclass
from math import isfinite
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QRegion


@dataclass(frozen=True)
class Clip:
    frames: tuple[QPixmap, ...]
    durations: tuple[int, ...]
    anchor: tuple[int, int]
    ground_anchor: tuple[int, int]
    loop: bool = True
    next_name: str | None = None
    offsets: tuple[tuple[float, float], ...] = ()
    foot_lifts: tuple[int, ...] = ()

    @property
    def width(self) -> int:
        return self.frames[0].width()

    @property
    def height(self) -> int:
        return self.frames[0].height()


class SpriteBank:
    def __init__(self, directory: Path):
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        self.clips = {}
        for name, spec in manifest["animations"].items():
            width = int(spec.get("frame_width", manifest.get("frame_width", 0)))
            height = int(spec.get("frame_height", manifest.get("frame_height", 0)))
            if width <= 0 or height <= 0:
                raise ValueError(f"Invalid frame dimensions: {name}")
            path = (directory / spec["file"]).resolve()
            if not path.is_relative_to(directory.resolve()):
                raise ValueError("Sprite path escapes asset directory")
            sheet = QPixmap(str(path))
            if sheet.isNull():
                raise ValueError(f"Cannot read sprite: {path}")
            frames = []
            for frame in spec["frames"]:
                x, y, w, h = (int(frame[key]) for key in ("x", "y", "w", "h"))
                if (
                    (w, h) != (width, height)
                    or x < 0
                    or y < 0
                    or x + w > sheet.width()
                    or y + h > sheet.height()
                ):
                    raise ValueError(f"Invalid sprite rectangle: {name}")
                frames.append(sheet.copy(x, y, w, h))
            durations = tuple(spec["frame_durations_ms"])
            if (
                not frames
                or len(frames) != len(durations)
                or any(type(v) is not int or v <= 0 for v in durations)
            ):
                raise ValueError(f"Invalid frame durations: {name}")
            anchor = spec.get("anchor", {"x": width // 2, "y": height})
            ax, ay = int(anchor["x"]), int(anchor["y"])
            if not 0 <= ax <= width or not 0 <= ay <= height:
                raise ValueError(f"Invalid anchor: {name}")
            offsets = tuple(
                (float(v["dx"]), float(v["dy"]))
                for v in spec.get("frame_offsets_px", [{"dx": 0, "dy": 0}] * len(frames))
            )
            if len(offsets) != len(frames) or any(
                not isfinite(v) for pair in offsets for v in pair
            ):
                raise ValueError(f"Invalid frame motion: {name}")
            loop = spec.get("loop", True)
            if type(loop) is not bool:
                raise ValueError(f"Invalid loop flag: {name}")
            # Drag's manifest anchor is the grip point, not a floor anchor.
            ground_anchor = (width // 2, height) if name == "drag" else (ax, ay)
            lifts = tuple(
                height - (QRegion(frame.mask()).boundingRect().bottom() + 1) for frame in frames
            )
            self.clips[name] = Clip(
                tuple(frames),
                durations,
                (ax, ay),
                ground_anchor,
                loop,
                spec.get("next"),
                offsets,
                lifts,
            )
        required = {"idle", "wave", "drag", "sleep"} | {
            f"{animation}_{side}"
            for animation in ("walk", "jump", "liedown", "lie", "getup")
            for side in ("left", "right")
        }
        for name in sorted(required):
            if name not in self.clips:
                raise ValueError(f"Missing required animation: {name}")
        for name, clip in self.clips.items():
            if clip.next_name is not None and clip.next_name not in self.clips:
                raise ValueError(f"Unknown next animation: {name}")
        self.width, self.height = self.clips["idle"].width, self.clips["idle"].height
        self.max_width = max(clip.width for clip in self.clips.values())
        self.max_height = max(clip.height for clip in self.clips.values())

    def scaled(self, scale: float) -> dict[str, Clip]:
        return {
            name: Clip(
                tuple(
                    frame.scaled(
                        max(1, round(clip.width * scale)),
                        max(1, round(clip.height * scale)),
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.FastTransformation,
                    )
                    for frame in clip.frames
                ),
                clip.durations,
                tuple(round(v * scale) for v in clip.anchor),
                tuple(round(v * scale) for v in clip.ground_anchor),
                clip.loop,
                clip.next_name,
                tuple((dx * scale, dy * scale) for dx, dy in clip.offsets),
                tuple(round(v * scale) for v in clip.foot_lifts),
            )
            for name, clip in self.clips.items()
        }


class Animator:
    def __init__(self, clips: dict[str, Clip]):
        self.clips = clips
        self.name = "idle"
        self.index = 0
        self.elapsed_ms = 0.0
        self.finished = False
        self.just_finished = False
        self.motion = (0.0, 0.0)

    @property
    def clip(self) -> Clip:
        return self.clips[self.name]

    @property
    def frame(self) -> QPixmap:
        return self.clips[self.name].frames[self.index]

    def play(self, name: str, *, restart: bool = False) -> bool:
        if name == self.name and not restart:
            return False
        self.name, self.index, self.elapsed_ms = name, 0, 0.0
        self.finished = self.just_finished = False
        self.motion = self.clip.offsets[0]
        return True

    def advance(self, elapsed_ms: float) -> bool:
        clip = self.clip
        self.just_finished = False
        self.motion = (0.0, 0.0)
        if self.finished:
            return False
        self.elapsed_ms += max(0, elapsed_ms)
        previous = self.index
        while self.elapsed_ms >= clip.durations[self.index]:
            self.elapsed_ms -= clip.durations[self.index]
            if self.index == len(clip.frames) - 1 and not clip.loop:
                self.finished = self.just_finished = True
                self.elapsed_ms = 0
                break
            self.index = (self.index + 1) % len(clip.frames)
            dx, dy = clip.offsets[self.index]
            self.motion = self.motion[0] + dx, self.motion[1] + dy
        return self.index != previous
