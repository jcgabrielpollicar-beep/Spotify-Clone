"""Settings for the PythonAnywhere copy of the site (see deploy/PYTHONANYWHERE_STEPS.md).

Nothing secret lives in this file: the secret key is read from the environment or from a `secret_key.txt`
that is created on the server (and never uploaded anywhere else).
"""
import os

from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F401,F403
from .settings import BASE_DIR

DEBUG = False

_key_file = BASE_DIR / 'secret_key.txt'
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY') or (_key_file.read_text().strip() if _key_file.exists() else '')
if not SECRET_KEY:
    raise ImproperlyConfigured('Create secret_key.txt (see deploy/PYTHONANYWHERE_STEPS.md) or set DJANGO_SECRET_KEY.')

ALLOWED_HOSTS = ['.pythonanywhere.com']
CSRF_TRUSTED_ORIGINS = ['https://*.pythonanywhere.com']

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'            # `collectstatic` copies the CSS / JS here; the Web tab serves it
MEDIA_URL = '/media/'

# PythonAnywhere ends the HTTPS connection in front of Django
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 3600

# this site never sends email (no password reset), so the "development-only email backend" warning does not apply
SILENCED_SYSTEM_CHECKS = ['mail.E001']

ROOT_URLCONF = 'mysite.urls_prod'
