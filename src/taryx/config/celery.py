import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taryx.config.settings")

app = Celery("taryx")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
