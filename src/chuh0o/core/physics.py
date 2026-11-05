"""Fixed-step desktop physics in Qt logical pixels, independent of rendering and Win32."""

from dataclasses import dataclass
from math import exp

from chuh0o.core.geometry import Area


@dataclass(frozen=True)
class PhysicsSettings:
    gravity: float = 1800.0  # logical pixels / second²
    restitution: float = 0.32
    wall_restitution: float = 0.45
    minimum_bounce_speed: float = 85.0
    ground_friction: float = 1100.0
    walk_acceleration: float = 650.0
    air_drag: float = 0.25
    fixed_step: float = 1 / 120


@dataclass
class Contact:
    wall_hits: int = 0
    landed: bool = False
    impacts: int = 0


def approach(value: float, target: float, amount: float) -> float:
    return min(value + amount, target) if value < target else max(value - amount, target)


class PhysicsBody:
    def __init__(self, settings: PhysicsSettings | None = None):
        self.settings = settings or PhysicsSettings()
        self.x = self.y = self.vx = self.vy = 0.0
        self.grounded = False
        self.dragging = False
        self._accumulator = 0.0

    def place(self, x: float, y: float, area: Area, width: int, height: int) -> None:
        self.x, self.y = area.clamp(x, y, width, height)
        floor = area.y + max(0, area.height - height)
        self.grounded = not self.dragging and abs(self.y - floor) < 0.01 and self.vy >= 0

    def stop(self) -> None:
        self.vx = self.vy = 0
        self._accumulator = 0

    def grab(self) -> None:
        self.stop()
        self.dragging = True
        self.grounded = False

    def release(self) -> None:
        self.dragging = False
        self.grounded = False
        self.stop()  # Always drop from rest, independent of cursor movement or prior momentum.

    def advance(
        self, elapsed: float, area: Area, width: int, height: int, desired_vx: float = 0
    ) -> Contact:
        contact = Contact()
        if self.dragging:
            return contact
        # Discard a long stall rather than replaying a large catch-up after suspend/debugging.
        self._accumulator += min(max(elapsed, 0), 0.1)
        step = self.settings.fixed_step
        while self._accumulator + 1e-10 >= step:
            self._accumulator -= step
            hit = self._step(step, area, width, height, desired_vx)
            contact.wall_hits += hit.wall_hits
            contact.landed |= hit.landed
            contact.impacts += hit.impacts
            if hit.wall_hits % 2:
                desired_vx = -desired_vx
        return contact

    def _step(self, dt: float, area: Area, width: int, height: int, desired_vx: float) -> Contact:
        contact = Contact()
        settings = self.settings
        left, top = area.x, area.y
        right = left + max(0, area.width - width)
        floor = top + max(0, area.height - height)
        was_grounded = self.grounded
        self.grounded = self.grounded and abs(self.y - floor) < 0.01 and self.vy >= 0
        if self.grounded:
            acceleration = settings.walk_acceleration if desired_vx else settings.ground_friction
            self.vx = approach(self.vx, desired_vx, acceleration * dt)
            self.vy = 0  # The floor's support cancels gravity at rest.
        else:
            self.vx *= exp(-settings.air_drag * dt)
            self.vy += settings.gravity * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        if right == left:
            self.x, self.vx = float(left), 0
        elif self.x < left or self.x > right:
            self.x = min(max(self.x, left), right)
            self.vx = -self.vx * settings.wall_restitution
            contact.wall_hits += 1
        if self.y < top:
            self.y = float(top)
            if self.vy < 0:
                self.vy = -self.vy * settings.wall_restitution
        if self.y >= floor:
            self.y = float(floor)
            rebound = self.vy * settings.restitution
            if not self.grounded and rebound >= settings.minimum_bounce_speed and floor > top:
                self.vy = -rebound
                contact.impacts += 1
                self.grounded = False
            else:
                if not was_grounded:
                    contact.landed = True
                self.vy = 0
                self.grounded = True
        return contact
