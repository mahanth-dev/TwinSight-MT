import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = BASE_DIR.parent

SECRET_KEY = "mt-tahlil-local-dev-only-not-for-production"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "tahlil.apps.TahlilConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
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
                "tahlil.context_processors.brand",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"

(BASE_DIR / "data").mkdir(parents=True, exist_ok=True)

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "data" / "mt_tahlil.sqlite3",
    }
}

LANGUAGE_CODE = "fa"
TIME_ZONE = "Asia/Tehran"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

BACKUP_ROOT = Path(
    os.environ.get(
        "ASAREH_BACKUP",
        str(
            WORKSPACE_DIR
            / "extracted"
            / "backup-8.31.2026_11-41-18_asarehsp"
        ),
    )
)
_local_uploads = BASE_DIR / "data" / "uploads"
UPLOADS_ROOT = Path(
    os.environ.get(
        "ASAREH_UPLOADS",
        str(_local_uploads if _local_uploads.exists() else BACKUP_ROOT / "homedir" / "public_html" / "wp-content" / "uploads"),
    )
)
SQL_PATH = BACKUP_ROOT / "mysql" / "asarehsp_asaresp.sql"
SITE_URL = "https://asarehsport.com"
CSRF_TRUSTED_ORIGINS = [
    "http://localhost:8765",
    "http://127.0.0.1:8765",
]
LOGIN_URL = "/admin/login/"
LOGIN_REDIRECT_URL = "/manage/"
