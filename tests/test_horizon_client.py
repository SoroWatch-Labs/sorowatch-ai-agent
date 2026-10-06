import pytest
import respx
from httpx import Response

from app.horizon_client import (
    HORIZON_TESTNET_URL,
    HorizonClient,
    HorizonRateLimitError,
)

ADDRESS = "GRATELIMITED"
URL = f"{HORIZON_TESTNET_URL}/accounts/{ADDRESS}/operations"
OK_BODY = {"_embedded": {"records": [{"created_at": "2026-01-01T00:00:00Z"}]}}


@pytest.fixture
def sleeps(monkeypatch):
    """Record sleep calls instead of really waiting."""
    calls: list[float] = []

    async def fake_sleep(seconds: float):
        calls.append(seconds)

    monkeypatch.setattr("app.horizon_client.asyncio.sleep", fake_sleep)
    return calls


@pytest.mark.asyncio
@respx.mock
async def test_retries_after_429_then_succeeds(sleeps):
    route = respx.get(URL).mock(
        side_effect=[Response(429), Response(429), Response(200, json=OK_BODY)]
    )
    ops = await HorizonClient().get_recent_operations(ADDRESS)
    assert len(ops) == 1
    assert route.call_count == 3
    assert sleeps == [1.0, 2.0]  # exponential backoff


@pytest.mark.asyncio
@respx.mock
async def test_honours_retry_after_header(sleeps):
    respx.get(URL).mock(
        side_effect=[
            Response(429, headers={"Retry-After": "7"}),
            Response(200, json=OK_BODY),
        ]
    )
    await HorizonClient().get_recent_operations(ADDRESS)
    assert sleeps == [7.0]


@pytest.mark.asyncio
@respx.mock
async def test_retry_after_is_capped(sleeps):
    respx.get(URL).mock(
        side_effect=[
            Response(429, headers={"Retry-After": "9999"}),
            Response(200, json=OK_BODY),
        ]
    )
    await HorizonClient(max_backoff=30.0).get_recent_operations(ADDRESS)
    assert sleeps == [30.0]


@pytest.mark.asyncio
@respx.mock
async def test_invalid_retry_after_falls_back_to_backoff(sleeps):
    respx.get(URL).mock(
        side_effect=[
            Response(429, headers={"Retry-After": "soon"}),
            Response(200, json=OK_BODY),
        ]
    )
    await HorizonClient().get_recent_operations(ADDRESS)
    assert sleeps == [1.0]


@pytest.mark.asyncio
@respx.mock
async def test_raises_after_max_retries(sleeps):
    route = respx.get(URL).mock(return_value=Response(429))
    with pytest.raises(HorizonRateLimitError):
        await HorizonClient(max_retries=2).get_recent_operations(ADDRESS)
    assert route.call_count == 3  # first try + 2 retries
    assert len(sleeps) == 2


@pytest.mark.asyncio
@respx.mock
async def test_404_still_returns_empty_without_retrying(sleeps):
    route = respx.get(URL).mock(return_value=Response(404))
    assert await HorizonClient().get_recent_operations(ADDRESS) == []
    assert route.call_count == 1
    assert sleeps == []


@pytest.mark.asyncio
@respx.mock
async def test_other_errors_are_not_retried(sleeps):
    route = respx.get(URL).mock(return_value=Response(500))
    with pytest.raises(Exception):
        await HorizonClient().get_recent_operations(ADDRESS)
    assert route.call_count == 1
    assert sleeps == []
