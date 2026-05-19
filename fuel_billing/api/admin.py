"""
Django Admin configuration for fuel billing.
"""
from django.contrib import admin

from api.models import (
    BillingCycle,
    Client,
    FuelTransaction,
    Invoice,
    InvoiceLineItem,
)


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ["name", "relay_client_id", "email", "is_active", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["name", "relay_client_id", "email"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(FuelTransaction)
class FuelTransactionAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "client",
        "relay_transaction_id",
        "transaction_date",
        "gallons",
        "total_amount",
        "is_invoiced",
    ]
    list_filter = ["fuel_type", "is_invoiced", "transaction_date"]
    search_fields = ["relay_transaction_id", "client__name"]
    readonly_fields = ["id", "created_at"]
    raw_id_fields = ["client", "invoice"]


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "client",
        "billing_period_start",
        "billing_period_end",
        "total_amount",
        "status",
        "delivery_status",
        "sent_at",
    ]
    list_filter = ["status", "delivery_status"]
    search_fields = ["client__name"]
    readonly_fields = ["id", "created_at", "updated_at"]
    raw_id_fields = ["client"]

    actions = ["regenerate_invoices", "send_invoices"]

    def regenerate_invoices(self, request, queryset):
        from api.services.billing import billing_service

        count = 0
        for invoice in queryset:
            cycle = billing_service.create_weekly_billing_cycle(
                invoice.billing_period_start
            )
            if billing_service._generate_client_invoice(invoice.client, cycle):
                count += 1
        self.message_user(request, f"Regenerated {count} invoices")

    regenerate_invoices.short_description = "Regenerate selected invoices"

    def send_invoices(self, request, queryset):
        from api.services.billing import billing_service

        count = 0
        for invoice in queryset:
            if billing_service.send_invoice_email(invoice):
                count += 1
        self.message_user(request, f"Sent {count} invoices")

    send_invoices.short_description = "Send selected invoices"


@admin.register(InvoiceLineItem)
class InvoiceLineItemAdmin(admin.ModelAdmin):
    list_display = ["id", "invoice", "description", "gallons", "line_total"]
    search_fields = ["invoice__id", "description"]
    raw_id_fields = ["invoice", "transaction"]


@admin.register(BillingCycle)
class BillingCycleAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "week_start",
        "week_end",
        "status",
        "invoices_generated",
        "clients_processed",
        "total_amount",
        "completed_at",
    ]
    list_filter = ["status"]
    readonly_fields = ["id", "created_at"]