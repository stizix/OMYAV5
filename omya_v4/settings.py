# Django settings for omya_v4 project.
import os
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv

# Charge .env à la racine (dev/local)
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# -------------------------
# Core / Security
# -------------------------
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "False").lower() == "true"

ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("DJANGO_TRUSTED_CSRF_ORIGINS", "").split(",") if o.strip()]

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

# -------------------------
# Apps
# -------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Project apps
    "commons",
    "subscriptions",
    "accounts",
    "courses",
    "django.contrib.sites",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
]
SITE_ID = 1

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

ROOT_URLCONF = "omya_v4.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],  # pas une app, juste un dossier
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

WSGI_APPLICATION = "omya_v4.wsgi.application"

# -------------------------
# Database
# -------------------------
# Si DATABASE_URL est défini -> l'utiliser (Postgres recommandé en prod)
# Sinon -> SQLite (défaut)
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

if DATABASE_URL:
    # Parsing simple (sans dj-database-url pour rester léger)
    parsed = urlparse(DATABASE_URL)
    ENGINE_MAP = {
        "postgres": "django.db.backends.postgresql",
        "postgresql": "django.db.backends.postgresql",
        "psql": "django.db.backends.postgresql",
        "mysql": "django.db.backends.mysql",
        "mariadb": "django.db.backends.mysql",
        "sqlite": "django.db.backends.sqlite3",
    }
    ENGINE = ENGINE_MAP.get(parsed.scheme, "django.db.backends.postgresql")
    DB_NAME = parsed.path.lstrip("/")
    DATABASES = {
        "default": {
            "ENGINE": ENGINE,
            "NAME": DB_NAME,
            "USER": parsed.username,
            "PASSWORD": parsed.password,
            "HOST": parsed.hostname,
            "PORT": parsed.port or "",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# -------------------------
# Auth / Passwords
# -------------------------
AUTH_USER_MODEL = "accounts.CustomUser"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# -------------------------
# Static & Media
# -------------------------
STATIC_URL = "static/"
STATIC_ROOT = os.environ.get("STATIC_ROOT") or str(BASE_DIR / "staticfiles")

MEDIA_URL = "/media/"
MEDIA_ROOT = os.environ.get("MEDIA_ROOT") or str(BASE_DIR / "media")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# -------------------------
# Third-party keys (env)
# -------------------------
STRIPE_PUBLIC_KEY = os.environ.get("STRIPE_PUBLIC_KEY")
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# -------------------------
# Celery / Redis (optionnel)
# -------------------------
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL

# -------------------------
# Security headers (auto selon DEBUG)
# -------------------------
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = not DEBUG  # redirige vers HTTPS en prod
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
X_FRAME_OPTIONS = "DENY"

# -------------------------
# Logging (utile en dev; sobre en prod)
# -------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "loggers": {
        "django": {"handlers": ["console"], "level": "WARNING",},
        # Décommente pour voir le SQL en dev :
        # "django.db.backends": {"handlers": ["console"], "level": "DEBUG"},
    },
}

ACCOUNT_AUTHENTICATION_METHOD = "email"
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_CONFIRM_EMAIL_ON_GET = False
ACCOUNT_EMAIL_CONFIRMATION_EXPIRE_DAYS = 3

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"  # Dev only
DEFAULT_FROM_EMAIL = "therealomya@gmail.com"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",                # Django par défaut
    "allauth.account.auth_backends.AuthenticationBackend",      # Allauth
]

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD")

DEFAULT_FROM_EMAIL = "OMYA <therealomya@gmail.com>"

ACCOUNT_LOGIN_ATTEMPTS_LIMIT = 5
ACCOUNT_LOGIN_ATTEMPTS_TIMEOUT = 300
SESSION_COOKIE_AGE = 60 * 60 * 24 * 7

LOGIN_URL = 'login'   