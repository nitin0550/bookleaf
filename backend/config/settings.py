"""
Django settings for the BookLeaf Author Support Portal.

All secrets and environment-specific values come from environment variables
(optionally loaded from backend/.env in local development). Nothing secret is
hardcoded here, and the LLM API key is never exposed to the frontend.
"""
import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent

load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY") or (
    "dev-only-insecure-key-change-me" if DEBUG else None
)
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is false.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third party
    "rest_framework",
    "rest_framework.authtoken",
    "django_filters",
    "drf_spectacular",
    "corsheaders",
    # local
    "apps.accounts",
    "apps.catalog",
    "apps.support",
    "apps.ai",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

# The production React build (frontend/dist) is served by Django + WhiteNoise so
# the whole app deploys as a single service.
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [FRONTEND_DIST],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=60,
    )
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [FRONTEND_DIST] if FRONTEND_DIST.exists() else []
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
WHITENOISE_ROOT = FRONTEND_DIST if FRONTEND_DIST.exists() else None

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- CORS (only needed when the frontend is served from a different origin) ---
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:5173")

# --- Django REST Framework ---
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
        "rest_framework.filters.SearchFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "apps.support.pagination.StandardPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "config.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.AnonRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "user": "600/min",
        "anon": "30/min",
        "ticket_create": "10/hour",
        "ai_draft": "60/hour",
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "BookLeaf Author Support API",
    "DESCRIPTION": (
        "REST API for the BookLeaf Author Support & Communication Portal. "
        "Authenticate with `POST /api/auth/login/` and send the returned token as "
        "`Authorization: Token <token>`."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "ENUM_NAME_OVERRIDES": {
        "TicketStatusEnum": "apps.support.models.Ticket.Status",
        "CategoryEnum": "apps.support.models.Category",
        "PriorityEnum": "apps.support.models.Priority",
        "ValueSourceEnum": "apps.support.models.Source",
    },
}

# --- AI / LLM configuration (keys only ever read server-side) ---
AI = {
    "PROVIDER": os.getenv("AI_PROVIDER", "anthropic"),
    "API_KEY": os.getenv("ANTHROPIC_API_KEY", ""),
    "MODEL": os.getenv("AI_MODEL", "claude-haiku-4-5"),
    "TIMEOUT_SECONDS": float(os.getenv("AI_TIMEOUT_SECONDS", "20")),
    "MAX_RETRIES": int(os.getenv("AI_MAX_RETRIES", "2")),
    # Run classification in a background thread so ticket creation never waits on the LLM.
    "ASYNC_CLASSIFICATION": env_bool("AI_ASYNC_CLASSIFICATION", True),
    # Indicative USD prices per million tokens, used only for the cost dashboard.
    "PRICE_INPUT_PER_MTOK": float(os.getenv("AI_PRICE_INPUT_PER_MTOK", "1.0")),
    "PRICE_OUTPUT_PER_MTOK": float(os.getenv("AI_PRICE_OUTPUT_PER_MTOK", "5.0")),
}

# Optional fixed "today" for royalty-cycle maths (e.g. BOOKLEAF_REFERENCE_DATE=2026-01-10)
# so demo answers stay consistent with the sample dataset. Empty = real date.
BOOKLEAF_REFERENCE_DATE = os.getenv("BOOKLEAF_REFERENCE_DATE") or None

# --- Ticket attachments ---
ATTACHMENT_MAX_BYTES = int(os.getenv("ATTACHMENT_MAX_BYTES", str(5 * 1024 * 1024)))
ATTACHMENT_ALLOWED_EXTENSIONS = ["png", "jpg", "jpeg", "pdf", "webp"]
DATA_UPLOAD_MAX_MEMORY_SIZE = ATTACHMENT_MAX_BYTES + 1024 * 1024

# --- Security hardening for production ---
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "loggers": {
        "apps": {"handlers": ["console"], "level": os.getenv("APP_LOG_LEVEL", "INFO")},
    },
}
