from rest_framework import generics

from .models import Book
from .royalty import author_royalty_summary
from .serializers import BookSerializer


class BookListView(generics.ListAPIView):
    """Authors: their own books. Admins: all books (filter with ?author=AUTH001)."""

    serializer_class = BookSerializer
    pagination_class = None
    filterset_fields = {"status": ["exact"]}
    search_fields = ["title", "isbn", "book_id"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # OpenAPI schema generation
            return Book.objects.none()
        qs = Book.objects.select_related("author__user")
        user = self.request.user
        if user.is_admin:
            author = self.request.query_params.get("author")
            return qs.filter(author__author_id=author) if author else qs
        return qs.filter(author__user=user)

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        data = {"results": response.data}
        profile = getattr(request.user, "author_profile", None)
        if profile is not None:
            data["summary"] = author_royalty_summary(profile)
        response.data = data
        return response


class BookDetailView(generics.RetrieveAPIView):
    serializer_class = BookSerializer
    lookup_field = "book_id"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # OpenAPI schema generation
            return Book.objects.none()
        qs = Book.objects.select_related("author__user")
        user = self.request.user
        return qs if user.is_admin else qs.filter(author__user=user)
