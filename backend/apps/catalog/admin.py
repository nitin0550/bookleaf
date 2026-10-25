from django.contrib import admin

from .models import Author, Book


class BookInline(admin.TabularInline):
    model = Book
    extra = 0
    fields = ["book_id", "title", "status", "total_copies_sold", "royalty_pending"]


@admin.register(Author)
class AuthorAdmin(admin.ModelAdmin):
    list_display = ["author_id", "name", "email", "city", "joined_date"]
    search_fields = ["author_id", "user__full_name", "user__email"]
    inlines = [BookInline]


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ["book_id", "title", "author", "status", "total_copies_sold", "royalty_pending"]
    list_filter = ["status", "print_partner"]
    search_fields = ["book_id", "title", "isbn"]
