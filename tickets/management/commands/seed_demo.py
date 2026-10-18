"""Load a small, repeatable helpdesk dataset for local demos."""

import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models.signals import post_save
from django.utils import timezone

from accounts.models import User
from tickets.models import Comment, Tag, Ticket
from tickets.signals import enqueue_triage
from tickets.triage import fallback_classify

DEMO_PASSWORD = "Ticketdesk-demo-1"

_USERS = (
    ("admin", User.Role.ADMIN, "admin@example.com", True, True),
    ("sam", User.Role.AGENT, "sam@example.com", True, False),
    ("riley", User.Role.AGENT, "riley@example.com", True, False),
    ("alice", User.Role.CUSTOMER, "alice@example.com", False, False),
    ("bob", User.Role.CUSTOMER, "bob@example.com", False, False),
    ("carol", User.Role.CUSTOMER, "carol@example.com", False, False),
)

_TAGS = ("billing", "login", "outage", "mobile", "api", "account")

# Text is written so the keyword fallback lands on the category used in the story.
_TICKETS = (
    {
        "title": "Invoice charged twice this month",
        "description": "The latest invoice includes a duplicate charge for the same seats.",
        "requester": "alice",
        "assignee": "sam",
        "status": Ticket.Status.RESOLVED,
        "tags": ["billing"],
        "days_ago": 6,
        "comments": [
            ("alice", "The second line item matches the first one exactly.", False),
            ("sam", "I see the duplicate. Finance will issue a credit on the next invoice.", False),
        ],
    },
    {
        "title": "Cannot reset my password",
        "description": "The reset email never arrives and login stays locked.",
        "requester": "alice",
        "assignee": "riley",
        "status": Ticket.Status.IN_PROGRESS,
        "tags": ["login"],
        "days_ago": 2,
        "comments": [
            ("riley", "I re-sent the reset link and confirmed the mailbox is not bouncing.", False),
        ],
    },
    {
        "title": "Checkout API returning 500",
        "description": "Customers see an error when the checkout API times out.",
        "requester": "bob",
        "assignee": "sam",
        "status": Ticket.Status.OPEN,
        "tags": ["api"],
        "days_ago": 1,
        "comments": [],
    },
    {
        "title": "Update the company name on my profile",
        "description": "Please change the company name on our account profile to Northwind Labs.",
        "requester": "bob",
        "assignee": None,
        "status": Ticket.Status.OPEN,
        "tags": ["account"],
        "days_ago": 1,
        "comments": [],
    },
    {
        "title": "How do I export a monthly report?",
        "description": "Looking for the steps to download last month's usage report.",
        "requester": "carol",
        "assignee": "riley",
        "status": Ticket.Status.CLOSED,
        "tags": [],
        "days_ago": 12,
        "comments": [
            ("riley", "Open Billing, then Usage, then Download CSV for the month you need.", False),
            ("carol", "That worked. Thanks.", False),
        ],
    },
    {
        "title": "Mobile app crashes on launch",
        "description": (
            "The iOS app hits a crash immediately after opening. "
            "It started after yesterday's release."
        ),
        "requester": "carol",
        "assignee": "sam",
        "status": Ticket.Status.IN_PROGRESS,
        "tags": ["mobile"],
        "days_ago": 3,
        "comments": [
            ("sam", "We can reproduce this on iOS 18. Collecting the crash log now.", False),
        ],
    },
    {
        "title": "Refund for unused seats",
        "description": "We need a refund for seats we did not use after the renewal invoice.",
        "requester": "alice",
        "assignee": None,
        "status": Ticket.Status.OPEN,
        "tags": ["billing"],
        "days_ago": 0,
        "comments": [],
    },
    {
        "title": "Production API outage since 09:10",
        "description": "The public API has been down and customers cannot complete checkout.",
        "requester": "bob",
        "assignee": "sam",
        "status": Ticket.Status.RESOLVED,
        "tags": ["outage", "api"],
        "days_ago": 4,
        "comments": [
            (
                "sam",
                "The bad deploy was rolled back at 09:24. Error rate is back to baseline.",
                False,
            ),
            (
                "sam",
                "Postmortem draft is in the incident channel. Do not paste it to the customer.",
                True,
            ),
        ],
    },
)


def _upsert_user(username, role, email, staff, superuser) -> User:
    user, _created = User.objects.get_or_create(
        username=username,
        defaults={"email": email, "role": role},
    )
    user.email = email
    user.role = role
    user.is_staff = staff
    user.is_superuser = superuser
    user.set_password(DEMO_PASSWORD)
    user.save()
    return user


class Command(BaseCommand):
    help = "Create demo users, tags, and tickets. Safe to run more than once."

    def handle(self, *args, **options):
        was_connected = post_save.disconnect(enqueue_triage, sender=Ticket)
        try:
            self._seed()
        finally:
            if was_connected:
                post_save.connect(enqueue_triage, sender=Ticket)

    def _seed(self) -> None:
        users = {
            username: _upsert_user(username, role, email, staff, superuser)
            for username, role, email, staff, superuser in _USERS
        }
        tags = {name: Tag.objects.get_or_create(name=name)[0] for name in _TAGS}
        created_tickets = 0
        now = timezone.now()

        for spec in _TICKETS:
            if Ticket.objects.filter(title=spec["title"]).exists():
                continue
            started = time.perf_counter()
            result = fallback_classify(spec["title"], spec["description"])
            latency_ms = int((time.perf_counter() - started) * 1000)
            ticket = Ticket.objects.create(
                title=spec["title"],
                description=spec["description"],
                requester=users[spec["requester"]],
                assignee=users[spec["assignee"]] if spec["assignee"] else None,
                status=spec["status"],
                priority=result.priority,
                category=result.category,
                triage_status=Ticket.TriageStatus.COMPLETED,
                triage_source=result.source,
                suggested_reply=result.suggested_reply,
                triage_model=result.model,
                triage_latency_ms=latency_ms,
                triaged_at=now - timedelta(days=spec["days_ago"]),
            )
            ticket.tags.set([tags[name] for name in spec["tags"]])
            created_at = now - timedelta(days=spec["days_ago"], hours=4)
            Ticket.objects.filter(pk=ticket.pk).update(
                created_at=created_at,
                updated_at=created_at + timedelta(hours=1),
            )
            Comment.objects.bulk_create(
                [
                    Comment(
                        ticket=ticket,
                        author=users[author],
                        body=body,
                        is_internal=internal,
                    )
                    for author, body, internal in spec["comments"]
                ]
            )
            created_tickets += 1

        self.stdout.write(self.style.SUCCESS("Seeded ticketdesk demo data."))
        self.stdout.write(f"Login password for every account: {DEMO_PASSWORD}")
        self.stdout.write("")
        for username, role, *_rest in _USERS:
            self.stdout.write(f"  {username:<8} {role}")
        self.stdout.write("")
        self.stdout.write(
            f"Tickets created this run: {created_tickets}. Total tickets: {Ticket.objects.count()}."
        )
        self.stdout.write("Swagger UI: /api/docs/    ReDoc: /api/redoc/    Health: /api/health/")
