"""
API URL configuration.
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from api.views import (
    BillingCycleViewSet,
    ClientViewSet,
    GenerateInvoicesView,
    InvoiceViewSet,
    SyncPullView,
    health_check,
)

router = DefaultRouter()
router.register(r"clients", ClientViewSet)
router.register(r"invoices", InvoiceViewSet)
router.register(r"billingcycles", BillingCycleViewSet)

urlpatterns = [
    path("", include(router.urls)),
    path("health/", health_check, name="health_check"),
    path("sync/pull/", SyncPullView.as_view(), name="sync_pull"),
    path("invoices/generate/", GenerateInvoicesView.as_view(), name="generate_invoices"),
]