import random

import pytest

from chuh0o.core.behavior import Behavior, Event, State
from chuh0o.core.state_machine import StateMachine


def test_node_lifecycle_events_and_invalid_transition_are_ordered():
    calls = []

    class Node:
        def __init__(self, name):
            self.name = name

        def enter(self, ctx):
            ctx.append((self.name, "enter"))

        def exit(self, ctx):
            ctx.append((self.name, "exit"))

        def handle(self, ctx, event):
            ctx.append((self.name, event))

        def update(self, ctx, dt):
            ctx.append((self.name, dt))

    machine = StateMachine(calls, {"a": Node("a"), "b": Node("b")}, "a")
    machine.dispatch("clicked")
    machine.update(0.1)
    machine.transition("b")
    assert calls == [("a", "enter"), ("a", "clicked"), ("a", 0.1), ("a", "exit"), ("b", "enter")]
    with pytest.raises(KeyError):
        machine.transition("missing")
    assert machine.current == "b" and calls[-1] == ("b", "enter")


def test_airborne_state_waits_for_physics_when_sleep_is_requested():
    pet = Behavior(random.Random(1))
    pet.begin_drag()
    pet.end_drag()
    pet.set_sleep_requested(True)
    pet.update(100)
    pet.click()
    assert pet.state == State.FALL and pet.desired_velocity(45) == 0
    pet.dispatch(Event.LANDED)
    assert pet.state == State.LAND
    pet.update(0.31)
    assert pet.state == State.SLEEP
    pet.update(1000)
    assert pet.state == State.SLEEP
    pet.set_sleep_requested(False)
    assert pet.state == State.WAVE


def test_grabbing_interrupts_a_fall_and_repeated_airborne_event_does_not_restart_it():
    pet = Behavior()
    pet.dispatch(Event.AIRBORNE)
    assert pet.state == State.FALL
    pet.remaining = 123
    pet.dispatch(Event.AIRBORNE)
    assert pet.remaining == 123
    pet.begin_drag()
    assert pet.state == State.DRAG
    pet.dispatch(Event.AIRBORNE)
    pet.dispatch(Event.LANDED)
    assert pet.state == State.DRAG
    assert Behavior().states[State.IDLE] is not pet.states[State.IDLE]


def test_walk_and_three_hops_share_duration_and_count_one_activity():
    pet = Behavior(jump_durations={"jump_left": 1.03, "jump_right": 1.03})
    pet.enter(State.WALK)
    assert pet.remaining == pytest.approx(3.09)
    pet.update(3.08)
    assert pet.state == State.WALK and pet.movements == 0
    pet.update(0.01)
    assert pet.state == State.IDLE and pet.movements == 1
    pet.enter(State.JUMP)
    for remaining in (2.06, 1.03):
        pet.dispatch(Event.ANIMATION_FINISHED)
        assert pet.state == State.JUMP and pet.remaining == pytest.approx(remaining)
        assert pet.movements == 1
    pet.dispatch(Event.ANIMATION_FINISHED)
    assert pet.state == State.IDLE and pet.movements == pet.moves_since_rest == 2


@pytest.mark.parametrize("interruption,target", [("click", State.WAVE), ("sleep", State.SLEEP)])
def test_continuous_jumps_finish_current_hop_before_responding(interruption, target):
    pet = Behavior()
    pet.enter(State.JUMP)
    pet.dispatch(Event.ANIMATION_FINISHED)
    if interruption == "click":
        pet.click()
    else:
        pet.set_sleep_requested(True)
    assert pet.state == State.JUMP
    pet.dispatch(Event.ANIMATION_FINISHED)
    assert pet.state == target and pet.movements == 1


def test_continuous_jumps_recheck_direction_and_stop_when_no_hop_fits():
    pet = Behavior()
    pet.direction = 1
    pet.enter(State.JUMP)
    pet.jump_directions = (-1,)
    pet.dispatch(Event.ANIMATION_FINISHED)
    assert pet.state == State.JUMP and pet.direction == -1
    pet.jump_directions = ()
    pet.dispatch(Event.ANIMATION_FINISHED)
    assert pet.state == State.IDLE and pet.movements == 1


def test_grabbing_cancels_remaining_hops_immediately():
    pet = Behavior()
    pet.enter(State.JUMP)
    pet.dispatch(Event.ANIMATION_FINISHED)
    pet.begin_drag()
    pet.dispatch(Event.ANIMATION_FINISHED)
    assert pet.state == State.DRAG and pet.movements == 0
