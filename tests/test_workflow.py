import pytest

from tickets.models import Ticket

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("current", "new", "allowed"),
    [
        (Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS, True),
        (Ticket.Status.OPEN, Ticket.Status.RESOLVED, False),
        (Ticket.Status.OPEN, Ticket.Status.CLOSED, False),
        (Ticket.Status.IN_PROGRESS, Ticket.Status.RESOLVED, True),
        (Ticket.Status.IN_PROGRESS, Ticket.Status.OPEN, False),
        (Ticket.Status.RESOLVED, Ticket.Status.CLOSED, True),
        (Ticket.Status.RESOLVED, Ticket.Status.IN_PROGRESS, True),
        (Ticket.Status.RESOLVED, Ticket.Status.OPEN, False),
        (Ticket.Status.CLOSED, Ticket.Status.OPEN, True),
        (Ticket.Status.CLOSED, Ticket.Status.IN_PROGRESS, False),
    ],
)
def test_agent_status_transitions(agent_client, customer, make_ticket, current, new, allowed):
    ticket = make_ticket(customer, status=current)
    response = agent_client.patch(
        f"/api/tickets/{ticket.id}/",
        {"status": new},
        format="json",
    )
    ticket.refresh_from_db()
    if allowed:
        assert response.status_code == 200
        assert response.data["status"] == new
        assert ticket.status == new
    else:
        assert response.status_code == 400
        assert "status" in response.data
        assert ticket.status == current


def test_repeating_the_current_status_is_allowed(agent_client, customer, make_ticket):
    ticket = make_ticket(customer, status=Ticket.Status.OPEN)
    response = agent_client.patch(
        f"/api/tickets/{ticket.id}/",
        {"status": Ticket.Status.OPEN},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["status"] == Ticket.Status.OPEN


def test_title_must_be_at_least_three_characters(customer_client):
    response = customer_client.post(
        "/api/tickets/",
        {"title": "no", "description": "This description is long enough."},
        format="json",
    )
    assert response.status_code == 400
