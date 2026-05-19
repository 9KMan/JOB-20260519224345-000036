"""
Data models for Fuel Billing Platform.
"""
import uuid
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models


class Client(models.Model):
    """
    Master client record with billing configuration.
    130 clients total for Relay Payments integration.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    relay_client_id = models.CharField(
        max_length=100, unique=True, db_index=True, help_text="Relay Payments client ID"
    )
    name = models.CharField(max_length=255, help_text="Client business name")
    email = models.EmailField(help_text="Billing email address")
    billing_config = models.JSONField(
        default=dict,
        help_text="Rate per gallon, minimums, discounts as JSON",
    )
    is_active = models.BooleanField(default=True, help_text="Billing enabled")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "client"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["is_active"]),
            models.Index(fields=["relay_client_id"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.relay_client_id})"

    @property
    def rate_per_gallon(self) -> Decimal:
        return Decimal(self.billing_config.get("rate_per_gallon", "0.00"))

    @property
    def minimum_gallons(self) -> Decimal:
        return Decimal(self.billing_config.get("minimum_gallons", "0.00"))


class FuelTransaction(models.Model):
    """
    Fuel transaction record pulled from Relay Payments API.
    Deduplication via unique (relay_transaction_id, client) constraint.
    """

    FUEL_TYPES = [
        ("diesel", "Diesel"),
        ("regular", "Regular"),
        ("premium", "Premium"),
        ("midgrade", "Midgrade"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name="transactions",
        db_index=True,
    )
    relay_transaction_id = models.CharField(
        max_length=100, db_index=True, help_text="Relay API transaction ID"
    )
    transaction_date = models.DateField(db_index=True)
    gallons = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    price_per_gallon = models.DecimalField(
        max_digits=8,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0.0001"))],
    )
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    fuel_type = models.CharField(max_length=20, choices=FUEL_TYPES, default="diesel")
    invoice = models.ForeignKey(
        "Invoice",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="line_items",
    )
    is_invoiced = models.BooleanField(default=False, db_index=True)
    raw_json = models.JSONField(default=dict, help_text="Full Relay API response")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fuel_transaction"
        ordering = ["-transaction_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["relay_transaction_id", "client"],
                name="unique_relay_transaction_per_client",
            ),
        ]
        indexes = [
            models.Index(fields=["client", "transaction_date"]),
            models.Index(fields=["is_invoiced"]),
            models.Index(fields=["transaction_date", "is_invoiced"]),
        ]

    def __str__(self):
        return f"{self.client.name} - {self.gallons}gal on {self.transaction_date}"


class Invoice(models.Model):
    """
    Weekly billing invoice for a client.
    Generated every Monday for the previous week's transactions.
    """

    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("SENT", "Sent"),
        ("PAID", "Paid"),
        ("OVERDUE", "Overdue"),
        ("CANCELLED", "Cancelled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name="invoices",
        db_index=True,
    )
    billing_period_start = models.DateField()
    billing_period_end = models.DateField()
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="DRAFT")
    sent_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    delivery_status = models.CharField(
        max_length=20, default="pending", help_text="Email delivery status"
    )
    pdf_url = models.CharField(max_length=500, blank=True, help_text="S3/storage URL")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "invoice"
        ordering = ["-billing_period_end"]
        indexes = [
            models.Index(fields=["client", "status"]),
            models.Index(fields=["status"]),
            models.Index(fields=["billing_period_end"]),
        ]

    def __str__(self):
        return f"Invoice {self.id} - {self.client.name} ({self.billing_period_start} to {self.billing_period_end})"


class InvoiceLineItem(models.Model):
    """
    Per-transaction line item within an invoice.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name="items",
    )
    transaction = models.OneToOneField(
        FuelTransaction,
        on_delete=models.CASCADE,
        related_name="line_item",
    )
    description = models.CharField(max_length=255)
    gallons = models.DecimalField(max_digits=10, decimal_places=2)
    price_per_gallon = models.DecimalField(max_digits=8, decimal_places=4)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "invoice_line_item"

    def __str__(self):
        return f"LineItem {self.id} - {self.gallons}gal @ ${self.price_per_gallon}"


class BillingCycle(models.Model):
    """
    Weekly billing cycle tracking.
    Created every Monday, tracks generation progress.
    """

    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("PROCESSING", "Processing"),
        ("COMPLETE", "Complete"),
        ("FAILED", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    week_start = models.DateField(db_index=True)
    week_end = models.DateField(db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    invoices_generated = models.IntegerField(default=0)
    clients_processed = models.IntegerField(default=0)
    total_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "billing_cycle"
        ordering = ["-week_start"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["week_start", "week_end"]),
        ]

    def __str__(self):
        return f"BillingCycle {self.week_start} to {self.week_end} [{self.status}]"