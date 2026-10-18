from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from accounts.models import User
from accounts.serializers import UserMiniSerializer
from tickets.models import Comment, Tag, Ticket
from tickets.workflow import TransitionError, ensure_transition

_STAFF_ONLY_FIELDS = (
    "suggested_reply",
    "triage_source",
    "triage_latency_ms",
    "triage_model",
    "triaged_at",
    "triage_error",
)


def _is_staff(user) -> bool:
    return user.role in (User.Role.AGENT, User.Role.ADMIN)


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ["id", "name", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_name(self, value: str) -> str:
        return value.lower()


class CommentSerializer(serializers.ModelSerializer):
    author = UserMiniSerializer(read_only=True)
    body = serializers.CharField(min_length=1, max_length=5000)

    class Meta:
        model = Comment
        fields = ["id", "author", "body", "is_internal", "created_at"]
        read_only_fields = ["id", "author", "created_at"]

    def validate_is_internal(self, value: bool) -> bool:
        if value and not _is_staff(self.context["request"].user):
            raise serializers.ValidationError("Customers cannot create internal notes.")
        return value


class TicketListSerializer(serializers.ModelSerializer):
    requester = UserMiniSerializer(read_only=True)
    assignee = UserMiniSerializer(read_only=True)
    tags = serializers.SlugRelatedField(slug_field="name", many=True, read_only=True)

    class Meta:
        model = Ticket
        fields = [
            "id",
            "title",
            "status",
            "priority",
            "category",
            "requester",
            "assignee",
            "tags",
            "triage_status",
            "created_at",
            "updated_at",
        ]


class TicketDetailSerializer(TicketListSerializer):
    comments = serializers.SerializerMethodField()

    class Meta(TicketListSerializer.Meta):
        fields = [
            *TicketListSerializer.Meta.fields,
            "description",
            "comments",
            "suggested_reply",
            "triage_source",
            "triage_model",
            "triage_latency_ms",
            "triage_error",
            "triaged_at",
        ]

    @extend_schema_field(CommentSerializer(many=True))
    def get_comments(self, obj: Ticket):
        comments = obj.comments.all()
        if not _is_staff(self.context["request"].user):
            comments = comments.filter(is_internal=False)
        return CommentSerializer(comments, many=True, context=self.context).data

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not _is_staff(self.context["request"].user):
            for field in _STAFF_ONLY_FIELDS:
                data[field] = None
        return data


class TicketCreateSerializer(serializers.ModelSerializer):
    title = serializers.CharField(min_length=3, max_length=200)
    description = serializers.CharField(min_length=10)
    tags = serializers.SlugRelatedField(
        slug_field="name",
        many=True,
        queryset=Tag.objects.all(),
        required=False,
    )

    class Meta:
        model = Ticket
        fields = [
            "id",
            "title",
            "description",
            "tags",
            "status",
            "priority",
            "category",
            "triage_status",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "priority",
            "category",
            "triage_status",
            "created_at",
        ]


class CustomerTicketUpdateSerializer(serializers.ModelSerializer):
    title = serializers.CharField(min_length=3, max_length=200, required=False)
    description = serializers.CharField(min_length=10, required=False)

    class Meta:
        model = Ticket
        fields = ["title", "description"]

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError({"non_field_errors": "Expected an object."})
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {field: "Customers cannot change this field." for field in sorted(unknown)}
            )
        return super().to_internal_value(data)

    def validate(self, attrs):
        if attrs and self.instance.status != Ticket.Status.OPEN:
            raise serializers.ValidationError("Customers can edit a ticket only while it is open.")
        return attrs


class AgentTicketUpdateSerializer(serializers.ModelSerializer):
    title = serializers.CharField(min_length=3, max_length=200, required=False)
    description = serializers.CharField(min_length=10, required=False)
    tags = serializers.SlugRelatedField(
        slug_field="name",
        many=True,
        queryset=Tag.objects.all(),
        required=False,
    )
    assignee = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role__in=[User.Role.AGENT, User.Role.ADMIN]),
        allow_null=True,
        required=False,
    )

    class Meta:
        model = Ticket
        fields = ["title", "description", "status", "priority", "category", "assignee", "tags"]

    def validate(self, attrs):
        if "status" in attrs:
            try:
                ensure_transition(self.instance.status, attrs["status"])
            except TransitionError as exc:
                raise serializers.ValidationError({"status": str(exc)}) from exc
        return attrs
