from celery import Celery
from .config import settings
from .db import Session, User, initialize, user_snapshot
from .service import run_scan, prepare_application

celery = Celery("career", broker=settings.redis_url, backend=settings.redis_url)
celery.conf.update(
    timezone="UTC",
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    beat_schedule={"discover-hourly": {"task": "career.scan", "schedule": 3600.0}},
    worker_concurrency=1,
)


@celery.task(name="career.scan")
def scan():
    """Beat runs this hourly; each account starts only when its own interval is due."""
    from .scheduler import due_users, scheduled_scan

    initialize()
    for user in due_users():
        scheduled_scan(user)


@celery.task(name="career.prepare")
def prepare(job_id, user_id):
    prepare_application(job_id, user_id)


@celery.task(name="career.scan_existing")
def scan_existing(run_id, user_id):
    run_scan(run_id, user_id)
