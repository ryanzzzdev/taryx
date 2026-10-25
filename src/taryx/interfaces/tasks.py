from celery import shared_task


@shared_task(name="taryx.smoke.ping")
def ping() -> str:
    return "pong"
