# Prediction Markets (Event Contracts)

Pyhood provides access to Robinhood Derivatives (Ceres) **event contracts** —
the Prediction Markets product — including SWAP account discovery, positions,
orders, fee quotes, place/cancel, and public navigation / marketdata quotes.

Endpoints were reverse-engineered from a live Robinhood app capture (2026-09-25
Oil WTI place of 10 @ 0.77). Trading uses Ceres REST under `/ceres/v1/`, not
the equity `/orders/` or futures arsenal place paths.

## Quick Start

```python
from pyhood import login, PyhoodClient

login("user@example.com", "password")
client = PyhoodClient()

# SWAP account = event contracts; FUTURES sibling used for fee quotes
swap_id = client.get_event_contract_account_id(rhf_account_number="5QU49246")
positions = client.get_event_contract_positions(account_id=swap_id)

# Public taxonomy + quotes (no place)
tabs = client.get_prediction_markets_navigation()
quotes = client.get_event_contract_quotes(["a6cf2bf3-13ca-4c34-b5b6-97341cc6d21b"])

# Live place requires allow_live=True (safety gate)
# order = client.place_event_contract_order(
#     account_id=swap_id,
#     contract_id="a6cf2bf3-13ca-4c34-b5b6-97341cc6d21b",
#     order_side="BUY",
#     quantity=10,
#     limit_price=0.77,
#     allow_live=True,
# )
```

## Account types

The same `GET /ceres/v1/accounts/` list used for futures returns multiple
`accountType` values that share an `rhfAccountNumber`:

| `accountType` | Role |
|---------------|------|
| **SWAP** | Place, cancel, positions, order poll for event contracts |
| **FUTURES** | Fee tentative quotes (as seen in the live capture) |
| CFTC_30_7 | Present on some accounts; not used for this flow |

## Methods

### `get_ceres_accounts(account_type=None, rhf_account_number=None)`

List Ceres accounts, optionally filtered.

**Returns:** `list[CeresAccount]`

### `get_event_contract_account_id(rhf_account_number=None, require_active=True)`

Auto-discover the first ACTIVE SWAP account.

Also available as `get_event_contracts_account_id` (alias).

**Raises:** `APIError` if none found.

### `get_event_contract_positions(account_id=None, rhf_account_number=None)`

Open positions with `contractType=EVENT_CONTRACT`.

**Returns:** `list[EventContractPosition]`

### `get_event_contract_orders(account_id=None, …, order_states=None)`

List orders. Pass `order_states` (e.g. `['QUEUED', 'CONFIRMED']`) to repeat
`orderState` query params as the app does.

### `get_event_contract_order(order_id, account_id=None, …)`

Single-order GET for fill polling (`UNCONFIRMED` → `FILLED`).

### `get_event_contract_fees(…)`

`POST /ceres/v1/accounts/fees_for_tentative_order`. Requires `quantity` **or**
`notional_amount`. By default prefers the FUTURES account for the fee quote
when auto-discovering (`use_futures_account_for_fees=True`).

### `place_event_contract_order(…, allow_live=False)`

`POST /ceres/v1/event_contract_orders`. **Refuses unless `allow_live=True`.**

Default time-in-force is `GTD` with expiration next calendar day `07:00Z`
(midnight PT), matching the live app capture.

### `cancel_event_contract_order(order_id, …, allow_live=False)`

`POST …/event_contract_orders/{id}/cancel` with body `{accountId}`.
**Refuses unless `allow_live=True`.**

### `get_event_contract_quotes(contract_ids)`

`GET /marketdata/event/contract/quotes/v1/?ids=…` — batches of 12.

### `get_prediction_markets_navigation()`

Public `GET /prediction-markets/v1/navigation_nodes` category tabs.

### `get_prediction_markets_events(category, limit=100)`

Public `GET /prediction-markets/v1/events/?categories={label}`. Some sports /
combo tabs return 400 from this endpoint.

### `get_prediction_markets_layout(node_id)`

Public `GET /prediction-markets/v1/layout?nodeId={id}` — **camelCase**
`nodeId` (not `node_id`). Returns layout components for a navigation tab;
each `eventComponent` typically carries an `eventId`.

### `get_prediction_markets_event(event_id)`

Public `GET /prediction-markets/v1/events/{eventId}`.

### `get_prediction_markets_contract(contract_id)`

Public `GET /prediction-markets/v1/events/contracts/{contractId}`.

## Place body (example)

```json
{
  "accountId": "<SWAP uuid>",
  "legs": [{
    "contractType": "EVENT_CONTRACT",
    "contractId": "a6cf2bf3-13ca-4c34-b5b6-97341cc6d21b",
    "ratioQuantity": 1,
    "orderSide": "BUY"
  }],
  "quantity": "10",
  "limitPrice": "0.77",
  "refId": "<uuid>",
  "timeInForce": "GTD",
  "gtdExpirationTime": "2026-09-26T07:00:00Z"
}
```

## API Endpoints

| Method | Path | Role |
|--------|------|------|
| GET | `/ceres/v1/accounts/` | List Ceres accounts |
| GET | `/ceres/v1/accounts/{id}/positions?contractType=EVENT_CONTRACT` | Positions |
| GET | `/ceres/v1/accounts/{id}/orders?…` | Orders |
| GET | `/ceres/v1/accounts/{id}/orders/{orderId}` | Order detail |
| POST | `/ceres/v1/accounts/fees_for_tentative_order` | Fee quote |
| POST | `/ceres/v1/event_contract_orders` | Place |
| POST | `/ceres/v1/event_contract_orders/{id}/cancel` | Cancel |
| GET | `/marketdata/event/contract/quotes/v1/` | Quotes |
| GET | `/prediction-markets/v1/navigation_nodes` | Nav taxonomy |
| GET | `/prediction-markets/v1/layout?nodeId=` | Category layout |
| GET | `/prediction-markets/v1/events/` | Events by category |
| GET | `/prediction-markets/v1/events/{id}` | Event detail |
| GET | `/prediction-markets/v1/events/contracts/{id}` | Contract detail |

## Notes

- Ceres requests set `Rh-Contract-Protected: true` and `X-TimeZone-Id`
  automatically (same pattern as futures).
- The URL `contract=` query param on the Robinhood web event page is **not**
  always the leg you place — use the contract id from the order ticket / chain.
- Place and cancel are gated behind `allow_live=True` because the path was
  reverse-engineered; remove the gate at your own risk for trusted automation.
