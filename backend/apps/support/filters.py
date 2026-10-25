import django_filters
from django.db.models import Q
from django.utils import timezone

from .models import Category, Priority, Ticket


class CommaMultipleChoiceFilter(django_filters.BaseInFilter, django_filters.CharFilter):
    """?status=open,in_progress"""


class TicketFilter(django_filters.FilterSet):
    status = CommaMultipleChoiceFilter(field_name="status")
    category = CommaMultipleChoiceFilter(field_name="category")
    priority = CommaMultipleChoiceFilter(field_name="priority")
    created_after = django_filters.DateFilter(field_name="created_at", lookup_expr="date__gte")
    created_before = django_filters.DateFilter(field_name="created_at", lookup_expr="date__lte")
    assigned = django_filters.CharFilter(method="filter_assigned", help_text="me | unassigned | <user id>")
    overdue = django_filters.BooleanFilter(method="filter_overdue")
    awaiting_staff = django_filters.BooleanFilter(field_name="awaiting_staff")
    author = django_filters.CharFilter(field_name="author__author_id")
    q = django_filters.CharFilter(method="filter_search", help_text="Search subject, author, book title")

    class Meta:
        model = Ticket
        fields = []

    def filter_assigned(self, qs, name, value):
        if value == "me":
            return qs.filter(assigned_to=self.request.user)
        if value == "unassigned":
            return qs.filter(assigned_to__isnull=True)
        if value.isdigit():
            return qs.filter(assigned_to_id=int(value))
        return qs

    def filter_overdue(self, qs, name, value):
        cond = Q(status__in=Ticket.UNRESOLVED_STATUSES, first_response_at__isnull=True,
                 sla_due_at__lt=timezone.now())
        return qs.filter(cond) if value else qs.exclude(cond)

    def filter_search(self, qs, name, value):
        value = value.strip()
        if not value:
            return qs
        cond = (Q(subject__icontains=value) | Q(author__user__full_name__icontains=value)
                | Q(book__title__icontains=value) | Q(author__author_id__iexact=value))
        ref = value.upper().removeprefix("BL-")
        if ref.isdigit():
            cond |= Q(pk=int(ref))
        return qs.filter(cond)


# Used by the OpenAPI docs to show valid values.
VALID_VALUES = {
    "status": [s.value for s in Ticket.Status],
    "category": [c.value for c in Category],
    "priority": [p.value for p in Priority],
}
