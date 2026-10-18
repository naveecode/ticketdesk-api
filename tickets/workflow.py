"""Allowed ticket status transitions.

Customers do not move tickets through this workflow. Agents and admins may
follow the edges below. Repeating the current status is a no-op.
"""

from tickets.models import Ticket

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    Ticket.Status.OPEN: {Ticket.Status.IN_PROGRESS},
    Ticket.Status.IN_PROGRESS: {Ticket.Status.RESOLVED},
    Ticket.Status.RESOLVED: {Ticket.Status.CLOSED, Ticket.Status.IN_PROGRESS},
    Ticket.Status.CLOSED: {Ticket.Status.OPEN},
}


class TransitionError(Exception):
    def __init__(self, current: str, new: str) -> None:
        self.current = current
        self.new = new
        super().__init__(f"Cannot transition from {current} to {new}.")


def ensure_transition(current: str, new: str) -> None:
    if current == new:
        return
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if new not in allowed:
        raise TransitionError(current, new)
