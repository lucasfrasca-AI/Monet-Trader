"""Alpaca trading + market-data client.

All Alpaca interactions in Monet-Trader go through this module. Other scripts
must NOT make direct REST calls to Alpaca.

Paper vs live is controlled exclusively by ALPACA_BASE_URL in the environment:
  paper: https://paper-api.alpaca.markets
  live:  https://api.alpaca.markets

The market-data API (bars, latest quote, etc.) always lives at
data.alpaca.markets regardless of paper/live trading.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

TRADING_BASE_URL = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets").rstrip("/")
DATA_BASE_URL = "https://data.alpaca.markets"

_API_KEY = os.environ.get("ALPACA_API_KEY_ID", "")
_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")

DEFAULT_TIMEOUT_S = 15


def _headers() -> dict[str, str]:
    if not _API_KEY or not _SECRET_KEY:
        raise RuntimeError("ALPACA_API_KEY_ID / ALPACA_SECRET_KEY missing from environment")
    return {
        "APCA-API-KEY-ID": _API_KEY,
        "APCA-API-SECRET-KEY": _SECRET_KEY,
    }


class AlpacaError(RuntimeError):
    """Raised for any non-2xx Alpaca response."""


def _request(method: str, url: str, **kwargs: Any) -> Any:
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT_S)
    resp = requests.request(method, url, headers=_headers(), **kwargs)
    if not resp.ok:
        raise AlpacaError(f"{method} {url} -> {resp.status_code}: {resp.text}")
    if resp.status_code == 204 or not resp.text:
        return None
    return resp.json()


# ---------------------------------------------------------------------------
# Account + positions
# ---------------------------------------------------------------------------

def get_account() -> dict[str, Any]:
    return _request("GET", f"{TRADING_BASE_URL}/v2/account")


def get_positions() -> list[dict[str, Any]]:
    return _request("GET", f"{TRADING_BASE_URL}/v2/positions") or []


def get_position(symbol: str) -> dict[str, Any] | None:
    try:
        return _request("GET", f"{TRADING_BASE_URL}/v2/positions/{symbol}")
    except AlpacaError as exc:
        if "404" in str(exc) or "position does not exist" in str(exc).lower():
            return None
        raise


def close_position(symbol: str, qty: float | None = None, percentage: float | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if qty is not None:
        params["qty"] = qty
    if percentage is not None:
        params["percentage"] = percentage
    return _request(
        "DELETE",
        f"{TRADING_BASE_URL}/v2/positions/{symbol}",
        params=params or None,
    )


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

def list_orders(status: str = "open", limit: int = 100) -> list[dict[str, Any]]:
    return _request(
        "GET",
        f"{TRADING_BASE_URL}/v2/orders",
        params={"status": status, "limit": limit, "direction": "desc"},
    ) or []


def get_order(order_id: str) -> dict[str, Any]:
    return _request("GET", f"{TRADING_BASE_URL}/v2/orders/{order_id}")


def cancel_order(order_id: str) -> None:
    _request("DELETE", f"{TRADING_BASE_URL}/v2/orders/{order_id}")


def submit_market_order(
    symbol: str,
    qty: float,
    side: str,
    time_in_force: str = "day",
    client_order_id: str | None = None,
) -> dict[str, Any]:
    """Submit a plain market order. Use submit_bracket_order for entries with
    attached stop/take-profit. This helper exists for closing trims.
    """
    body: dict[str, Any] = {
        "symbol": symbol,
        "qty": str(qty),
        "side": side,
        "type": "market",
        "time_in_force": time_in_force,
    }
    if client_order_id:
        body["client_order_id"] = client_order_id
    return _request("POST", f"{TRADING_BASE_URL}/v2/orders", json=body)


def submit_bracket_order(
    symbol: str,
    qty: float,
    side: str,
    stop_price: float,
    take_profit_price: float,
    time_in_force: str = "day",
    client_order_id: str | None = None,
    entry_type: str = "market",
    limit_price: float | None = None,
) -> dict[str, Any]:
    """Submit a bracket entry with attached stop-loss and take-profit legs.

    Per CLAUDE.md hard rule: no entry without an attached stop. This helper
    is the canonical entry path.
    """
    body: dict[str, Any] = {
        "symbol": symbol,
        "qty": str(qty),
        "side": side,
        "type": entry_type,
        "time_in_force": time_in_force,
        "order_class": "bracket",
        "stop_loss": {"stop_price": f"{stop_price:.2f}"},
        "take_profit": {"limit_price": f"{take_profit_price:.2f}"},
    }
    if entry_type == "limit":
        if limit_price is None:
            raise ValueError("limit_price required when entry_type='limit'")
        body["limit_price"] = f"{limit_price:.2f}"
    if client_order_id:
        body["client_order_id"] = client_order_id
    return _request("POST", f"{TRADING_BASE_URL}/v2/orders", json=body)


def submit_stop_order(
    symbol: str,
    qty: float,
    side: str,
    stop_price: float,
    time_in_force: str = "gtc",
    client_order_id: str | None = None,
) -> dict[str, Any]:
    """Standalone stop order. Used to attach a protective stop to an existing
    position when bracket wasn't possible.
    """
    body: dict[str, Any] = {
        "symbol": symbol,
        "qty": str(qty),
        "side": side,
        "type": "stop",
        "stop_price": f"{stop_price:.2f}",
        "time_in_force": time_in_force,
    }
    if client_order_id:
        body["client_order_id"] = client_order_id
    return _request("POST", f"{TRADING_BASE_URL}/v2/orders", json=body)


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

def get_latest_trade(symbol: str) -> dict[str, Any]:
    data = _request("GET", f"{DATA_BASE_URL}/v2/stocks/{symbol}/trades/latest")
    return data.get("trade", {}) if data else {}


def get_latest_quote(symbol: str) -> dict[str, Any]:
    data = _request("GET", f"{DATA_BASE_URL}/v2/stocks/{symbol}/quotes/latest")
    return data.get("quote", {}) if data else {}


def get_daily_bars(symbol: str, days: int = 30) -> list[dict[str, Any]]:
    end = datetime.now(timezone.utc) - timedelta(minutes=20)  # IEX feed lag tolerance
    start = end - timedelta(days=days * 2 + 5)                # buffer for weekends/holidays
    data = _request(
        "GET",
        f"{DATA_BASE_URL}/v2/stocks/{symbol}/bars",
        params={
            "timeframe": "1Day",
            "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limit": days,
            "adjustment": "raw",
            "feed": "iex",
        },
    )
    return data.get("bars", []) if data else []


def calculate_atr(symbol: str, period: int = 14) -> float | None:
    """Wilder's ATR over `period` daily bars. Returns None if insufficient data."""
    bars = get_daily_bars(symbol, days=period + 5)
    if len(bars) < period + 1:
        return None
    trs: list[float] = []
    prev_close = float(bars[0]["c"])
    for bar in bars[1:]:
        high = float(bar["h"])
        low = float(bar["l"])
        close = float(bar["c"])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
        prev_close = close
    if len(trs) < period:
        return None
    # Simple average for the first ATR; Wilder smoothing thereafter.
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


