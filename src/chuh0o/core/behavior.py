"""Behavior states produce movement intent; physics owns actual motion."""

from __future__ import annotations

import random
from collections.abc import Mapping
from enum import StrEnum

from chuh0o.core.state_machine import StateMachine


class State(StrEnum):
    IDLE = "idle"
    WALK = "walk"
    SLEEP = "sleep"
    DRAG = "drag"
    WAVE = "wave"
    JUMP = "jump"
    LIE_DOWN = "lie_down"
    LIE = "lie"
    GET_UP = "get_up"
    FALL = "fall"
    LAND = "land"


class Event(StrEnum):
    CLICK = "click"
    GRAB = "grab"
    RELEASE = "release"
    AIRBORNE = "airborne"
    LANDED = "landed"
    SLEEP_REQUESTED = "sleep_requested"
    WAKE = "wake"
    ANIMATION_FINISHED = "animation_finished"
    WAVE_REQUESTED = "wave_requested"
    JUMP_REQUESTED = "jump_requested"
    LIE_REQUESTED = "lie_requested"
    STAND_REQUESTED = "stand_requested"


class BehaviorState:
    animation = "idle"

    def enter(self, pet: Behavior) -> None:
        pet.remaining = 0

    def exit(self, pet: Behavior) -> None:
        pass

    def update(self, pet: Behavior, dt: float) -> None:
        pass

    def handle(self, pet: Behavior, event: Event) -> None:
        if event == Event.GRAB:
            pet.enter(State.DRAG)

    def velocity(self, pet: Behavior, speed: float) -> float:
        return 0

    def clip(self, pet: Behavior) -> str:
        return self.animation


class GroundState(BehaviorState):
    def handle(self, pet: Behavior, event: Event) -> None:
        if event == Event.AIRBORNE:
            pet.enter(State.FALL)
        elif event == Event.SLEEP_REQUESTED:
            pet.enter(State.SLEEP)
        elif event == Event.CLICK and not pet.sleep_requested:
            pet.enter(State.WAVE)
        elif not pet.sleep_requested and event == Event.WAVE_REQUESTED:
            pet.enter(State.WAVE)
        elif not pet.sleep_requested and event == Event.LIE_REQUESTED:
            pet.enter(State.LIE_DOWN)
        elif not pet.sleep_requested and event == Event.JUMP_REQUESTED and pet.jump_directions:
            pet.choose_jump_direction()
            pet.enter(State.JUMP)
        else:
            super().handle(pet, event)


class TimedGroundState(GroundState):
    def update(self, pet: Behavior, dt: float) -> None:
        pet.remaining -= dt
        if pet.remaining <= 0:
            self.finished(pet)

    def finished(self, pet: Behavior) -> None:
        if pet.sleep_requested:
            pet.enter(State.SLEEP)
        else:
            pet.enter(State.IDLE, pet.rng.uniform(2, 7))


class IdleState(TimedGroundState):
    def enter(self, pet: Behavior) -> None:
        pet.remaining = pet.rng.uniform(3, 10)

    def finished(self, pet: Behavior) -> None:
        if pet.sleep_requested:
            pet.enter(State.SLEEP)
            return
        if pet.moves_since_rest >= 4:
            pet.enter(State.LIE_DOWN)
            return
        if (pet.movements + 1) % 3 == 0 and pet.jump_directions:
            pet.choose_jump_direction()
            pet.enter(State.JUMP)
            return
        pet.direction = pet.rng.choice((-1, 1))
        pet.enter(State.WALK)


class MovementState(GroundState):
    """Share one activity budget; jumps spend it at complete landing boundaries."""

    def enter(self, pet: Behavior) -> None:
        pet.remaining = pet.movement_duration

    def spend_time(self, pet: Behavior, seconds: float) -> bool:
        pet.remaining = max(0.0, pet.remaining - seconds)
        return pet.remaining <= 1e-9


class WalkState(MovementState):
    def update(self, pet: Behavior, dt: float) -> None:
        if self.spend_time(pet, dt):
            pet.complete_movement()

    def clip(self, pet: Behavior) -> str:
        return "walk_right" if pet.direction > 0 else "walk_left"

    def velocity(self, pet: Behavior, speed: float) -> float:
        return pet.direction * speed


