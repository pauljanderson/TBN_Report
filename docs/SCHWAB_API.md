# Schwab Trader API (Individual)

What Schwab's API offers, how auth works, and what TBN uses today. Schwab's own pages, saved
2026-11-14, are in `reference/schwab_api/`. They are kept out of `docs/` because the publish step
pushes everything in `docs/` to the public Pages site.

| File | Contents |
|---|---|
| `Schwab_TraderAPI_OAuth_and_OrderSamples.pdf` | OAuth 2 three-legged flow, token lifetimes, order-throttle limits, option symbology, sample order JSON (market, limit, spreads, OTO, OCO, OTO+OCO, trailing stop) |
| `Schwab_TraderAPI_AccountsAndTrading_Endpoints.pdf` | Swagger reference for `https://api.schwabapi.com/trader/v1`: accounts, orders, transactions, user preference, plus schemas |
| `Schwab_TraderAPI_MarketData_Endpoints.pdf` | Swagger reference for `https://api.schwabapi.com/marketdata/v1`: quotes, option chains, price history, movers, market hours, instruments |

## TBN tooling (first pass, read-only)

`tools/schwab_api.py` is a client library and CLI, run through `run_schwab.bat`. It only sends GET
requests, plus the OAuth token POST. It **cannot place, replace, or cancel orders**, which matches
TBN's no-auto-trading rule. `tools/test_schwab_api.py::test_read_only` fails if anyone adds an order
mutation.

```bat
run_schwab.bat login            rem one-time browser consent; repeat every 7 days
run_schwab.bat status           rem token time left, no API call
run_schwab.bat accounts         rem per-account net liq / cash / buying power + every open position
run_schwab.bat accounts --csv   rem also drive\schwab\positions_<ts>.csv and raw accounts_<ts>.json
run_schwab.bat quote AAPL,MSFT
python tools/test_schwab_api.py rem offline tests (fake HTTP)
```

The console output masks account numbers to the last 3 digits. The raw JSON in `drive/schwab/`,
which is gitignored, keeps the full numbers.

Library use:

```python
from schwab_api import SchwabClient, load_config
c = SchwabClient(load_config())
raw = c.accounts(positions=True)                      # list of {"securitiesAccount": {...}}
h = c.account_numbers()[0]["hashValue"]               # hashed id needed by per-account calls
c.orders(h, start, end, status="WORKING"); c.transactions(h, start, end, types="TRADE")
c.quotes(["AAPL", "MSFT"]); c.price_history("AAPL", periodType="year", frequencyType="daily")
```

### Setup

1. On developer.schwab.com, create an App with these settings, then wait for its status to reach
   *Ready For Use*:
   - **Products:** both *Accounts and Trading Production* and *Market Data Production*.
   - **Callback URL:** `https://127.0.0.1`.
   - **Order Limit:** `0`. Schwab then blocks order requests from this App, which backs up the
     client's read-only design. Raising it later goes through Schwab (TraderAPI@schwab.com).
2. Copy `secrets/schwab.env.example` to `secrets/schwab.env`, then fill in `SCHWAB_APP_KEY` and
   `SCHWAB_APP_SECRET`. The callback in this file must match the App's callback exactly.
3. Run `run_schwab.bat login`, log in, and tick the accounts to share. The browser then lands on a
   page that cannot load. Copy its full address-bar URL (Ctrl+L, Ctrl+C); the tool watches the
   clipboard and exchanges the code immediately, because Schwab codes expire within ~30 s. If there
   is no clipboard, `login --paste` takes it typed, and you must be fast. Tokens are saved to
   `secrets/schwab_tokens.json`.

## Auth (OAuth 2, authorization_code)

| Step | Call |
|---|---|
| 1. Consent | Browser: `GET https://api.schwabapi.com/v1/oauth/authorize?client_id={APP_KEY}&redirect_uri={CALLBACK}`. Redirects to `{CALLBACK}/?code=...&session=...` |
| 2. Tokens | `POST https://api.schwabapi.com/v1/oauth/token`, header `Authorization: Basic base64(key:secret)`, form `grant_type=authorization_code&code=...&redirect_uri=...`. The code must be **URL-decoded** (it ends in `@`, not `%40`) |
| 3. Calls | `Authorization: Bearer {access_token}` |
| 4. Refresh | Same token URL, form `grant_type=refresh_token&refresh_token=...` |

