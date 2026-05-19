"""
REST API views for fuel billing.
"""
from datetime import date, timedelta

from django.http import HttpResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import (
    BillingCycle,
    Client,
    FuelTransaction,
    Invoice,
)
from api.serializers import (
    BillingCycleSerializer,
    ClientSerializer,
    FuelTransactionSerializer,
    InvoiceDetailSerializer,
    InvoiceSerializer,
)
from api.services.billing import billing_service
from api.services.relay_api import relay_api_client
from api.services.transaction_processor import transaction_processor


@api_view(["GET"])
def health_check(request):
    """Health check endpoint."""
    return Response({"status": "ok", "service": "fuel-billing"})


class ClientViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only viewset for clients.
    """

    queryset = Client.objects.filter(is_active=True)
    serializer_class = ClientSerializer

    @action(detail=True, methods=["get"])
    def transactions(self, request, pk=None):
        """Get transactions for a specific client."""
        client = self.get_object()
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")

        transactions = FuelTransaction.objects.filter(client=client)

        if start_date:
            transactions = transactions.filter(transaction_date__gte=start_date)
        if end_date:
            transactions = transactions.filter(transaction_date__lte=end_date)

        serializer = FuelTransactionSerializer(transactions, many=True)
        return Response(serializer.data)


class InvoiceViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only viewset for invoices.
    """

    queryset = Invoice.objects.all()
    serializer_class = InvoiceSerializer

    def get_serializer_class(self):
        if self.action == "retrieve":
            return InvoiceDetailSerializer
        return InvoiceSerializer

    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        """Send invoice to client via email."""
        invoice = self.get_object()
        success = billing_service.send_invoice_email(invoice)
        if success:
            return Response({"status": "sent", "invoice_id": str(invoice.id)})
        return Response(
            {"status": "failed", "invoice_id": str(invoice.id)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class BillingCycleViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only viewset for billing cycles.
    """

    queryset = BillingCycle.objects.all()
    serializer_class = BillingCycleSerializer


class SyncPullView(APIView):
    """
    Trigger manual Relay API pull.
    """

    def post(self, request):
        start_date = request.data.get("start_date")
        end_date = request.data.get("end_date")

        if start_date:
            start_date = date.fromisoformat(start_date)
        if end_date:
            end_date = date.fromisoformat(end_date)

        result = transaction_processor.sync_all_clients(start_date, end_date)
        return Response(result)


class GenerateInvoicesView(APIView):
    """
    Trigger weekly invoice generation.
    """

    def post(self, request):
        cycle = billing_service.create_weekly_billing_cycle()
        result = billing_service.generate_invoices_for_cycle(cycle)
        return Response(result)