import os

from celery import Celery

from taryx.diagnostics import install_celery_signals

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taryx.config.settings")

app = Celery("taryx")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Bind task_id/task_name into the structured-log context per task run.
install_celery_signals()
