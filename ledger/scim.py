import hmac
import os

from django.http import HttpResponse
from django_scim.adapters import SCIMGroup


class DjangoGroupAdapter(SCIMGroup):
    """Adapt Django's built-in Group model to SCIM without schema changes."""

    id_field = "id"

    def to_dict(self):
        data = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
            "id": self.id,
            "externalId": "",
            "displayName": self.display_name,
            "members": self.members,
            "meta": self.meta,
        }
        return data

    def from_dict(self, data):
        self.obj.name = data.get("displayName") or ""


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
