"""Tests for prediction markets / Ceres event-contract trading."""

import pytest
import responses

from pyhood import urls
from pyhood.client import PyhoodClient
from pyhood.exceptions import APIError, OrderError
from pyhood.http import Session
from pyhood.models import (
    CeresAccount,
    EventContractOrder,
    EventContractPosition,
    EventContractQuote,
    PredictionMarketNavNode,
)

BASE = "https://api.robinhood.com"
SWAP_ID = "swap-acct-001"
FUTURES_ID = "futures-acct-001"
CONTRACT_ID = "a6cf2bf3-13ca-4c34-b5b6-97341cc6d21b"
ORDER_ID = "6ab607fe-c14b-43df-8603-50f9fccda7b8"


@pytest.fixture
def client():
    session = Session(timeout=5)
    session.set_auth("Bearer", "test-token")
    return PyhoodClient(session=session)


def _accounts_payload():
    return {
        "results": [
            {
                "id": SWAP_ID,
                "accountType": "SWAP",
                "status": "ACTIVE",
                "rhfAccountNumber": "5QU49246",
                "rhsAccountNumber": "104492467",
            },
            {
                "id": FUTURES_ID,
                "accountType": "FUTURES",
                "status": "ACTIVE",
                "rhfAccountNumber": "5QU49246",
                "rhsAccountNumber": "104492467",
            },
            {
                "id": "other-swap",
                "accountType": "SWAP",
                "status": "ACTIVE",
                "rhfAccountNumber": "999999999",
                "rhsAccountNumber": "1",
            },
        ]
    }


class TestCeresAccounts:
    @responses.activate
    def test_list_and_filter(self, client):
        responses.add(responses.GET, urls.CERES_ACCOUNTS, json=_accounts_payload())
        all_accts = client.get_ceres_accounts()
        assert len(all_accts) == 3
        assert all(isinstance(a, CeresAccount) for a in all_accts)

        swaps = client.get_ceres_accounts(account_type="SWAP")
        assert [a.account_id for a in swaps] == [SWAP_ID, "other-swap"]

        filtered = client.get_ceres_accounts(
            account_type="SWAP", rhf_account_number="5QU49246",
        )
        assert len(filtered) == 1
        assert filtered[0].account_id == SWAP_ID

    @responses.activate
    def test_swap_account_id(self, client):
        responses.add(responses.GET, urls.CERES_ACCOUNTS, json=_accounts_payload())
        assert client.get_event_contract_account_id() == SWAP_ID
        assert client.get_event_contract_account_id("5QU49246") == SWAP_ID

    @responses.activate
    def test_no_swap_account(self, client):
        responses.add(
            responses.GET,
            urls.CERES_ACCOUNTS,
            json={"results": [{"id": FUTURES_ID, "accountType": "FUTURES"}]},
        )
        with pytest.raises(APIError, match="SWAP"):
            client.get_event_contract_account_id()


class TestPositionsAndOrders:
    @responses.activate
    def test_positions(self, client):
        responses.add(responses.GET, urls.CERES_ACCOUNTS, json=_accounts_payload())
        responses.add(
            responses.GET,
            urls.ceres_positions_url(SWAP_ID),
            json={
                "results": [{
                    "contractId": CONTRACT_ID,
                    "quantity": "10",
                    "tradePrice": "0.77",
                }],
            },
        )
        pos = client.get_event_contract_positions(rhf_account_number="5QU49246")
        assert len(pos) == 1
        assert isinstance(pos[0], EventContractPosition)
        assert pos[0].contract_id == CONTRACT_ID
        assert pos[0].quantity == 10.0
        assert pos[0].trade_price == 0.77

    @responses.activate
    def test_orders_with_states(self, client):
        responses.add(
            responses.GET,
            urls.ceres_orders_url(SWAP_ID),
            json={
                "results": [{
                    "id": ORDER_ID,
                    "accountId": SWAP_ID,
                    "quantity": "10",
                    "limitPrice": "0.77",
                    "orderState": "FILLED",
                    "derivedState": "FILLED",
                    "timeInForce": "GTD",
                    "refId": "ref-1",
                    "createdAt": "2026-09-25T05:35:12Z",
                    "legs": [{
                        "contractType": "EVENT_CONTRACT",
                        "contractId": CONTRACT_ID,
                        "orderSide": "BUY",
                        "ratioQuantity": 1,
                    }],
                }],
            },
        )
        orders = client.get_event_contract_orders(
            account_id=SWAP_ID,
            order_states=["QUEUED", "FILLED"],
        )
        assert len(orders) == 1
        o = orders[0]
        assert isinstance(o, EventContractOrder)
        assert o.order_id == ORDER_ID
        assert o.contract_id == CONTRACT_ID
        assert o.side == "BUY"
        assert o.quantity == 10.0
        assert o.limit_price == 0.77
        assert o.status == "FILLED"
        assert o.derived_state == "FILLED"

        req = responses.calls[0].request
        assert "contractType=EVENT_CONTRACT" in req.url
        assert "orderState=QUEUED" in req.url
        assert "orderState=FILLED" in req.url

    @responses.activate
    def test_single_order(self, client):
        responses.add(
            responses.GET,
            urls.ceres_order_url(SWAP_ID, ORDER_ID),
            json={
                "id": ORDER_ID,
                "accountId": SWAP_ID,
                "quantity": "10",
                "limitPrice": "0.77",
                "orderState": "FILLED",
                "legs": [{
                    "contractId": CONTRACT_ID,
                    "orderSide": "BUY",
                }],
            },
        )
        order = client.get_event_contract_order(ORDER_ID, account_id=SWAP_ID)
        assert order.order_id == ORDER_ID
        assert order.status == "FILLED"


