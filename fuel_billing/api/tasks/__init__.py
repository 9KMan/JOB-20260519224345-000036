"""
Celery tasks for fuel billing.
"""
import logging
from datetime import date, timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def pull_transactions_task(self):
    """
    Pull latest transactions from Relay API for all clients.
    Runs every 15 minutes via Celery Beat.
    """
    from api.services.transaction_processor import transaction_processor

    try:
        logger.info("Starting transaction pull for all clients")
        result = transaction_processor.sync_all_clients()
        logger.info(
            f"Transaction pull complete: {result['processed']} processed, "
            f"{result['skipped_duplicates']} duplicates, {result['errors']} errors"
        )
        return result
    except Exception as exc:
        logger.error(f"Transaction pull failed: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=600)
def generate_weekly_invoices(self):
    """
    Generate weekly invoices for all active clients.
    Runs every Monday at 6am UTC via Celery Beat.
    """
    from api.services.billing import billing_service

    try:
        logger.info("Starting weekly invoice generation")
        cycle = billing_service.create_weekly_billing_cycle()
        result = billing_service.generate_invoices_for_cycle(cycle)
        logger.info(
            f"Invoice generation complete: {result['invoices_created']} invoices, "
            f"{result['errors']} errors"
        )
        return result
    except Exception as exc:
        logger.error(f"Invoice generation failed: {exc}")
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def send_invoice_emails(self):
    """
    Send pending invoices via email.
    Runs every 5 minutes via Celery Beat.
    """
    from api.models import Invoice
    from api.services.billing import billing_service

    sent_count = 0
    failed_count = 0

    pending_invoices = Invoice.objects.filter(
        status="DRAFT",
        delivery_status="pending",
    ).select_related("client")

    for invoice in pending_invoices:
        try:
            if billing_service.send_invoice_email(invoice):
                sent_count += 1
            else:
                failed_count += 1
        except Exception as exc:
            logger.error(f"Failed to send invoice {invoice.id}: {exc}")
            failed_count += 1

    logger.info(f"Invoice email send complete: {sent_count} sent, {failed_count} failed")
    return {"sent": sent_count, "failed": failed_count}


@shared_task(bind=True, max_retries=3, default_retry_delay=3600)
def check_invoice_status(self):
    """
    Check and update invoice payment status.
    Runs daily via Celery Beat.
    """
    from api.models import Invoice

    today = date.today()
    overdue_threshold = today - timedelta(days=30)

    overdue_invoices = Invoice.objects.filter(
        status="SENT",
        billing_period_end__lt=overdue_threshold,
    )

    updated_count = 0
    for invoice in overdue_invoices:
        invoice.status = "OVERDUE"
        invoice.save(update_fields=["status"])
        updated_count += 1

    logger.info(f"Invoice status check complete: {updated_count} marked overdue")
    return {"updated": updated_count}