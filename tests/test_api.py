import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from app.horizon_client import HORIZON_TESTNET_URL
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    async def fake_sleep(_seconds: float):
        return None

    monkeypatch.setattr("app.horizon_client.asyncio.sleep", fake_sleep)


@respx.mock
def test_score_returns_503_when_horizon_keeps_rate_limiting():
    address = "GRATELIMITEDAPI"
    respx.get(f"{HORIZON_TESTNET_URL}/accounts/{address}/operations").mock(
        return_value=Response(429)
    )
    response = client.post("/score", json={"address": address})
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "30"
    assert "rate limiting" in response.json()["detail"]
