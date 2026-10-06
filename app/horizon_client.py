"""
Thin client for Stellar Horizon (used to gather account activity for
scoring). Uses the public Horizon API rather than Soroban RPC directly,
since Horizon exposes payment/operation history in a form that's easy to
score, whereas Soroban RPC is oriented around contract events.
"""
import asyncio
import logging

import httpx

HORIZON_TESTNET_URL = "https://horizon-testnet.stellar.org"

logger = logging.getLogger(__name__)


class HorizonRateLimitError(Exception):
    """Raised when Horizon keeps answering 429 after all retries."""


class HorizonClient:
    def __init__(
        self,
        base_url: str = HORIZON_TESTNET_URL,
        timeout: float = 10.0,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        max_backoff: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.max_backoff = max_backoff

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        """
        How long to wait before retrying a 429. Honours a numeric
        Retry-After header when Horizon sends one, otherwise uses
        exponential backoff (1s, 2s, 4s, ...). Always capped.
        """
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return min(max(float(retry_after), 0.0), self.max_backoff)
            except ValueError:
                pass
        return min(self.backoff_base * (2**attempt), self.max_backoff)

    async def get_recent_operations(self, address: str, limit: int = 50) -> list[dict]:
        """
        Fetch the most recent operations for an address. Returns an empty
        list if the account doesn't exist yet (common for freshly-created
        testnet addresses) rather than raising, since "no history" is a
        valid input to the risk scorer.

        If Horizon rate-limits us (HTTP 429) the request is retried with
        backoff up to max_retries times, then HorizonRateLimitError is
        raised so callers can tell "rate limited" apart from "no history".
        """
        url = f"{self.base_url}/accounts/{address}/operations"
        params = {"order": "desc", "limit": limit}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(self.max_retries + 1):
                response = await client.get(url, params=params)
                if response.status_code == 404:
                    return []
                if response.status_code == 429:
                    if attempt == self.max_retries:
                        raise HorizonRateLimitError(
                            f"Horizon rate limit hit {attempt + 1} times for {address}"
                        )
                    delay = self._retry_delay(response, attempt)
                    logger.warning(
                        "Horizon returned 429; retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        self.max_retries,
                    )
                    await asyncio.sleep(delay)
                    continue
                response.raise_for_status()
                data = response.json()
                return data.get("_embedded", {}).get("records", [])
        return []  # pragma: no cover - loop always returns or raises