class TestFeesPlaceCancel:
    @responses.activate
    def test_fees_uses_futures_account(self, client):
        responses.add(responses.GET, urls.CERES_ACCOUNTS, json=_accounts_payload())
        responses.add(
            responses.POST,
            urls.CERES_FEES_FOR_TENTATIVE_ORDER,
            json={"exchangeFee": "0.10", "commission": "0.09"},
        )
        fees = client.get_event_contract_fees(
            contract_id=CONTRACT_ID,
            order_side="BUY",
            limit_price=0.77,
            quantity=10,
            rhf_account_number="5QU49246",
        )
        assert fees["exchangeFee"] == "0.10"
        body = responses.calls[-1].request.body
        assert isinstance(body, (str, bytes))
        text = body.decode() if isinstance(body, bytes) else body
        assert FUTURES_ID in text
        assert '"quantity": "10"' in text
        assert '"limitPrice": "0.77"' in text

    def test_fees_requires_quantity_or_notional(self, client):
        with pytest.raises(OrderError, match="quantity or notional"):
            client.get_event_contract_fees(
                contract_id=CONTRACT_ID,
                order_side="BUY",
                limit_price=0.5,
                account_id=FUTURES_ID,
            )

    def test_place_requires_allow_live(self, client):
        with pytest.raises(OrderError, match="allow_live"):
            client.place_event_contract_order(
                contract_id=CONTRACT_ID,
                order_side="BUY",
                quantity=1,
                limit_price=0.5,
                account_id=SWAP_ID,
            )

    def test_cancel_requires_allow_live(self, client):
        with pytest.raises(OrderError, match="allow_live"):
            client.cancel_event_contract_order(ORDER_ID, account_id=SWAP_ID)

    @responses.activate
    def test_place_order(self, client):
        responses.add(
            responses.POST,
            urls.EVENT_CONTRACT_ORDERS,
            json={
                "id": ORDER_ID,
                "accountId": SWAP_ID,
                "quantity": "10",
                "limitPrice": "0.77",
                "orderState": "UNCONFIRMED",
                "derivedState": "UNCONFIRMED",
                "timeInForce": "GTD",
                "refId": "fixed-ref",
                "legs": [{
                    "contractType": "EVENT_CONTRACT",
                    "contractId": CONTRACT_ID,
                    "orderSide": "BUY",
                    "ratioQuantity": 1,
                }],
            },
        )
        order = client.place_event_contract_order(
            account_id=SWAP_ID,
            contract_id=CONTRACT_ID,
            order_side="buy",
            quantity=10,
            limit_price=0.77,
            ref_id="fixed-ref",
            gtd_expiration_time="2026-09-26T07:00:00Z",
            allow_live=True,
        )
        assert order.order_id == ORDER_ID
        assert order.status == "UNCONFIRMED"
        assert client._session.headers.get("Rh-Contract-Protected") == "true"
        assert client._session.headers.get("X-TimeZone-Id") == "America/Los_Angeles"

        text = responses.calls[0].request.body
        if isinstance(text, bytes):
            text = text.decode()
        assert '"accountId": "swap-acct-001"' in text
        assert CONTRACT_ID in text
        assert '"orderSide": "BUY"' in text
        assert '"gtdExpirationTime": "2026-09-26T07:00:00Z"' in text

    @responses.activate
    def test_cancel_order(self, client):
        responses.add(
            responses.POST,
            urls.event_contract_cancel_url(ORDER_ID),
            json={"ok": True},
        )
        result = client.cancel_event_contract_order(
            ORDER_ID, account_id=SWAP_ID, allow_live=True,
        )
        assert result["ok"] is True
        text = responses.calls[0].request.body
        if isinstance(text, bytes):
            text = text.decode()
        assert '"accountId": "swap-acct-001"' in text


