import hmac
import os

from django.http import HttpResponse
from django_scim.adapters import SCIMGroup, SCIMUser


class DjangoUserAdapter(SCIMUser):
    """Map SCIM's name fields explicitly onto Django's user name fields."""

    def _apply_name(self, name):
        name = name or {}
        first_name = name.get("givenName")
        last_name = name.get("familyName")
        if first_name is None and last_name is None and name.get("formatted"):
            parts = name["formatted"].strip().split(None, 1)
            first_name = parts[0] if parts else ""
            last_name = parts[1] if len(parts) > 1 else ""
        self.obj.first_name = (first_name or "").strip()
        self.obj.last_name = (last_name or "").strip()

    def from_dict(self, data):
        super().from_dict(data)
        self._apply_name(data.get("name"))

    def handle_replace(self, path, value, operation):
        if path.first_path == ("name", None, None) and isinstance(value, dict):
            self._apply_name(value)
            self.save()
            return
        if path.first_path == ("name", "givenName", None):
            self.obj.first_name = (value or "").strip()
            self.save()
            return
        if path.first_path == ("name", "familyName", None):
            self.obj.last_name = (value or "").strip()
            self.save()
            return
        super().handle_replace(path, value, operation)


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
