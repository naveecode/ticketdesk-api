import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from tickets.models import Ticket
from tickets.tasks import triage_ticket

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Ticket)
def enqueue_triage(sender, instance: Ticket, created: bool, **kwargs) -> None:
    if not created:
        return
    try:
        triage_ticket.delay(instance.pk)
    except Exception:
        logger.exception("Failed to enqueue triage for ticket %s", instance.pk)
