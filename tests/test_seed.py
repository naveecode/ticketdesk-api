from io import StringIO

import pytest
from django.core.management import call_command

from accounts.models import User
from tickets.models import Ticket

pytestmark = pytest.mark.django_db


def test_seed_demo_is_idempotent_and_uses_the_fallback():
    first = StringIO()
    call_command("seed_demo", stdout=first)
    assert "Ticketdesk-demo-1" in first.getvalue()
    assert User.objects.get(username="alice").role == User.Role.CUSTOMER
    assert User.objects.get(username="sam").role == User.Role.AGENT
    assert User.objects.get(username="admin").is_superuser is True
    assert Ticket.objects.count() == 8

    invoice = Ticket.objects.get(title="Invoice charged twice this month")
    assert invoice.category == Ticket.Category.BILLING
    assert invoice.priority == Ticket.Priority.HIGH
    assert invoice.triage_source == Ticket.TriageSource.FALLBACK
    assert invoice.triage_status == Ticket.TriageStatus.COMPLETED
    assert invoice.suggested_reply

    outage = Ticket.objects.get(title="Production API outage since 09:10")
    assert outage.priority == Ticket.Priority.URGENT
    assert outage.category == Ticket.Category.TECHNICAL
    assert outage.comments.filter(is_internal=True).exists()

    second = StringIO()
    call_command("seed_demo", stdout=second)
    assert Ticket.objects.count() == 8
    assert "Tickets created this run: 0" in second.getvalue()
