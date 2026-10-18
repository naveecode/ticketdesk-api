"""Celery wrapper around triage.

Retries use exponential backoff (1s, 2s, 4s) and then the keyword fallback,
so a missing or broken model endpoint still leaves a completed triage row.
"""

import logging
import time
from collections.abc import Callable

from django.utils import timezone

from celery import shared_task
from tickets.models import Ticket
from tickets.triage import TriagePermanentError, TriageTransientError, classify, fallback_classify

logger = logging.getLogger(__name__)

_UPDATE_FIELDS = [
    "category",
    "priority",
    "suggested_reply",
    "triage_status",
    "triage_source",
    "triage_model",
    "triage_latency_ms",
    "triage_error",
    "triaged_at",
    "updated_at",
]


def run_triage(ticket_id: int, *, force_fallback: bool = False, error: str = "") -> None:
    try:
        ticket = Ticket.objects.get(pk=ticket_id)
    except Ticket.DoesNotExist:
        logger.warning("triage skipped; ticket %s does not exist", ticket_id)
        return
    if ticket.triage_status == Ticket.TriageStatus.COMPLETED and not force_fallback:
        return

    started = time.perf_counter()
    failure = error
    try:
        if force_fallback:
            result = fallback_classify(ticket.title, ticket.description)
        else:
            result = classify(ticket.title, ticket.description)
    except TriagePermanentError as exc:
        result = fallback_classify(ticket.title, ticket.description)
        failure = str(exc)
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    ticket.category = result.category
    ticket.priority = result.priority
    ticket.suggested_reply = result.suggested_reply
    ticket.triage_status = Ticket.TriageStatus.COMPLETED
    ticket.triage_source = result.source
    ticket.triage_model = result.model
    ticket.triage_latency_ms = elapsed_ms
    ticket.triage_error = failure[:500]
    ticket.triaged_at = timezone.now()
    ticket.save(update_fields=_UPDATE_FIELDS)
    logger.info(
        "triaged ticket %s via %s in %sms",
        ticket_id,
        result.source,
        elapsed_ms,
    )


def handle_triage(
    ticket_id: int,
    *,
    retries: int,
    max_retries: int,
    retry_fn: Callable[[Exception, int], None],
) -> str:
    try:
        run_triage(ticket_id)
    except TriageTransientError as exc:
        if retries >= max_retries:
            run_triage(ticket_id, force_fallback=True, error=str(exc))
            return "fallback"
        retry_fn(exc, 2**retries)
        return "retry"
    return "ok"


@shared_task(bind=True, max_retries=3, name="tickets.triage_ticket")
def triage_ticket(self, ticket_id: int) -> str:
    def retry_fn(exc: Exception, countdown: int) -> None:
        raise self.retry(exc=exc, countdown=countdown)

    return handle_triage(
        ticket_id,
        retries=self.request.retries,
        max_retries=self.max_retries,
        retry_fn=retry_fn,
    )