class SleepState(GroundState):
    animation = "sleep"

    def handle(self, pet: Behavior, event: Event) -> None:
        if event == Event.WAKE:
            pet.enter(State.WAVE)
        elif event != Event.SLEEP_REQUESTED:
            super().handle(pet, event)


class WaveState(GroundState):
    animation = "wave"

    def handle(self, pet: Behavior, event: Event) -> None:
        if event == Event.ANIMATION_FINISHED:
            pet.rest()
        elif event not in (Event.CLICK, Event.WAVE_REQUESTED):
            super().handle(pet, event)


class JumpState(MovementState):
    def enter(self, pet: Behavior) -> None:
        super().enter(pet)
        pet.after_jump = State.IDLE

    def clip(self, pet: Behavior) -> str:
        return "jump_right" if pet.direction > 0 else "jump_left"

    def handle(self, pet: Behavior, event: Event) -> None:
        if event == Event.ANIMATION_FINISHED:
            expired = self.spend_time(pet, pet.jump_durations[self.clip(pet)])
            if (
                expired
                or pet.sleep_requested
                or pet.after_jump != State.IDLE
                or not pet.jump_directions
            ):
                pet.complete_movement(pet.after_jump)
            else:
                pet.choose_jump_direction()
        elif event in (Event.CLICK, Event.WAVE_REQUESTED) and not pet.sleep_requested:
            pet.after_jump = State.WAVE
        elif event == Event.LIE_REQUESTED and not pet.sleep_requested:
            pet.after_jump = State.LIE_DOWN
        elif event not in (Event.SLEEP_REQUESTED, Event.JUMP_REQUESTED):
            super().handle(pet, event)


def requested_pose(event: Event, pet: Behavior) -> State | None:
    if event in (Event.CLICK, Event.WAVE_REQUESTED):
        return State.WAVE
    if event == Event.JUMP_REQUESTED and pet.jump_directions:
        return State.JUMP
    if event == Event.STAND_REQUESTED:
        return State.IDLE
    return None


class LieDownState(GroundState):
    def enter(self, pet: Behavior) -> None:
        super().enter(pet)
        pet.pending_stand = None
        pet.moves_since_rest = 0

    def clip(self, pet: Behavior) -> str:
        return "liedown_right" if pet.direction > 0 else "liedown_left"

    def handle(self, pet: Behavior, event: Event) -> None:
        if event == Event.ANIMATION_FINISHED:
            if pet.sleep_requested:
                pet.begin_getup(State.SLEEP)
            elif pet.pending_stand is not None:
                pet.begin_getup(pet.pending_stand)
            else:
                pet.enter(State.LIE)
        elif (target := requested_pose(event, pet)) is not None:
            pet.pending_stand = target
        elif event not in (Event.SLEEP_REQUESTED, Event.LIE_REQUESTED):
            super().handle(pet, event)


class LieState(TimedGroundState):
    def enter(self, pet: Behavior) -> None:
        pet.remaining = 6

    def clip(self, pet: Behavior) -> str:
        return "lie_right" if pet.direction > 0 else "lie_left"

    def finished(self, pet: Behavior) -> None:
        pet.begin_getup(State.SLEEP if pet.sleep_requested else State.IDLE)

    def handle(self, pet: Behavior, event: Event) -> None:
        if event == Event.SLEEP_REQUESTED:
            pet.begin_getup(State.SLEEP)
        elif (target := requested_pose(event, pet)) is not None:
            pet.begin_getup(target)
        else:
            super().handle(pet, event)


class GetUpState(GroundState):
    def clip(self, pet: Behavior) -> str:
        return "getup_right" if pet.direction > 0 else "getup_left"

    def handle(self, pet: Behavior, event: Event) -> None:
        if event == Event.ANIMATION_FINISHED:
            if pet.sleep_requested:
                pet.enter(State.SLEEP)
            elif pet.after_getup == State.SLEEP:
                pet.enter(State.WAVE)
            elif pet.after_getup == State.JUMP:
                if pet.jump_directions:
                    pet.choose_jump_direction()
                    pet.enter(State.JUMP)
                else:
                    pet.rest()
            else:
                pet.enter(pet.after_getup, 2 if pet.after_getup == State.IDLE else None)
        elif (target := requested_pose(event, pet)) is not None:
            pet.after_getup = target
        elif event == Event.WAKE and pet.after_getup == State.SLEEP:
            pet.after_getup = State.WAVE
        elif event not in (Event.SLEEP_REQUESTED, Event.LIE_REQUESTED):
            super().handle(pet, event)


