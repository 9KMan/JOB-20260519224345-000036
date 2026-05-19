"""
Transaction processor service.
Normalizes, deduplicates, and validates fuel transactions from Relay API.
"""
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Generator

from django.db import IntegrityError, transaction

from api.models import Client, FuelTransaction
from api.services.relay_api import relay_api_client

logger = logging.getLogger(__name__)


class TransactionProcessor:
    """
    Processes fuel transactions from Relay Payments API.
    Handles deduplication, validation, and storage.
    """

    def __init__(self):
        self.api_client = relay_api_client
        self.processed_count = 0
        self.skipped_count = 0
        self.error_count = 0

    def sync_all_clients(
        self,
        start_date=None,
        end_date=None,
        batch_size: int = 20,
    ) -> dict:
        """
        Sync transactions for all active clients.
        Processes clients in batches to avoid DB lock contention.
        Returns summary statistics.
        """
        clients = Client.objects.filter(is_active=True)
        total_clients = clients.count()

        for idx, client in enumerate(clients.iterator(chunk_size=batch_size)):
            try:
                self.sync_client(client, start_date, end_date)
                logger.info(
                    f"[{idx + 1}/{total_clients}] Synced transactions for {client.name}"
                )
            except Exception as e:
                logger.error(f"Failed to sync client {client.name}: {e}")
                self.error_count += 1

        return {
            "total_clients": total_clients,
            "processed": self.processed_count,
            "skipped_duplicates": self.skipped_count,
            "errors": self.error_count,
        }

    def sync_client(
        self,
        client: Client,
        start_date=None,
        end_date=None,
    ) -> int:
        """
        Sync transactions for a single client.
        Returns count of new transactions inserted.
        """
        new_count = 0
        for txn_data in self.api_client.get_transactions(
            client.relay_client_id,
            start_date,
            end_date,
        ):
            if self._process_transaction(client, txn_data):
                new_count += 1

        return new_count

    def _process_transaction(self, client: Client, txn_data: dict) -> bool:
        """
        Process a single transaction record.
        Returns True if new transaction was created, False if skipped.
        """
        relay_txn_id = txn_data.get("id") or txn_data.get("transaction_id")
        if not relay_txn_id:
            logger.warning(f"Transaction missing ID: {txn_data}")
            self.skipped_count += 1
            return False

        if FuelTransaction.objects.filter(
            relay_transaction_id=relay_txn_id,
            client=client,
        ).exists():
            self.skipped_count += 1
            return False

        try:
            transaction_date = self._parse_date(
                txn_data.get("date") or txn_data.get("transaction_date")
            )
            fuel_type = self._normalize_fuel_type(
                txn_data.get("fuel_type") or txn_data.get("type", "diesel")
            )
            gallons = Decimal(str(txn_data.get("gallons", "0")))
            price_per_gallon = Decimal(str(txn_data.get("price_per_gallon", "0")))
            total_amount = Decimal(str(txn_data.get("total_amount", "0")))

            if total_amount == Decimal("0") and gallons and price_per_gallon:
                total_amount = gallons * price_per_gallon

            FuelTransaction.objects.create(
                client=client,
                relay_transaction_id=relay_txn_id,
                transaction_date=transaction_date,
                gallons=gallons,
                price_per_gallon=price_per_gallon,
                total_amount=total_amount,
                fuel_type=fuel_type,
                raw_json=txn_data,
            )
            self.processed_count += 1
            return True

        except IntegrityError:
            self.skipped_count += 1
            return False
        except Exception as e:
            logger.error(f"Error processing transaction {relay_txn_id}: {e}")
            self.error_count += 1
            return False

    def _parse_date(self, date_value) -> date:
        """Parse date from various formats."""
        if isinstance(date_value, date):
            return date_value
        if isinstance(date_value, datetime):
            return date_value.date()
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(str(date_value), fmt).date()
            except ValueError:
                continue
        return date.today()

    def _normalize_fuel_type(self, fuel_type: str) -> str:
        """Normalize fuel type to known categories."""
        fuel_map = {
            "diesel": "diesel",
            "gasoline": "regular",
            "regular": "regular",
            "midgrade": "midgrade",
            "premium": "premium",
            "super": "premium",
        }
        return fuel_map.get(fuel_type.lower(), "diesel")


transaction_processor = TransactionProcessor()