import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "QueshStandards.settings")

app = Celery("QueshStandards")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
