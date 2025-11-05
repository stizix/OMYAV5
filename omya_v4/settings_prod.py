# omya_v4/settings_prod.py
import os
from pathlib import Path

# Map des variables Render -> variables attendues par ton settings de base
if os.environ.get("SECRET_KEY"):
    os.environ["DJANGO_SECRET_KEY"] = os.environ["SECRET_KEY"]

if os.environ.get("DEBUG") is not None:
    # "0"/"1" -> "False"/"True"
    os.environ["DJANGO_DEBUG"] = "True" if os.environ["DEBUG"] in ("1", "true", "True") else "False"

if os.environ.get("ALLOWED_HOSTS"):
    os.environ["DJANGO_ALLOWED_HOSTS"] = os.environ["ALLOWED_HOSTS"]

if os.environ.get("CSRF_TRUSTED_ORIGINS"):
    os.environ["DJANGO_TRUSTED_CSRF_ORIGINS"] = os.environ["CSRF_TRUSTED_ORIGINS"]

# Timezone prod (Europe/Paris) si non fourni
os.environ.setdefault("DJANGO_TIME_ZONE", "Europe/Paris")

# Importe TOUT ton settings de base (apps, AUTH_USER_MODEL, allauth, etc.)
from .settings import *  # noqa: E402,F401,F403

# ---------- Overrides PROD ----------
BASE_DIR = Path(__file__).resolve().parent.parent  # omya_v4/

# Forcer HTTPS en prod
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"

# Static (WhiteNoise)
STATIC_URL = os.environ.get("STATIC_URL", "static/")
STATIC_ROOT = os.environ.get("STATIC_ROOT") or str(BASE_DIR.parent / "staticfiles")
if "whitenoise.middleware.WhiteNoiseMiddleware" not in MIDDLEWARE:
    # juste après SecurityMiddleware
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# Media (disk Render si monté)
MEDIA_URL = "/media/"
MEDIA_ROOT = os.environ.get("MEDIA_ROOT") or "/opt/render/project/src/media"

# CORS (si activé côté env)
if "corsheaders" not in INSTALLED_APPS:
    INSTALLED_APPS.append("corsheaders")
if "corsheaders.middleware.CorsMiddleware" not in MIDDLEWARE:
    # avant CommonMiddleware
    MIDDLEWARE.insert(2, "corsheaders.middleware.CorsMiddleware")
# Valeurs déjà lues depuis DJANGO_TRUSTED_CSRF_ORIGINS / CORS_ALLOWED_ORIGINS via settings de base
CORS_ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()]

# Redis / Celery (ton settings de base lit déjà REDIS_URL)
REDIS_URL = os.environ.get("REDIS_URL", REDIS_URL)  # garde la valeur si déjà définie

# Base de données (utilise dj-database-url pour SSL correct de Render)
try:
    import dj_database_url  # type: ignore

    if os.environ.get("DATABASE_URL"):
        DATABASES = {
            "default": dj_database_url.parse(
                os.environ["DATABASE_URL"],
                conn_max_age=600,
                ssl_require=True,
            )
        }
except Exception:
    # fallback sur ton parsing de base
    pass

# Stripe (déjà lus par ton settings de base, on s'assure qu'ils existent)
STRIPE_PUBLIC_KEY = os.environ.get("STRIPE_PUBLIC_KEY", STRIPE_PUBLIC_KEY if "STRIPE_PUBLIC_KEY" in globals() else None)
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", STRIPE_SECRET_KEY if "STRIPE_SECRET_KEY" in globals() else "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", STRIPE_WEBHOOK_SECRET if "STRIPE_WEBHOOK_SECRET" in globals() else "")