- The **access token lasts 30 minutes.** The client refreshes it automatically 2 minutes before expiry, and once more on any 401.
- The **refresh token lasts 7 days and cannot be extended.** After 7 days, or after a password reset, step 1 must be repeated. Nothing can automate this, because a human must log in. `status` shows the time left, and every call warns when less than 24 h remain.
- Callback URLs must be HTTPS. Several can be registered, comma-separated, up to 255 characters in total.
- Each App subscribes to one API product. A sandbox is "coming later", so only production exists.

## Trader API: `https://api.schwabapi.com/trader/v1`

Account numbers in plain text are **not** accepted in URLs. Call `/accounts/accountNumbers` first and
use each account's `hashValue` as `{accountNumber}` in every other call.

| Method | Path | Purpose | Key params | In client |
|---|---|---|---|---|
| GET | `/accounts/accountNumbers` | plain number to hash pairs | none | `account_numbers()` |
| GET | `/accounts` | balances for all linked accounts | `fields=positions` adds positions | `accounts()` |
| GET | `/accounts/{hash}` | one account | `fields=positions` | `account()` |
| GET | `/accounts/{hash}/orders` | orders for one account | `fromEnteredTime`, `toEnteredTime` (required, ISO `yyyy-MM-dd'T'HH:mm:ss.SSSZ`, 1-year max range), `status`, `maxResults` (default 3000) | `orders(hash, ...)` |
| GET | `/orders` | orders for all accounts | same, but `from` must be within the last 60 days | `orders(None, ...)` |
| GET | `/accounts/{hash}/orders/{orderId}` | one order | none | not built |
| POST | `/accounts/{hash}/orders` | **place order** | Order JSON body | **not built (read-only)** |
| PUT | `/accounts/{hash}/orders/{orderId}` | **replace order** | Order JSON body | **not built** |
| DELETE | `/accounts/{hash}/orders/{orderId}` | **cancel order** | none | **not built** |
| POST | `/accounts/{hash}/previewOrder` | dry-run an order: commission, buying-power effect, validation warnings and rejects | Order JSON | not built (safe candidate) |
| GET | `/accounts/{hash}/transactions` | activity history | `startDate`, `endDate` (required, 1-year max, 3000 rows max), `types` (required: `TRADE`, `DIVIDEND_OR_INTEREST`, `ACH_RECEIPT`, `JOURNAL`, ...), `symbol` | `transactions()` |
| GET | `/accounts/{hash}/transactions/{id}` | one transaction | none | not built |
| GET | `/userPreference` | account nicknames, streamer socket info, market-data permissions | none | `user_preference()` |

The order statuses are `AWAITING_PARENT_ORDER`, `AWAITING_CONDITION`, `AWAITING_STOP_CONDITION`,
`AWAITING_MANUAL_REVIEW`, `ACCEPTED`, `AWAITING_UR_OUT`, `PENDING_ACTIVATION`, `QUEUED`, `WORKING`,
`REJECTED`, `PENDING_CANCEL`, `CANCELED`, `PENDING_REPLACE`, `REPLACED`, `FILLED`, `EXPIRED`, `NEW`,
`AWAITING_RELEASE_TIME`, `PENDING_ACKNOWLEDGEMENT`, `PENDING_RECALL` and `UNKNOWN`.

### Account payload, the fields TBN uses

`securitiesAccount`: `type` (`MARGIN` / `CASH`), `accountNumber`, `isDayTrader`, `roundTrips`,
`positions[]`, `initialBalances`, `currentBalances`, `projectedBalances`.

