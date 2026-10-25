from django.conf import settings
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path, re_path
from django.views.generic import TemplateView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from apps.accounts.views import LoginView, LogoutView, MeView, StaffListView
from apps.catalog.views import BookDetailView, BookListView
from apps.support.views import AdminStatsView, MetaView, TicketViewSet

router = DefaultRouter(trailing_slash=True)
router.register("tickets", TicketViewSet, basename="ticket")


def api_not_found(request, *args, **kwargs):
    return JsonResponse(
        {"error": {"code": "not_found", "message": "No such API endpoint.", "details": None}}, status=404
    )


api_patterns = [
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/logout/", LogoutView.as_view(), name="logout"),
    path("auth/me/", MeView.as_view(), name="me"),
    path("books/", BookListView.as_view(), name="book-list"),
    path("books/<str:book_id>/", BookDetailView.as_view(), name="book-detail"),
    path("staff/", StaffListView.as_view(), name="staff-list"),
    path("admin/stats/", AdminStatsView.as_view(), name="admin-stats"),
    path("meta/", MetaView.as_view(), name="meta"),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger"),
    path("", include(router.urls)),
    re_path(r"^.*$", api_not_found),
]

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("api/", include(api_patterns)),
    path("healthz", lambda r: JsonResponse({"ok": True})),
]

# Note: uploaded attachments are deliberately NOT exposed under /media; they are served
# by the authenticated /api/tickets/{id}/attachment/ endpoint.

# Single-page app: any other path returns the built React index.html.
if (settings.FRONTEND_DIST / "index.html").exists():
    urlpatterns += [re_path(r"^(?!api/|django-admin/|media/|static/).*$",
                            TemplateView.as_view(template_name="index.html"))]
