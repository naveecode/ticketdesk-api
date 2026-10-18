import django_filters

from tickets.models import Ticket


class TicketFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(choices=Ticket.Status.choices)
    priority = django_filters.ChoiceFilter(choices=Ticket.Priority.choices)
    category = django_filters.ChoiceFilter(choices=Ticket.Category.choices)
    tags = django_filters.CharFilter(field_name="tags__name", lookup_expr="iexact")
    assignee = django_filters.NumberFilter(field_name="assignee_id")
    requester = django_filters.NumberFilter(field_name="requester_id")

    class Meta:
        model = Ticket
        fields = ["status", "priority", "category", "tags", "assignee", "requester"]
