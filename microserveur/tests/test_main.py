from pathlib import Path
import sys
from typing import Optional

import pytest

pytest.importorskip("fastapi")
TestClient = pytest.importorskip("fastapi.testclient").TestClient  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main  # noqa: E402  pylint: disable=wrong-import-position


class DummyClient:
    def __init__(self) -> None:
        self.last_payload: Optional[dict] = None

    def create_order(self, **payload):  # type: ignore[no-untyped-def]
        self.last_payload = payload
        return {"orderId": 123}

    def close_connection(self) -> None:
        pass


def test_place_trailing_order_forwards_payload(monkeypatch):
    dummy_client = DummyClient()

    def fake_create_client(use_testnet: bool) -> DummyClient:
        assert use_testnet is True
        return dummy_client

    monkeypatch.setattr(main, "create_client", fake_create_client)

    client = TestClient(main.app)
    response = client.post(
        "/orders",
        json={"command": "achetez 0,25 btcusdt trailing 0,5 activation 20000", "testnet": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert dummy_client.last_payload == {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "type": "TRAILING_STOP_MARKET",
        "quantity": "0.25",
        "callbackRate": "0.5",
        "activationPrice": "20000",
    }
    assert body["data"]["parsed_order"]["callback_rate"] == "0.5"
    assert body["data"]["parsed_order"]["activation_price"] == "20000"
