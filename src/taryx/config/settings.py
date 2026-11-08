import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[3]

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "taryx-development-only-secret-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() in {"1", "true", "yes"}
ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",") if h]
# Session-authenticated GraphQL stays CSRF-enforced; the dev portal origin
# must be explicitly trusted because the Vite proxy forwards the browser's
# Origin header while rewriting Host (decision 004).
CSRF_TRUSTED_ORIGINS = [
    o
    for o in os.environ.get(
        "DJANGO_CSRF_TRUSTED_ORIGINS", "http://localhost:5174,http://127.0.0.1:5174"
    ).split(",")
    if o
]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "graphene_django",
    "taryx.core.accounts",
    "taryx.core.audit",
    "taryx.core.metering",
    "taryx.core.pricing",
    "taryx.core.billing",
    "taryx.core.migration",
    "taryx.core.market",
    "taryx.composition",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]

ROOT_URLCONF = "taryx.config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
    },
]

WSGI_APPLICATION = "taryx.config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "taryx"),
        "USER": os.environ.get("POSTGRES_USER", "taryx"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "taryx"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "55432"),
    },
    # Restricted credential for shadow/comparison evidence paths: the
    # database itself denies this role writes to financial and
    # evidence-of-record tables (see migration 0001 grants).
    "shadow": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "taryx"),
        "USER": os.environ.get("POSTGRES_SHADOW_USER", "taryx_shadow"),
        "PASSWORD": os.environ.get("POSTGRES_SHADOW_PASSWORD", "taryx_shadow"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "55432"),
        "TEST": {"MIRROR": "default"},
    },
}

LANGUAGE_CODE = "en-au"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

GRAPHENE = {"SCHEMA": "taryx.interfaces.graphql.schema.schema"}

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "amqp://taryx:taryx@localhost:5673/taryx")

# Independently deployed legacy calculator (satellite service, own schema).
LEGACY_BASE_URL = os.environ.get("LEGACY_BASE_URL", "http://localhost:18090")

# Bounded market integration (decision 005): synthetic taryx-market/1
# coordinator, one token in each direction, durable workflow + inbox +
# outbox. Deadlines are short for the local demo.
MARKET_BASE_URL = os.environ.get("MARKET_BASE_URL", "http://localhost:18092")
MARKET_TOKEN = os.environ.get("MARKET_TOKEN", "taryx-market-token")
MARKET_CALLBACK_TOKEN = os.environ.get("MARKET_CALLBACK_TOKEN", "taryx-market-token")
MARKET_CALLBACK_URL = os.environ.get(
    "MARKET_CALLBACK_URL", "http://localhost:8001/callbacks/transfers"
)
MARKET_OUTCOME_DEADLINE_SECONDS = int(os.environ.get("MARKET_OUTCOME_DEADLINE_SECONDS", "30"))
MARKET_RECONCILE_BUDGET_SECONDS = int(os.environ.get("MARKET_RECONCILE_BUDGET_SECONDS", "120"))
MARKET_MAX_ATTEMPTS = int(os.environ.get("MARKET_MAX_ATTEMPTS", "5"))
MARKET_RETRY_SECONDS = int(os.environ.get("MARKET_RETRY_SECONDS", "5"))

CELERY_BEAT_SCHEDULE = {
    "market-sweep": {"task": "taryx.market.sweep", "schedule": 10.0},
    "market-drain": {"task": "taryx.market.drain", "schedule": 10.0},
}
LEGACY_TIMEOUT_SECONDS = float(os.environ.get("LEGACY_TIMEOUT_SECONDS", "5"))
CELERY_IMPORTS = ["taryx.interfaces.tasks"]
CELERY_TASK_TRACK_STARTED = True
CELERY_WORKER_ENABLE_REMOTE_CONTROL = False
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
