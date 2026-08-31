"""Django settings used exclusively by the automated test suite."""

from .settings import *

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

SCIM_ENABLED = True
INSTALLED_APPS.append("django_scim")
SCIM_SERVICE_PROVIDER = {
    "NETLOC": "testserver",
    "SCHEME": "http",
    "AUTHENTICATION_SCHEMES": [{"type": "oauthbearertoken", "name": "Bearer token"}],
    "AUTH_CHECK_MIDDLEWARE": "ledger.scim.ScimBearerAuthMiddleware",
    "GROUP_ADAPTER": "ledger.scim.DjangoGroupAdapter",
    "WWW_AUTHENTICATE_HEADER": "Bearer",
}