class DragState(BehaviorState):
    animation = "drag"

    def handle(self, pet: Behavior, event: Event) -> None:
        if event == Event.RELEASE:
            pet.enter(State.FALL)


class FallState(BehaviorState):
    animation = "drag"

    def handle(self, pet: Behavior, event: Event) -> None:
        if event == Event.LANDED:
            pet.enter(State.LAND)
        else:
            super().handle(pet, event)


class LandState(TimedGroundState):
    def enter(self, pet: Behavior) -> None:
        pet.remaining = 0.3

    def finished(self, pet: Behavior) -> None:
        if pet.sleep_requested:
            pet.enter(State.SLEEP)
        else:
            pet.enter(State.IDLE, 2)


# Add a new node here; lifecycle and event rules stay with the corresponding class.
STATE_TYPES = {
    State.IDLE: IdleState,
    State.WALK: WalkState,
    State.SLEEP: SleepState,
    State.DRAG: DragState,
    State.WAVE: WaveState,
    State.JUMP: JumpState,
    State.LIE_DOWN: LieDownState,
    State.LIE: LieState,
    State.GET_UP: GetUpState,
    State.FALL: FallState,
    State.LAND: LandState,
}


class Behavior:
    def __init__(
        self,
        rng: random.Random | None = None,
        *,
        jump_durations: Mapping[str, float] | None = None,
    ):
        self.rng = rng or random.Random()
        self.jump_durations = dict(jump_durations or {"jump_left": 1.0, "jump_right": 1.0})
        self.movement_duration = 3 * max(self.jump_durations.values())
        self.direction = self.rng.choice((-1, 1))
        self.remaining = 0.0
        self.sleep_requested = False
        self.movements = self.moves_since_rest = 0
        self.jump_directions: tuple[int, ...] = (-1, 1)
        self.after_getup = self.after_jump = State.IDLE
        self.pending_stand: State | None = None
        self.states = {key: node() for key, node in STATE_TYPES.items()}
        self.machine = StateMachine(self, self.states, State.IDLE)
        self.remaining = 3.0

    @property
    def state(self) -> State:
        return self.machine.current

    @property
    def animation(self) -> str:
        return self.states[self.state].clip(self)

    def enter(self, state: State, seconds: float | None = None) -> None:
        self.machine.transition(state)
        if seconds is not None:
            self.remaining = seconds

    def dispatch(self, event: Event) -> None:
        self.machine.dispatch(event)

    def set_sleep_requested(self, requested: bool) -> None:
        if requested != self.sleep_requested:
            self.sleep_requested = requested
            self.dispatch(Event.SLEEP_REQUESTED if requested else Event.WAKE)

    def update(self, dt: float) -> None:
        self.machine.update(dt)

    def desired_velocity(self, speed: float) -> float:
        return self.states[self.state].velocity(self, speed)

    def click(self) -> None:
        self.dispatch(Event.CLICK)

    def begin_drag(self) -> None:
        self.dispatch(Event.GRAB)

    def end_drag(self) -> None:
        self.dispatch(Event.RELEASE)

    def bounce(self) -> None:
        self.direction *= -1

    def rest(self) -> None:
        if self.sleep_requested:
            self.enter(State.SLEEP)
        else:
            self.enter(State.IDLE, 2)

    def complete_movement(self, following: State = State.IDLE) -> None:
        self.movements += 1
        self.moves_since_rest += 1
        if self.sleep_requested:
            self.enter(State.SLEEP)
        elif following != State.IDLE:
            self.enter(following)
        else:
            self.enter(State.IDLE, self.rng.uniform(2, 7))

    def choose_jump_direction(self) -> None:
        if self.direction not in self.jump_directions:
            self.direction = self.jump_directions[0]

    def begin_getup(self, following: State) -> None:
        self.after_getup = following
        self.enter(State.GET_UP)

    def request_action(self, action: str) -> None:
        event = {
            "wave": Event.WAVE_REQUESTED,
            "jump": Event.JUMP_REQUESTED,
            "lie": Event.STAND_REQUESTED
            if self.state in (State.LIE, State.LIE_DOWN)
            else Event.LIE_REQUESTED,
        }[action]
        self.dispatch(event)
