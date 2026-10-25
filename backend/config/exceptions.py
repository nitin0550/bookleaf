"""
Uniform error envelope for every API error.

Every non-2xx response from the API has this shape so the frontend (and any
integrator) can handle errors with a single code path:

    {
      "error": {
        "code": "validation_error",
        "message": "Some fields are invalid.",
        "details": {"subject": ["This field is required."]}
      }
    }
"""
import logging

from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger("apps.api")

_CODE_BY_CLASS = {
    exceptions.ValidationError: ("validation_error", "Some fields are invalid."),
    exceptions.NotAuthenticated: ("not_authenticated", None),
    exceptions.AuthenticationFailed: ("authentication_failed", None),
    exceptions.PermissionDenied: ("permission_denied", None),
    exceptions.NotFound: ("not_found", None),
    exceptions.MethodNotAllowed: ("method_not_allowed", None),
    exceptions.Throttled: ("rate_limited", None),
    exceptions.ParseError: ("malformed_request", None),
    exceptions.UnsupportedMediaType: ("unsupported_media_type", None),
}


class ConflictError(exceptions.APIException):
    """Raised when a request is valid but conflicts with the resource's current state."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "This action conflicts with the current state of the resource."
    default_code = "conflict"


def api_exception_handler(exc, context):
    # Translate Django-native exceptions into DRF ones first.
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, PermissionDenied):
        exc = exceptions.PermissionDenied()
    elif isinstance(exc, DjangoValidationError):
        exc = exceptions.ValidationError(
            exc.message_dict if hasattr(exc, "message_dict") else exc.messages
        )

    response = exception_handler(exc, context)

    if response is None:
        # Unhandled exception: log it with context, return a safe message.
        view = context.get("view")
        logger.exception("Unhandled API error in %s", view.__class__.__name__ if view else "?")
        return Response(
            {
                "error": {
                    "code": "server_error",
                    "message": "Something went wrong on our side. The team has been notified.",
                    "details": None,
                }
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    code, default_message = "error", None
    for klass, (klass_code, klass_message) in _CODE_BY_CLASS.items():
        if isinstance(exc, klass):
            code, default_message = klass_code, klass_message
            break
    else:
        code = getattr(exc, "default_code", "error")

    details = None
    if isinstance(exc, exceptions.ValidationError):
        details = response.data
        # Surface the first message as a human-readable summary.
        message = default_message
        if isinstance(details, dict) and "non_field_errors" in details:
            message = str(details["non_field_errors"][0])
        elif isinstance(details, list) and details:
            message = str(details[0])
    else:
        detail = response.data.get("detail") if isinstance(response.data, dict) else None
        message = str(detail) if detail else (default_message or "Request failed.")

    response.data = {"error": {"code": code, "message": message, "details": details}}
    return response
