import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file():
    """讀取專案根目錄的 .env（KEY=VALUE 每行一組），讓 Google 金鑰不必寫進程式碼。"""
    path = BASE_DIR / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
DEBUG = "RENDER" not in os.environ
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "courses",
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
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "courses.context_processors.site",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

import dj_database_url

import dj_database_url

if os.environ.get("RENDER"):
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("Render 環境缺少 DATABASE_URL，請檢查服務環境變數。")
    DATABASES = {
        "default": dj_database_url.parse(
            database_url,
            conn_max_age=600,
        )
    }
else:
    DATABASES = {
        "default": dj_database_url.config(
            default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
            conn_max_age=600,
        )
    }


AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "zh-hant"
TIME_ZONE = "Asia/Taipei"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "home"


# ---------- 雲端登入（Google、Microsoft）----------
SOCIAL_AUTH = {
    "google": {
        "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
        "secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
    },
    "microsoft": {
        "client_id": os.environ.get("MICROSOFT_CLIENT_ID", ""),
        "secret": os.environ.get("MICROSOFT_CLIENT_SECRET", ""),
        "tenant": os.environ.get("MICROSOFT_TENANT", "common"),
    },
}
# 只允許特定信箱網域登入，例如 "ntub.edu.tw"；留空代表不限制（測試用）
SOCIAL_ALLOWED_DOMAINS = [d.strip().lower() for d in os.environ.get("SOCIAL_ALLOWED_DOMAINS", "").split(",") if d.strip()]
# 部署到網址時可指定，例如 https://coursepuzzle.example.com；本機留空
SOCIAL_REDIRECT_BASE = os.environ.get("SOCIAL_REDIRECT_BASE", "")
