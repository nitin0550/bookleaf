"""
Role-based access control primitives.

Object-level scoping (an author only ever sees their own books and tickets) is
enforced in each view's ``get_queryset`` so that out-of-scope objects return
404 rather than 403 — we never confirm the existence of another author's data.
"""
from rest_framework.permissions import BasePermission


class IsAdmin(BasePermission):
    message = "This action is only available to BookLeaf staff."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_admin)


class IsAuthor(BasePermission):
    message = "This action is only available to authors."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_author
            and hasattr(request.user, "author_profile")
        )
