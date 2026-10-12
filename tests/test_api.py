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


@respx.mock
def test_score_response_includes_breakdown_that_adds_up():
    address = "GBREAKDOWNAPI"
    respx.get(f"{HORIZON_TESTNET_URL}/accounts/{address}/operations").mock(
        return_value=Response(
            200,
            json={
                "_embedded": {
                    "records": [
                        {"created_at": "2026-01-01T00:00:00Z", "to": "GX", "amount": "10"},
                        {"created_at": "2026-01-01T00:00:05Z", "to": "GX", "amount": "10"},
                        {"created_at": "2026-01-01T00:00:10Z", "to": "GX", "amount": "9999"},
                    ]
                }
            },
        )
    )
    body = client.post("/score", json={"address": address}).json()
    assert set(body["breakdown"]) == {
        "tx_velocity",
        "counterparty_diversity",
        "volume_anomaly",
        "account_age",
        "round_amounts",
    }
    assert body["score"] == min(100, sum(body["breakdown"].values()))
    assert all(isinstance(v, int) for v in body["breakdown"].values())


@respx.mock
def test_score_breakdown_is_all_zero_for_unknown_account():
    address = "GNOHISTORYAPI"
    respx.get(f"{HORIZON_TESTNET_URL}/accounts/{address}/operations").mock(
        return_value=Response(404)
    )
    body = client.post("/score", json={"address": address}).json()
    assert body["score"] == 0
    assert set(body["breakdown"].values()) == {0}