class TestQuotesAndNav:
    @responses.activate
    def test_quotes(self, client):
        responses.add(
            responses.GET,
            urls.EVENT_CONTRACT_QUOTES,
            json={
                "data": [{
                    "status": "OK",
                    "data": {
                        "instrument_id": CONTRACT_ID,
                        "last_trade_price": "0.77",
                        "yes_bid_price": "0.76",
                        "yes_ask_price": "0.78",
                        "no_bid_price": "0.22",
                        "no_ask_price": "0.24",
                        "bid_price": "0.76",
                        "ask_price": "0.78",
                    },
                }],
            },
        )
        quotes = client.get_event_contract_quotes([CONTRACT_ID])
        assert CONTRACT_ID in quotes
        q = quotes[CONTRACT_ID]
        assert isinstance(q, EventContractQuote)
        assert q.yes_ask == 0.78
        assert q.no_bid == 0.22
        assert q.last_trade_price == 0.77

    @responses.activate
    def test_navigation(self, client):
        responses.add(
            responses.GET,
            urls.PREDICTION_MARKETS_NAV,
            json={
                "nodes": [
                    {
                        "id": "n2",
                        "displayTabText": "Crypto",
                        "displayHeaderText": "Crypto markets",
                        "displayLayoutType": "GRID",
                        "rank": 2,
                        "imageUrl": "https://example/c.png",
                    },
                    {
                        "id": "n1",
                        "displayTabText": "Climate",
                        "rank": 1,
                    },
                    {"id": "n3", "displayTabText": "  "},
                ],
            },
        )
        nodes = client.get_prediction_markets_navigation()
        assert [n.label for n in nodes] == ["Climate", "Crypto"]
        assert isinstance(nodes[0], PredictionMarketNavNode)
        assert nodes[1].header == "Crypto markets"

    @responses.activate
    def test_events(self, client):
        responses.add(
            responses.GET,
            urls.PREDICTION_MARKETS_EVENTS,
            json={
                "results": [
                    {"id": "e1", "name": "Oil Price"},
                    {"id": "e2", "name": "Other"},
                    {"name": "no-id"},
                ],
            },
        )
        events = client.get_prediction_markets_events("Climate", limit=1)
        assert len(events) == 1
        assert events[0]["id"] == "e1"
        assert "categories=Climate" in responses.calls[0].request.url

    def test_events_require_category(self, client):
        with pytest.raises(OrderError, match="category"):
            client.get_prediction_markets_events("  ")

    @responses.activate
    def test_layout_uses_camel_case_node_id(self, client):
        responses.add(
            responses.GET,
            urls.PREDICTION_MARKETS_LAYOUT,
            json={
                "results": {
                    "nodeId": "n2",
                    "components": [{"eventComponent": {"eventId": "e1"}}],
                },
            },
        )
        layout = client.get_prediction_markets_layout("n2")
        assert layout["results"]["nodeId"] == "n2"
        assert "nodeId=n2" in responses.calls[0].request.url
        assert "node_id=" not in responses.calls[0].request.url

    def test_layout_requires_node_id(self, client):
        with pytest.raises(OrderError, match="node_id"):
            client.get_prediction_markets_layout("  ")

    @responses.activate
    def test_event_by_id(self, client):
        responses.add(
            responses.GET,
            urls.prediction_markets_event_url("e1"),
            json={"id": "e1", "name": "Oil Price"},
        )
        event = client.get_prediction_markets_event("e1")
        assert event["id"] == "e1"
        assert event["name"] == "Oil Price"

    @responses.activate
    def test_contract_by_id(self, client):
        responses.add(
            responses.GET,
            urls.prediction_markets_contract_url(CONTRACT_ID),
            json={"id": CONTRACT_ID, "shortName": "Above $89.99"},
        )
        contract = client.get_prediction_markets_contract(CONTRACT_ID)
        assert contract["id"] == CONTRACT_ID

    @responses.activate
    def test_account_id_alias(self, client):
        responses.add(responses.GET, urls.CERES_ACCOUNTS, json=_accounts_payload())
        assert client.get_event_contracts_account_id() == SWAP_ID


class TestUrlHelpers:
    def test_url_constants(self):
        assert urls.CERES_ACCOUNTS == urls.FUTURES_ACCOUNTS
        assert urls.EVENT_CONTRACT_ORDERS.endswith("/ceres/v1/event_contract_orders")
        assert urls.event_contract_cancel_url("abc").endswith(
            "/ceres/v1/event_contract_orders/abc/cancel"
        )
        assert urls.EVENT_CONTRACT_QUOTES.endswith(
            "/marketdata/event/contract/quotes/v1/"
        )
        assert urls.PREDICTION_MARKETS_NAV.endswith(
            "/prediction-markets/v1/navigation_nodes"
        )
        assert urls.PREDICTION_MARKETS_LAYOUT.endswith(
            "/prediction-markets/v1/layout"
        )
        assert urls.prediction_markets_event_url("e1").endswith(
            "/prediction-markets/v1/events/e1"
        )
        assert urls.prediction_markets_contract_url("c1").endswith(
            "/prediction-markets/v1/events/contracts/c1"
        )
