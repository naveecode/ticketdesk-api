from django.conf import settings
from django.db import models


class Tag(models.Model):
    name = models.SlugField(max_length=50, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Ticket(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In progress"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    class Category(models.TextChoices):
        GENERAL = "general", "General"
        BILLING = "billing", "Billing"
        TECHNICAL = "technical", "Technical"
        ACCOUNT = "account", "Account"
        ACCESS = "access", "Access"

    class TriageStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"

    class TriageSource(models.TextChoices):
        LLM = "llm", "LLM"
        FALLBACK = "fallback", "Fallback"

    title = models.CharField(max_length=200, help_text="Short summary of the issue.")
    description = models.TextField(help_text="What happened and what you already tried.")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )
    priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )
    category = models.CharField(
        max_length=20,
        choices=Category.choices,
        default=Category.GENERAL,
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="tickets",
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="assigned_tickets",
        null=True,
        blank=True,
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="tickets")
    triage_status = models.CharField(
        max_length=20,
        choices=TriageStatus.choices,
        default=TriageStatus.PENDING,
    )
    triage_source = models.CharField(max_length=20, choices=TriageSource.choices, blank=True)
    suggested_reply = models.TextField(blank=True)
    triage_model = models.CharField(max_length=100, blank=True)
    triage_latency_ms = models.PositiveIntegerField(null=True, blank=True)
    triage_error = models.TextField(blank=True)
    triaged_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["requester", "status"]),
        ]

    def __str__(self) -> str:
        return f"#{self.pk} {self.title}"


class Comment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="comments",
    )
    body = models.TextField()
    is_internal = models.BooleanField(
        default=False,
        help_text="Internal notes are visible to agents and admins only.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"Comment {self.pk} on ticket {self.ticket_id}"
