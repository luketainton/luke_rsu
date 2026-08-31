import hmac
import os

from django.http import HttpResponse


class ScimBearerAuthMiddleware:
    """SCIM's view decorator: accept only the configured service bearer token."""

    def __init__(self, get_response=None):
        self.get_response = get_response

    def __call__(self, request, *args, **kwargs):
        expected = os.environ.get("SCIM_BEARER_TOKEN", "")
        provided = request.headers.get("Authorization", "")
        if not expected or not hmac.compare_digest(provided, f"Bearer {expected}"):
            response = HttpResponse(status=401)
            response["WWW-Authenticate"] = "Bearer"
            return response
        return self.get_response(request, *args, **kwargs)
