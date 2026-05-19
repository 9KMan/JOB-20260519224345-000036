"""
Celery application configuration for fuel_billing.
"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("fuel_billing")

app.config_from_object("django.conf:settings", namespace="CELERY")

app.autodiscover_tasks()

app.conf.beat_schedule = {
    "pull-transactions-every-15-minutes": {
        "task": "api.tasks.pull_transactions_task",
        "schedule": 900.0,  # 15 minutes
    },
    "generate-weekly-invoices-monday-6am-utc": {
        "task": "api.tasks.generate_weekly_invoices",
        "schedule": {
            "type": "crontab",
            "hour": 6,
            "minute": 0,
            "day_of_week": 0,  # Monday
        },
    },
    "send-invoice-emails": {
        "task": "api.tasks.send_invoice_emails",
        "schedule": 300.0,  # 5 minutes
    },
    "check-invoice-status-daily": {
        "task": "api.tasks.check_invoice_status",
        "schedule": 86400.0,  # 24 hours
    },
}


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f"Request: {self.request!r}")