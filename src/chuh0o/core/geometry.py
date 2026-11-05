from dataclasses import dataclass


@dataclass(frozen=True)
class Area:
    x: int
    y: int
    width: int
    height: int

    def clamp(self, x: float, y: float, width: int, height: int) -> tuple[float, float]:
        return (
            min(max(x, self.x), self.x + max(0, self.width - width)),
            min(max(y, self.y), self.y + max(0, self.height - height)),
        )


def covers_monitor(
    rect: tuple[int, int, int, int], monitor: tuple[int, int, int, int], tolerance: int = 2
) -> bool:
    """Physical screen coordinates; edges may differ by a DWM rounding pixel."""
    return (
        rect[0] <= monitor[0] + tolerance
        and rect[1] <= monitor[1] + tolerance
        and rect[2] >= monitor[2] - tolerance
        and rect[3] >= monitor[3] - tolerance
    )


def pet_menu_position(
    pet: Area, menu_width: int, menu_height: int, work: Area, pointer_y: int, gap: int = 12
) -> tuple[int, int]:
    """Prefer beside the whole sprite; use above/below if neither side fits."""
    right_space = work.x + work.width - (pet.x + pet.width)
    left_space = pet.x - work.x
    y = pointer_y
    if right_space >= menu_width + gap:
        x = pet.x + pet.width + gap
    elif left_space >= menu_width + gap:
        x = pet.x - menu_width - gap
    elif pet.y - work.y >= menu_height + gap:
        x, y = pet.x, pet.y - menu_height - gap
    elif work.y + work.height - (pet.y + pet.height) >= menu_height + gap:
        x, y = pet.x, pet.y + pet.height + gap
    else:
        x = pet.x + pet.width + gap if right_space >= left_space else pet.x - menu_width - gap
    x, y = work.clamp(x, y, menu_width, menu_height)
    return round(x), round(y)
