"""Django settings used exclusively by the automated test suite."""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-django-secret-key")

from .settings import *  # noqa: F403 -- inherit the full production configuration

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

SCIM_ENABLED = True
INSTALLED_APPS = [*INSTALLED_APPS, "django_scim"]  # noqa: F405 -- inherited above
SCIM_SERVICE_PROVIDER = {
    "NETLOC": "testserver",
    "SCHEME": "http",
    "AUTHENTICATION_SCHEMES": [{"type": "oauthbearertoken", "name": "Bearer token"}],
    "AUTH_CHECK_MIDDLEWARE": "ledger.scim.ScimBearerAuthMiddleware",
    "USER_ADAPTER": "ledger.scim.DjangoUserAdapter",
    "GROUP_ADAPTER": "ledger.scim.DjangoGroupAdapter",
    "WWW_AUTHENTICATE_HEADER": "Bearer",
}