# ---------------------------------------------------------------------------
# Asset metadata
# ---------------------------------------------------------------------------

def get_asset(symbol: str) -> dict[str, Any]:
    return _request("GET", f"{TRADING_BASE_URL}/v2/assets/{symbol}")


def is_hard_to_borrow(symbol: str) -> bool:
    """An asset is HTB (or otherwise un-shortable) if Alpaca says it is not
    shortable, or it is shortable but easy_to_borrow=False.
    """
    asset = get_asset(symbol)
    if not asset.get("shortable", False):
        return True
    if asset.get("easy_to_borrow", True) is False:
        return True
    return False


# ---------------------------------------------------------------------------
# Intraday change + moving averages (used by macro overlays + scoring)
# ---------------------------------------------------------------------------

def get_intraday_change_pct(symbol: str) -> float | None:
    """Return today's % change from prior close to latest trade.

    Used by macro overlays (WTI/USO, copper/CPER, 10Y/TLT, SPY) and by the
    scoring rubric. Returns None on data unavailability so callers can
    decide whether to skip filter or proceed without it.
    """
    bars = get_daily_bars(symbol, days=3)
    if len(bars) < 2:
        return None
    prior_close = float(bars[-2]["c"])
    latest = get_latest_trade(symbol)
    last_price = float(latest.get("p", 0))
    if last_price <= 0 or prior_close <= 0:
        # Fall back to today's close on the most recent bar (after-hours / non-trading window).
        last_price = float(bars[-1]["c"])
    if prior_close <= 0:
        return None
    return (last_price - prior_close) / prior_close


