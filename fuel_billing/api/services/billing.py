"""
Billing service and invoice generation.
Handles weekly billing cycles, invoice creation, and PDF generation.
"""
import logging
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from typing import Generator

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction as db_transaction
from django.template.loader import render_to_string
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from api.models import (
    BillingCycle,
    Client,
    FuelTransaction,
    Invoice,
    InvoiceLineItem,
)

logger = logging.getLogger(__name__)


class BillingService:
    """
    Handles invoice generation and billing cycle management.
    Processes clients in batches to avoid DB lock contention.
    """

    BATCH_SIZE = 20

    def create_weekly_billing_cycle(self, week_start: date | None = None) -> BillingCycle:
        """
        Create or get existing billing cycle for the given week.
        """
        if week_start is None:
            week_start = self._get_current_week_start()

        week_end = week_start + timedelta(days=6)

        cycle, created = BillingCycle.objects.get_or_create(
            week_start=week_start,
            defaults={
                "week_end": week_end,
                "status": "PENDING",
            },
        )
        return cycle

    def generate_invoices_for_cycle(
        self,
        cycle: BillingCycle,
        batch_size: int = BATCH_SIZE,
    ) -> dict:
        """
        Generate invoices for all active clients in the billing cycle.
        Returns summary statistics.
        """
        cycle.status = "PROCESSING"
        cycle.save()

        active_clients = Client.objects.filter(is_active=True)
        total_clients = active_clients.count()
        invoices_created = 0
        errors = 0

        for idx, client in enumerate(
            active_clients.iterator(chunk_size=batch_size)
        ):
            try:
                invoice = self._generate_client_invoice(client, cycle)
                if invoice:
                    invoices_created += 1
                    cycle.clients_processed = idx + 1
                    cycle.save(update_fields=["clients_processed"])
                logger.info(
                    f"[{idx + 1}/{total_clients}] Invoice generated for {client.name}"
                )
            except Exception as e:
                logger.error(f"Failed to generate invoice for {client.name}: {e}")
                errors += 1

        cycle.status = "COMPLETE" if errors == 0 else "FAILED"
        cycle.invoices_generated = invoices_created
        cycle.completed_at = datetime.now(timezone.utc)
        cycle.save()

        return {
            "cycle_id": str(cycle.id),
            "clients_processed": total_clients,
            "invoices_created": invoices_created,
            "errors": errors,
        }

    def _generate_client_invoice(
        self,
        client: Client,
        cycle: BillingCycle,
    ) -> Invoice | None:
        """
        Generate invoice for a single client for the billing cycle.
        Returns None if no unbilled transactions exist.
        """
        unbilled_txns = FuelTransaction.objects.filter(
            client=client,
            is_invoiced=False,
            transaction_date__gte=cycle.week_start,
            transaction_date__lte=cycle.week_end,
        ).order_by("transaction_date")

        if not unbilled_txns.exists():
            return None

        total_amount = sum(txn.total_amount for txn in unbilled_txns)

        with db_transaction.atomic():
            invoice = Invoice.objects.create(
                client=client,
                billing_period_start=cycle.week_start,
                billing_period_end=cycle.week_end,
                total_amount=total_amount,
                status="DRAFT",
            )

            for txn in unbilled_txns:
                InvoiceLineItem.objects.create(
                    invoice=invoice,
                    transaction=txn,
                    description=f"{txn.fuel_type.title()} - {txn.gallons} gal @ ${txn.price_per_gallon}",
                    gallons=txn.gallons,
                    price_per_gallon=txn.price_per_gallon,
                    line_total=txn.total_amount,
                )
                txn.is_invoiced = True
                txn.invoice = invoice
                txn.save(update_fields=["is_invoiced", "invoice"])

            cycle.total_amount += total_amount

        return invoice

    def _get_current_week_start(self) -> date:
        """Get Monday of current week."""
        today = date.today()
        return today - timedelta(days=today.weekday())

    def send_invoice_email(self, invoice: Invoice) -> bool:
        """
        Send invoice email with PDF attachment to client.
        Returns True if successful.
        """
        try:
            pdf_buffer = self.generate_invoice_pdf(invoice)

            subject = f"Fuel Billing Invoice - {invoice.billing_period_start} to {invoice.billing_period_end}"
            html_message = self._render_invoice_email_html(invoice)
            plain_message = self._render_invoice_email_plain(invoice)

            send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.INVOICE_FROM_EMAIL,
                recipient_list=[invoice.client.email],
                html_message=html_message,
                fail_silently=False,
            )

            invoice.status = "SENT"
            invoice.sent_at = datetime.now(timezone.utc)
            invoice.delivery_status = "delivered"
            invoice.save(update_fields=["status", "sent_at", "delivery_status"])

            logger.info(f"Invoice {invoice.id} sent to {invoice.client.email}")
            return True

        except Exception as e:
            logger.error(f"Failed to send invoice {invoice.id}: {e}")
            invoice.delivery_status = "failed"
            invoice.save(update_fields=["delivery_status"])
            return False

    def generate_invoice_pdf(self, invoice: Invoice) -> BytesIO:
        """Generate PDF for an invoice."""
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=72,
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "Title",
            parent=styles["Heading1"],
            fontSize=24,
            spaceAfter=30,
        )

        elements = []

        elements.append(Paragraph("INVOICE", title_style))
        elements.append(Spacer(1, 12))

        info = [
            ["Invoice Number:", str(invoice.id)],
            ["Client:", invoice.client.name],
            ["Billing Period:", f"{invoice.billing_period_start} to {invoice.billing_period_end}"],
            ["Status:", invoice.status],
            ["Total Amount:", f"${invoice.total_amount:.2f}"],
        ]
        info_table = Table(info, colWidths=[2 * inch, 4 * inch])
        info_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        elements.append(info_table)
        elements.append(Spacer(1, 24))

        line_items = [["Fuel Type", "Gallons", "Price/Gal", "Total"]]
        for item in invoice.items.all():
            line_items.append(
                [
                    item.description,
                    f"{item.gallons:.2f}",
                    f"${item.price_per_gallon:.4f}",
                    f"${item.line_total:.2f}",
                ]
            )

        items_table = Table(line_items, colWidths=[2.5 * inch, 1 * inch, 1.25 * inch, 1.25 * inch])
        items_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ]
            )
        )
        elements.append(items_table)
        elements.append(Spacer(1, 24))

        total_row = [["", "", "Total:", f"${invoice.total_amount:.2f}"]]
        total_table = Table(total_row, colWidths=[2.5 * inch, 1 * inch, 1.25 * inch, 1.25 * inch])
        total_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (2, 0), (-1, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (2, 0), (-1, -1), 12),
                    ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
                ]
            )
        )
        elements.append(total_table)

        doc.build(elements)
        buffer.seek(0)
        return buffer

    def _render_invoice_email_html(self, invoice: Invoice) -> str:
        """Render HTML email body for invoice."""
        return f"""
        <html>
        <body>
            <h1>Invoice {invoice.id}</h1>
            <p>Dear {invoice.client.name},</p>
            <p>Please find attached your invoice for the billing period
            {invoice.billing_period_start} to {invoice.billing_period_end}.</p>
            <p><strong>Total Amount: ${invoice.total_amount:.2f}</strong></p>
            <p>Thank you for your business.</p>
        </body>
        </html>
        """

    def _render_invoice_email_plain(self, invoice: Invoice) -> str:
        """Render plain text email body for invoice."""
        return f"""
Invoice {invoice.id}

Dear {invoice.client.name},

Please find attached your invoice for the billing period
{invoice.billing_period_start} to {invoice.billing_period_end}.

Total Amount: ${invoice.total_amount:.2f}

Thank you for your business.
        """


billing_service = BillingService()