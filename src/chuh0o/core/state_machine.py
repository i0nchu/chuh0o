"""Small state-pattern FSM: nodes own lifecycle and event handling."""

from collections.abc import Mapping
from typing import Protocol, TypeVar

Context = TypeVar("Context", contravariant=True)
Event = TypeVar("Event", contravariant=True)


class StateNode(Protocol[Context, Event]):
    def enter(self, context: Context) -> None: ...

    def exit(self, context: Context) -> None: ...

    def update(self, context: Context, dt: float) -> None: ...

    def handle(self, context: Context, event: Event) -> None: ...


class StateMachine[Key, Context, Event]:
    def __init__(
        self, context: Context, states: Mapping[Key, StateNode[Context, Event]], initial: Key
    ):
        self.context = context
        self.states = dict(states)
        self.current = initial
        self.states[initial].enter(context)

    @property
    def node(self) -> StateNode[Context, Event]:
        return self.states[self.current]

    def transition(self, target: Key) -> None:
        next_node = self.states[target]
        self.node.exit(self.context)
        self.current = target
        next_node.enter(self.context)

    def dispatch(self, event: Event) -> None:
        self.node.handle(self.context, event)

    def update(self, dt: float) -> None:
        self.node.update(self.context, max(0.0, dt))
