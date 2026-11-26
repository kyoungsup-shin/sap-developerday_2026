"""Minimal Django settings for the stateless A2A demo gateway."""
from __future__ import annotations

import os

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "unsafe-local-demo-key")
DEBUG = os.getenv("DJANGO_DEBUG", "true").lower() == "true"
ALLOWED_HOSTS = [host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if host.strip()]
ROOT_URLCONF = "config.urls"
INSTALLED_APPS: list[str] = []
MIDDLEWARE: list[str] = []
TEMPLATES: list[dict[str, object]] = []
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
USE_TZ = True
DEFAULT_CHARSET = "utf-8"