- **Position:** `instrument{symbol, assetType, cusip, description}`, `longQuantity`, `shortQuantity`, `averagePrice`, `marketValue`, `longOpenProfitLoss`, `shortOpenProfitLoss`, `currentDayProfitLoss`, `currentDayProfitLossPercentage`, `settledLongQuantity`, `maintenanceRequirement`, `taxLotAverageLongPrice`.
- **Margin balances:** `liquidationValue`, `equity`, `cashBalance`, `buyingPower`, `availableFunds`, `dayTradingBuyingPower`, `longMarketValue`, `maintenanceRequirement`, `sma`, `isInCall`.
- **Cash balances:** `cashAvailableForTrading`, `cashAvailableForWithdrawal`, `unsettledCash`, `accountValue` (in initialBalances), `longStockValue`.

Margin and cash accounts name some balance fields differently, and the PDF schemas are incomplete.
`summarize_accounts()` therefore looks up each value in `currentBalances` first, then in
`initialBalances`, trying alternative field names in order:
- net liq: `liquidationValue`, then `accountValue`, then `equity`
- cash: `cashBalance`, then `totalCash`, then `cashAvailableForTrading`

**Verify these choices against the first real response.**

## Market Data API: `https://api.schwabapi.com/marketdata/v1`

| Path | Purpose | Key params |
|---|---|---|
| `/quotes` | quotes for many symbols, including options, futures (`/ESH23`), indices (`$SPX`) and FX | `symbols`, `fields` (`quote`, `fundamental`, `extended`, `reference`, `regular`), `indicative` |
| `/{symbol}/quotes` | one symbol | `fields` |
| `/chains` | option chain | symbol, contract type, strikes, range, dates |
| `/expirationchain` | option expirations only | `symbol` |
| `/pricehistory` | OHLCV candles | `symbol`, `periodType` (`day`/`month`/`year`/`ytd`), `period`, `frequencyType` (`minute`/`daily`/`weekly`/`monthly`), `frequency` (1/5/10/15/30 for minute), `startDate`/`endDate` (epoch ms), `needExtendedHoursData`, `needPreviousClose` |
| `/movers/{index}` | top 10 movers | index `$DJI`, `$COMPX`, `$SPX`, `NYSE`, `NASDAQ`, ...; `sort` (`VOLUME`, `TRADES`, `PERCENT_CHANGE_UP`/`DOWN`); `frequency` |
| `/markets`, `/markets/{id}` | market hours | `markets` (`equity`, `option`, `bond`, `future`, `forex`), `date` |
| `/instruments` | symbol search and fundamentals | `symbol`, `projection` (`symbol-search`, `symbol-regex`, `desc-search`, `desc-regex`, `search`, `fundamental`) |
| `/instruments/{cusip}` | lookup by CUSIP | none |

## Orders (reference only, not implemented)

- Order entry supports `EQUITY` and `OPTION` only.
- Order POST/PUT/DELETE calls are throttled per account per minute. The limit, from 0 to 120, is set per App at registration. GET calls are unthrottled.
- Equity instructions are `BUY`, `SELL`, `BUY_TO_COVER` and `SELL_SHORT`. Option instructions are `BUY_TO_OPEN`, `BUY_TO_CLOSE`, `SELL_TO_OPEN` and `SELL_TO_CLOSE`.
- An option symbol has four parts: the root padded to 6 characters, `YYMMDD`, `C` or `P`, and the strike × 1000 padded to 8 digits. For example, `XYZ   240315C00050000` is a $50 call expiring 2024-03-15.
- Strategy types are `SINGLE`, `TRIGGER` (one-triggers-other, with children under `childOrderStrategies`) and `OCO`. A bracket entry with target and stop is a `TRIGGER` whose child is an `OCO`. The OAuth PDF has worked JSON for each.

## Next steps (not built)

1. **Reconcile against the book.** Diff Schwab positions against `gettarget_positions.csv` (symbol and share count) and flag lots that exist on only one side.
2. **Stops on the book.** Read `WORKING` orders and check that each open lot has the stop and target `getTarget_output.csv` recommends.
3. `previewOrder` is a safe dry run for sizing and commission checks, if order work is ever wanted. Placing real orders would need an explicit decision and its own governance.
