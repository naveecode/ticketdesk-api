from datetime import timedelta

import pytest
from django.utils import timezone

from tickets.models import Tag, Ticket

pytestmark = pytest.mark.django_db


def test_filter_search_and_ordering(agent_client, customer, agent, make_ticket):
    billing = Tag.objects.create(name="billing")
    older = make_ticket(
        customer,
        title="Invoice charged twice",
        description="Please look at the invoice.",
        status=Ticket.Status.OPEN,
        priority=Ticket.Priority.HIGH,
        category=Ticket.Category.BILLING,
        assignee=agent,
    )
    older.tags.add(billing)
    newer = make_ticket(
        customer,
        title="Export question",
        description="Where is the download button?",
        status=Ticket.Status.CLOSED,
        priority=Ticket.Priority.LOW,
        category=Ticket.Category.GENERAL,
    )
    now = timezone.now()
    Ticket.objects.filter(pk=older.pk).update(created_at=now - timedelta(days=2))
    Ticket.objects.filter(pk=newer.pk).update(created_at=now - timedelta(hours=1))

    by_status = agent_client.get("/api/tickets/?status=open")
    assert [row["id"] for row in by_status.data["results"]] == [older.id]

    by_priority = agent_client.get("/api/tickets/?priority=low")
    assert [row["id"] for row in by_priority.data["results"]] == [newer.id]

    by_tag = agent_client.get("/api/tickets/?tags=BILLING")
    assert [row["id"] for row in by_tag.data["results"]] == [older.id]

    by_assignee = agent_client.get(f"/api/tickets/?assignee={agent.id}")
    assert [row["id"] for row in by_assignee.data["results"]] == [older.id]

    found = agent_client.get("/api/tickets/?search=invoice")
    assert [row["id"] for row in found.data["results"]] == [older.id]

    ordered = agent_client.get("/api/tickets/?ordering=created_at")
    assert [row["id"] for row in ordered.data["results"]] == [older.id, newer.id]

    combined = agent_client.get("/api/tickets/?status=open&search=invoice&ordering=-created_at")
    assert [row["id"] for row in combined.data["results"]] == [older.id]


def test_pagination(agent_client, customer, make_ticket):
    for index in range(11):
        make_ticket(customer, title=f"Ticket number {index:02d}")

    first = agent_client.get("/api/tickets/?page_size=10")
    assert first.status_code == 200
    assert first.data["count"] == 11
    assert len(first.data["results"]) == 10
    assert first.data["next"] is not None

    second = agent_client.get("/api/tickets/?page_size=10&page=2")
    assert len(second.data["results"]) == 1
    assert second.data["previous"] is not None