def get_moving_average(symbol: str, period: int) -> float | None:
    """Simple moving average of the last `period` daily closes."""
    bars = get_daily_bars(symbol, days=period + 5)
    closes = [float(b["c"]) for b in bars[-period:]]
    if len(closes) < period:
        return None
    return sum(closes) / period


def get_ma_slope(symbol: str, period: int, lookback: int = 5) -> float | None:
    """Approximate slope of the SMA over `lookback` sessions.

    Returns (sma_now - sma_lookback_ago) / sma_lookback_ago. Positive = rising.
    """
    bars = get_daily_bars(symbol, days=period + lookback + 5)
    closes = [float(b["c"]) for b in bars]
    if len(closes) < period + lookback:
        return None
    sma_now = sum(closes[-period:]) / period
    sma_then = sum(closes[-(period + lookback):-lookback]) / period
    if sma_then <= 0:
        return None
    return (sma_now - sma_then) / sma_then


def get_avg_volume(symbol: str, period: int = 20) -> float | None:
    bars = get_daily_bars(symbol, days=period + 5)
    vols = [float(b.get("v", 0)) for b in bars[-period:]]
    if len(vols) < period:
        return None
    return sum(vols) / period


def get_today_volume(symbol: str) -> float | None:
    bars = get_daily_bars(symbol, days=2)
    if not bars:
        return None
    return float(bars[-1].get("v", 0))


# ---------------------------------------------------------------------------
# Macro state — hybrid Alpaca (US ETFs) + yfinance (index symbols)
# ---------------------------------------------------------------------------
# Why hybrid: Alpaca's market-data API only carries US equities/ETFs; it
# cannot price index symbols like ^VIX (CBOE Vol Index) or ^TNX (CBOE 10-Year
# Treasury Yield Index). For those, we use yfinance directly.
#
# Per-symbol contracts emitted into macro_state:
#
#   ETF proxies (USO, CPER, SPY) — sourced from Alpaca
#     {symbol, source: "alpaca", available: True,
#      price, sma_20, below_20dma, change_pct}
#
#   ^VIX (volatility index) — sourced from yfinance
#     {symbol: "^VIX", source: "yfinance", available: True,
#      value, sma_20, intraday_open, change_pct, below_20dma, stale: bool}
#     If yfinance fails/missing: {available: False, reason: "VIX_UNAVAILABLE"}
#     We NEVER substitute VXX or any other proxy — strategy.md's VIX>25 / >35
#     thresholds reference real VIX, not a proxy.
#
#   ^TNX (CBOE 10-Year Treasury Yield Index) — sourced from yfinance
#     {symbol: "^TNX", source: "yfinance", available: True,
#      yield_pct, sma_20_yield_pct, intraday_open_yield_pct,
#      bps_change_intraday, stale: bool}
#     If yfinance fails/missing: {available: False, reason: "TNX_UNAVAILABLE"}
#     The macro overlay rules in strategy.md reference 10Y in BPS
#     (>5bps DTCR block, >10bps tech-longs cap) — never a TLT % approximation.

