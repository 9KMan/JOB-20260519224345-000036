"""
REST API serializers for fuel billing.
"""
from rest_framework import serializers

from api.models import (
    BillingCycle,
    Client,
    FuelTransaction,
    Invoice,
    InvoiceLineItem,
)


class ClientSerializer(serializers.ModelSerializer):
    """Serializer for Client model."""

    class Meta:
        model = Client
        fields = [
            "id",
            "relay_client_id",
            "name",
            "email",
            "billing_config",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class FuelTransactionSerializer(serializers.ModelSerializer):
    """Serializer for FuelTransaction model."""

    class Meta:
        model = FuelTransaction
        fields = [
            "id",
            "client",
            "relay_transaction_id",
            "transaction_date",
            "gallons",
            "price_per_gallon",
            "total_amount",
            "fuel_type",
            "is_invoiced",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class InvoiceLineItemSerializer(serializers.ModelSerializer):
    """Serializer for InvoiceLineItem model."""

    class Meta:
        model = InvoiceLineItem
        fields = [
            "id",
            "description",
            "gallons",
            "price_per_gallon",
            "line_total",
        ]


class InvoiceSerializer(serializers.ModelSerializer):
    """Serializer for Invoice model."""

    client_name = serializers.CharField(source="client.name", read_only=True)

    class Meta:
        model = Invoice
        fields = [
            "id",
            "client",
            "client_name",
            "billing_period_start",
            "billing_period_end",
            "total_amount",
            "status",
            "sent_at",
            "paid_at",
            "delivery_status",
            "created_at",
        ]
        read_only_fields = ["id", "sent_at", "paid_at", "created_at"]


class InvoiceDetailSerializer(InvoiceSerializer):
    """Detailed serializer for Invoice model with line items."""

    items = InvoiceLineItemSerializer(many=True, read_only=True)

    class Meta(InvoiceSerializer.Meta):
        fields = InvoiceSerializer.Meta.fields + ["items"]


class BillingCycleSerializer(serializers.ModelSerializer):
    """Serializer for BillingCycle model."""

    class Meta:
        model = BillingCycle
        fields = [
            "id",
            "week_start",
            "week_end",
            "status",
            "invoices_generated",
            "clients_processed",
            "total_amount",
            "completed_at",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]