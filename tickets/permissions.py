from rest_framework.permissions import BasePermission

from accounts.models import User


class TicketAccess(BasePermission):
    """Agents and admins see every ticket. Customers see only their own."""

    message = "You do not have access to this ticket."

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        if user.role in (User.Role.AGENT, User.Role.ADMIN):
            return True
        return obj.requester_id == user.id


class IsAgentOrAdmin(BasePermission):
    message = "Only agents and admins can do that."

    def has_permission(self, request, view) -> bool:
        return request.user.role in (User.Role.AGENT, User.Role.ADMIN)


class IsAdmin(BasePermission):
    message = "Only admins can do that."

    def has_permission(self, request, view) -> bool:
        return request.user.role == User.Role.ADMIN
