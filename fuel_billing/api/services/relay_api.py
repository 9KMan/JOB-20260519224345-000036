"""
Relay Payments API client wrapper.
Handles authentication, pagination, rate limiting, and retry logic.
"""
import logging
import time
from datetime import date, datetime, timedelta
from typing import Any, Generator

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class RelayAPIClient:
    """
    Client for Relay Payments API v1.
    Handles paginated transaction and client data retrieval.
    """

    def __init__(self):
        self.base_url = settings.RELAY_API_BASE_URL
        self.api_key = settings.RELAY_API_KEY
        self.timeout = settings.RELAY_API_TIMEOUT
        self.retry_limit = settings.RELAY_API_RETRY_LIMIT
        self.session = self._build_session()

    def _build_session(self) -> requests.Session:
        """Build requests session with retry logic."""
        session = requests.Session()
        retry_strategy = Retry(
            total=self.retry_limit,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "FuelBilling/1.0",
        }

    def _get(self, endpoint: str, params: dict | None = None) -> dict:
        """
        Make GET request with retry and rate limit handling.
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        for attempt in range(self.retry_limit + 1):
            try:
                response = self.session.get(
                    url,
                    headers=self._headers(),
                    params=params,
                    timeout=self.timeout,
                )
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    logger.warning(
                        f"Rate limited by Relay API. Waiting {retry_after}s before retry."
                    )
                    time.sleep(retry_after)
                    continue
                response.raise_for_status()
                return response.json()
            except requests.RequestException as e:
                if attempt == self.retry_limit:
                    logger.error(f"Relay API request failed after {self.retry_limit} retries: {e}")
                    raise
                wait_time = 2 ** attempt * 10
                logger.warning(f"Relay API error, retrying in {wait_time}s: {e}")
                time.sleep(wait_time)
        return {}

    def get_clients(self) -> Generator[dict, None, None]:
        """
        Fetch all clients from Relay Payments API with pagination.
        Yields individual client records.
        """
        page = 1
        per_page = 100
        while True:
            data = self._get("clients", params={"page": page, "per_page": per_page})
            clients = data.get("data", [])
            if not clients:
                break
            yield from clients
            if page >= data.get("meta", {}).get("total_pages", 1):
                break
            page += 1

    def get_transactions(
        self,
        client_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> Generator[dict, None, None]:
        """
        Fetch transactions for a specific client with pagination.
        Default: last 7 days of transactions.
        """
        if end_date is None:
            end_date = date.today()
        if start_date is None:
            start_date = end_date - timedelta(days=7)

        page = 1
        per_page = 100
        while True:
            params = {
                "client_id": client_id,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "page": page,
                "per_page": per_page,
            }
            data = self._get("transactions", params=params)
            transactions = data.get("data", [])
            if not transactions:
                break
            yield from transactions
            if page >= data.get("meta", {}).get("total_pages", 1):
                break
            page += 1

    def get_transaction(self, transaction_id: str) -> dict | None:
        """Fetch a single transaction by ID."""
        data = self._get(f"transactions/{transaction_id}")
        return data.get("data")


relay_api_client = RelayAPIClient()