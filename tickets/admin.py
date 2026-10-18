from django.contrib import admin

from tickets.models import Comment, Tag, Ticket


class CommentInline(admin.TabularInline):
    model = Comment
    extra = 0
    raw_id_fields = ("author",)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "status",
        "priority",
        "category",
        "requester",
        "assignee",
        "triage_status",
        "created_at",
    )
    list_filter = ("status", "priority", "category", "triage_status", "triage_source")
    search_fields = ("title", "description", "requester__username", "assignee__username")
    autocomplete_fields = ("requester", "assignee")
    filter_horizontal = ("tags",)
    readonly_fields = (
        "triage_status",
        "triage_source",
        "triage_model",
        "triage_latency_ms",
        "triage_error",
        "triaged_at",
        "suggested_reply",
        "created_at",
        "updated_at",
    )
    inlines = [CommentInline]