def _yf_intraday_state(symbol: str, sma_period: int = 20) -> dict[str, Any]:
    """Fetch intraday + 20-day-mean state for an index symbol via yfinance.

    Returns a dict with `available=True` and the relevant fields, or
    `available=False` with a `reason` string. Never raises.
    """
    try:
        import yfinance as yf
    except ImportError as exc:
        return {"available": False, "reason": f"yfinance not installed: {exc}"}

    try:
        ticker = yf.Ticker(symbol)
        daily = ticker.history(period="2mo", interval="1d")
        if daily is None or daily.empty:
            return {"available": False, "reason": f"no daily data for {symbol}"}
        sma_20 = float(daily["Close"].tail(sma_period).mean())
        last_daily_close = float(daily["Close"].iloc[-1])

        # Intraday minute bars for today's open + current value.
        intraday = ticker.history(period="1d", interval="1m")
        if intraday is None or intraday.empty or len(intraday) < 1:
            # Pre-market or feed gap — return last daily close, mark stale.
            return {
                "available": True,
                "stale": True,
                "value": last_daily_close,
                "sma_20": sma_20,
                "intraday_open": None,
                "intraday_change_abs": None,
                "change_pct": None,
                "below_20dma": last_daily_close < sma_20,
                "note": "intraday minute data unavailable; using last daily close",
            }

        today_open = float(intraday["Open"].iloc[0])
        latest = float(intraday["Close"].iloc[-1])
        change_abs = latest - today_open
        change_pct = change_abs / today_open if today_open else None
        return {
            "available": True,
            "stale": False,
            "value": latest,
            "sma_20": sma_20,
            "intraday_open": today_open,
            "intraday_change_abs": change_abs,
            "change_pct": change_pct,
            "below_20dma": latest < sma_20,
        }
    except Exception as exc:
        return {"available": False, "reason": f"yfinance error: {exc}"}


def _alpaca_etf_state(symbol: str, sma_period: int = 20) -> dict[str, Any]:
    """ETF proxy state via Alpaca: change_pct + 20DMA + below_20dma flag."""
    state: dict[str, Any] = {"symbol": symbol, "source": "alpaca"}
    try:
        change = get_intraday_change_pct(symbol)
    except AlpacaError:
        change = None
    try:
        sma_20 = get_moving_average(symbol, period=sma_period)
    except AlpacaError:
        sma_20 = None
    try:
        latest = get_latest_trade(symbol)
        price = float(latest.get("p", 0)) or None
    except AlpacaError:
        price = None
    below_20dma = bool(price and sma_20 and price < sma_20)
    state.update({
        "available": price is not None,
        "price": price,
        "sma_20": sma_20,
        "below_20dma": below_20dma,
        "change_pct": change,
    })
    return state


def get_macro_state(proxies: dict[str, str]) -> dict[str, Any]:
    """Fetch macro overlay state for each proxy in `proxies`.

    Routing rules:
      - Symbols starting with "^" → yfinance (index symbols Alpaca doesn't carry)
      - Anything else → Alpaca ETF data

    For ^VIX, the returned dict contains `value` (the VIX spot value).
    For ^TNX, the dict additionally exposes `yield_pct` (synonym for `value`)
    and `bps_change_intraday` (computed from intraday open vs latest).

    Failed yfinance fetches return `{available: False, reason: "..."}`. The
    legacy top-level `vix_value` key is preserved for routine compatibility:
    set to the ^VIX `value` if available, otherwise None.
    """
    state: dict[str, Any] = {}
    proxies = proxies or {}
    for alias, symbol in proxies.items():
        if not symbol:
            continue
        if symbol.startswith("^"):
            yf_state = _yf_intraday_state(symbol)
            yf_state["symbol"] = symbol
            yf_state["source"] = "yfinance"
            if not yf_state.get("available"):
                # Hard-flag specific aliases the strategy depends on.
                if alias == "vix":
                    yf_state["reason"] = yf_state.get("reason", "VIX_UNAVAILABLE")
                elif alias == "rates_10y":
                    yf_state["reason"] = yf_state.get("reason", "TNX_UNAVAILABLE")
            # ^TNX-specific derived fields (yield_pct + bps_change_intraday).
            if alias == "rates_10y" and yf_state.get("available"):
                value = yf_state.get("value")
                open_v = yf_state.get("intraday_open")
                yf_state["yield_pct"] = value
                yf_state["sma_20_yield_pct"] = yf_state.get("sma_20")
                yf_state["intraday_open_yield_pct"] = open_v
                # ^TNX is in percent (e.g. 4.416 = 4.416%); bps = (close - open) * 100.
                if value is not None and open_v is not None:
                    yf_state["bps_change_intraday"] = (value - open_v) * 100
                else:
                    yf_state["bps_change_intraday"] = None
            state[alias] = yf_state
        else:
            state[alias] = _alpaca_etf_state(symbol)

    # Backward-compat: surface ^VIX value at top level for routines that read it.
    vix_block = state.get("vix") or {}
    state["vix_value"] = vix_block.get("value") if vix_block.get("available") else None
    return state


