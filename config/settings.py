import os
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "development-only-change-me")
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = [
    host for host in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if host
]
CSRF_TRUSTED_ORIGINS = [url for url in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if url]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.openid_connect",
    "ledger",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "rsu"),
        "USER": os.environ.get("POSTGRES_USER", "rsu"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}
AUTH_USER_MODEL = "ledger.User"
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {"staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SESSION_COOKIE_SECURE = os.environ.get("APP_URL", "http://localhost:8000").startswith("https://")
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_LOGIN_METHODS = {"email", "username"}
ACCOUNT_SIGNUP_ENABLED = False

if os.environ.get("OIDC_ISSUER_URL"):
    SOCIALACCOUNT_PROVIDERS = {
        "openid_connect": {
            "OAUTH_PKCE_ENABLED": True,
            "APPS": [
                {
                    "provider_id": "company",
                    "name": "Company SSO",
                    "client_id": os.environ["OIDC_CLIENT_ID"],
                    "secret": os.environ["OIDC_CLIENT_SECRET"],
                    "settings": {
                        "server_url": os.environ["OIDC_ISSUER_URL"],
                        "fetch_userinfo": True,
                        "oauth_pkce_enabled": True,
                    },
                }
            ],
        }
    }

SCIM_ENABLED = bool(os.environ.get("SCIM_BEARER_TOKEN"))
if SCIM_ENABLED:
    INSTALLED_APPS.append("django_scim")
    scim_url = urlparse(os.environ.get("APP_URL", "http://localhost:8000"))
    SCIM_SERVICE_PROVIDER = {
        "NETLOC": scim_url.netloc,
        "SCHEME": scim_url.scheme,
        "AUTHENTICATION_SCHEMES": [
            {
                "type": "oauthbearertoken",
                "name": "Bearer token",
                "description": "Dedicated SCIM bearer token",
            }
        ],
        "AUTH_CHECK_MIDDLEWARE": "ledger.scim.ScimBearerAuthMiddleware",
        "GROUP_ADAPTER": "ledger.scim.DjangoGroupAdapter",
        "WWW_AUTHENTICATE_HEADER": "Bearer",
    }
