from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import User
from tickets.filters import TicketFilter
from tickets.models import Tag, Ticket
from tickets.permissions import IsAdmin, IsAgentOrAdmin, TicketAccess
from tickets.serializers import (
    AgentTicketUpdateSerializer,
    CommentSerializer,
    CustomerTicketUpdateSerializer,
    TagSerializer,
    TicketCreateSerializer,
    TicketDetailSerializer,
    TicketListSerializer,
)


@extend_schema_view(
    list=extend_schema(summary="List tickets visible to the caller", tags=["tickets"]),
    retrieve=extend_schema(summary="Retrieve a ticket", tags=["tickets"]),
    create=extend_schema(summary="Open a ticket", tags=["tickets"]),
    partial_update=extend_schema(
        summary="Update a ticket",
        description=(
            "Agents and admins can change status along the workflow, plus priority, "
            "category, assignee, tags, title, and description. Customers can change "
            "title and description, and only while the ticket is open."
        ),
        tags=["tickets"],
        request=AgentTicketUpdateSerializer,
        responses=TicketDetailSerializer,
    ),
    destroy=extend_schema(summary="Delete a ticket", tags=["tickets"]),
)
class TicketViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, TicketAccess]
    filterset_class = TicketFilter
    search_fields = ["title", "description"]
    ordering_fields = ["created_at", "updated_at"]
    ordering = ["-created_at"]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        queryset = Ticket.objects.select_related("requester", "assignee").prefetch_related("tags")
        if getattr(self, "action", None) in {"retrieve", "partial_update"}:
            queryset = queryset.prefetch_related("comments__author")
        user = self.request.user
        if getattr(user, "role", None) == User.Role.CUSTOMER:
            queryset = queryset.filter(requester=user)
        return queryset.distinct()

    def get_serializer_class(self):
        if self.action == "create":
            return TicketCreateSerializer
        if self.action == "partial_update":
            role = getattr(self.request.user, "role", None)
            if role == User.Role.CUSTOMER:
                return CustomerTicketUpdateSerializer
            return AgentTicketUpdateSerializer
        if self.action == "list":
            return TicketListSerializer
        return TicketDetailSerializer

    def perform_create(self, serializer):
        serializer.save(requester=self.request.user)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        instance = self.get_queryset().get(pk=instance.pk)
        return Response(TicketDetailSerializer(instance, context={"request": request}).data)

    def destroy(self, request, *args, **kwargs):
        if request.user.role != User.Role.ADMIN:
            raise PermissionDenied("Only admins can delete tickets.")
        return super().destroy(request, *args, **kwargs)

    @extend_schema(
        methods=["GET"],
        summary="List comments on a ticket",
        tags=["comments"],
        filters=False,
        responses=CommentSerializer(many=True),
    )
    @extend_schema(
        methods=["POST"],
        summary="Add a comment",
        tags=["comments"],
        filters=False,
        request=CommentSerializer,
        responses=CommentSerializer,
    )
    @action(detail=True, methods=["get", "post"], url_path="comments")
    def comments(self, request, pk=None):
        ticket = self.get_object()
        if request.method == "POST":
            serializer = CommentSerializer(data=request.data, context={"request": request})
            serializer.is_valid(raise_exception=True)
            serializer.save(ticket=ticket, author=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        comments = ticket.comments.select_related("author")
        if request.user.role == User.Role.CUSTOMER:
            comments = comments.filter(is_internal=False)
        page = self.paginate_queryset(comments)
        serializer = CommentSerializer(page, many=True, context={"request": request})
        return self.get_paginated_response(serializer.data)


@extend_schema_view(
    list=extend_schema(summary="List tags", tags=["tags"]),
    retrieve=extend_schema(summary="Retrieve a tag", tags=["tags"]),
    create=extend_schema(summary="Create a tag", tags=["tags"]),
    destroy=extend_schema(summary="Delete a tag", tags=["tags"]),
)
class TagViewSet(viewsets.ModelViewSet):
    queryset = Tag.objects.all()
    serializer_class = TagSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "delete", "head", "options"]
    search_fields = ["name"]
    ordering_fields = ["name", "created_at"]
    ordering = ["name"]

    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticated(), IsAgentOrAdmin()]
        if self.action == "destroy":
            return [IsAuthenticated(), IsAdmin()]
        return [IsAuthenticated()]