# ---------------------------------------------------------------------------
# Calendar + clock
# ---------------------------------------------------------------------------

def get_clock() -> dict[str, Any]:
    return _request("GET", f"{TRADING_BASE_URL}/v2/clock")


def get_calendar(start: str | None = None, end: str | None = None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {}
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    return _request("GET", f"{TRADING_BASE_URL}/v2/calendar", params=params or None) or []


# ---------------------------------------------------------------------------
# Earnings calendar
# ---------------------------------------------------------------------------
# Alpaca does not expose an earnings calendar. Per CLAUDE.md, the routine
# uses /trade quick or /trade earnings (web-search-driven skills) to confirm
# earnings windows. This helper is a placeholder hook so risk_check has a
# stable interface; the routine populates the schedule before calling.

def has_earnings_within(symbol: str, hours: int, schedule: dict[str, str] | None = None) -> bool:
    """Return True if `schedule[symbol]` is an ISO-8601 datetime within `hours`
    from now. `schedule` is supplied by the routine (sourced from research).
    Empty/absent entries return False (no known earnings).
    """
    if not schedule or symbol not in schedule:
        return False
    try:
        when = datetime.fromisoformat(schedule[symbol].replace("Z", "+00:00"))
    except ValueError:
        return False
    delta = when - datetime.now(timezone.utc)
    return timedelta(0) <= delta <= timedelta(hours=hours)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"Trading base URL: {TRADING_BASE_URL}")
    acct = get_account()
    print(f"Account status:   {acct.get('status')}")
    print(f"Cash:             ${acct.get('cash')}")
    print(f"Equity:           ${acct.get('equity')}")
    print(f"Shorting enabled: {acct.get('shorting_enabled')}")
    print(f"Trading blocked:  {acct.get('trading_blocked')}")

    clock = get_clock()
    print(f"Market open:      {clock.get('is_open')}  (next open {clock.get('next_open')})")

    print("Sampling ATR(14) + moving averages for NVDA...")
    atr = calculate_atr("NVDA", period=14)
    sma50 = get_moving_average("NVDA", 50)
    sma200 = get_moving_average("NVDA", 200)
    slope50 = get_ma_slope("NVDA", 50)
    intraday = get_intraday_change_pct("NVDA")
    print(f"  ATR(14)={atr}  50DMA={sma50}  200DMA={sma200}")
    print(f"  50DMA slope (5-sess)={slope50}  intraday_change={intraday}")

    print("Sampling macro state (USO/CPER/SPY via Alpaca; ^VIX/^TNX via yfinance)...")
    macro = get_macro_state({
        "wti": "USO",
        "copper": "CPER",
        "rates_10y": "^TNX",
        "spy": "SPY",
        "vix": "^VIX",
    })
    for k, v in macro.items():
        if k == "vix_value":
            print(f"  vix_value (legacy top-level): {v}")
            continue
        if not v.get("available", True):
            print(f"  {k:10s} UNAVAILABLE — {v.get('reason')}")
            continue
        if k == "vix":
            print(f"  {k:10s} {v['symbol']:6s} value={v.get('value'):.2f} "
                  f"sma20={v.get('sma_20'):.2f} change_pct={v.get('change_pct')} "
                  f"below_20dma={v.get('below_20dma')} stale={v.get('stale')}")
        elif k == "rates_10y":
            yld = v.get("yield_pct")
            bps = v.get("bps_change_intraday")
            sma = v.get("sma_20_yield_pct")
            print(f"  {k:10s} {v['symbol']:6s} yield={yld:.3f}% sma20={sma:.3f}% "
                  f"bps_change_intraday={bps:+.2f}bps stale={v.get('stale')}")
        else:
            print(f"  {k:10s} {v['symbol']:6s} change_pct={v.get('change_pct')} "
                  f"price={v.get('price')} below_20dma={v.get('below_20dma')}")

    positions = get_positions()
    print(f"Open positions:   {len(positions)}")
    for p in positions:
        print(f"  {p.get('symbol')} {p.get('qty')} @ {p.get('avg_entry_price')}")
