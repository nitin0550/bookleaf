from rest_framework import serializers

from .models import Author, Book
from .royalty import author_royalty_summary, book_royalty_flags


class BookSerializer(serializers.ModelSerializer):
    is_published = serializers.BooleanField(read_only=True)
    production_progress = serializers.SerializerMethodField()
    royalty_flags = serializers.SerializerMethodField()

    class Meta:
        model = Book
        fields = [
            "book_id", "title", "isbn", "genre", "publication_date", "status", "is_published",
            "production_progress", "mrp", "author_royalty_per_copy", "total_copies_sold",
            "total_royalty_earned", "royalty_paid", "royalty_pending", "last_royalty_payout_date",
            "print_partner", "available_on", "royalty_flags",
        ]

    def get_production_progress(self, obj) -> dict:
        return obj.production_progress

    def get_royalty_flags(self, obj) -> dict:
        return book_royalty_flags(obj)


class BookRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Book
        fields = ["book_id", "title", "status"]


class AuthorRefSerializer(serializers.ModelSerializer):
    name = serializers.CharField(read_only=True)
    email = serializers.EmailField(read_only=True)

    class Meta:
        model = Author
        fields = ["author_id", "name", "email", "city"]


class AuthorContextSerializer(serializers.ModelSerializer):
    """Everything an agent needs about the author while handling a ticket."""

    name = serializers.CharField(read_only=True)
    email = serializers.EmailField(read_only=True)
    books = BookSerializer(many=True, read_only=True)
    royalty_summary = serializers.SerializerMethodField()

    class Meta:
        model = Author
        fields = ["author_id", "name", "email", "phone", "city", "joined_date",
                  "bank_account_linked", "royalty_summary", "books"]

    def get_royalty_summary(self, obj) -> dict:
        return author_royalty_summary(obj)
