"""One-shot data gather for the research_log baseline seed.

Pulls price + ATR(14) + 50DMA + 200DMA + slopes + recent volume for each
universe ticker, plus macro state. Prints a JSON block the caller can
fold into the research_log entry.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import alpaca_client, risk_check  # noqa: E402

TICKERS = ["NVDA", "MSFT", "AIQ", "DTCR", "LLY", "LMT", "TSLA", "ISRG", "XOM", "FCX"]


def per_ticker(symbol: str) -> dict:
    out: dict = {"symbol": symbol}
    try:
        latest = alpaca_client.get_latest_trade(symbol)
        out["price"] = round(float(latest.get("p", 0)), 2)
    except Exception as exc:
        out["price_error"] = str(exc)

    try:
        out["atr_14"] = round(alpaca_client.calculate_atr(symbol, period=14) or 0, 3)
    except Exception as exc:
        out["atr_error"] = str(exc)

    try:
        out["sma_50"] = round(alpaca_client.get_moving_average(symbol, 50) or 0, 2)
        out["sma_200"] = round(alpaca_client.get_moving_average(symbol, 200) or 0, 2)
        out["slope_50_5sess"] = round(alpaca_client.get_ma_slope(symbol, 50) or 0, 5)
        out["slope_200_5sess"] = round(alpaca_client.get_ma_slope(symbol, 200) or 0, 5)
    except Exception as exc:
        out["ma_error"] = str(exc)

    try:
        avg_vol = alpaca_client.get_avg_volume(symbol, 20)
        today_vol = alpaca_client.get_today_volume(symbol)
        out["avg_vol_20"] = int(avg_vol) if avg_vol else None
        out["today_vol"] = int(today_vol) if today_vol else None
        out["vol_ratio"] = round((today_vol or 0) / (avg_vol or 1), 2) if avg_vol else None
    except Exception as exc:
        out["vol_error"] = str(exc)

    try:
        out["intraday_change_pct"] = round(
            (alpaca_client.get_intraday_change_pct(symbol) or 0) * 100, 2
        )
    except Exception as exc:
        out["intraday_change_error"] = str(exc)

    # Trend regime quick flags
    try:
        out["above_50dma"] = bool(out.get("price") and out.get("sma_50")
                                   and out["price"] > out["sma_50"])
        out["above_200dma"] = bool(out.get("price") and out.get("sma_200")
                                    and out["price"] > out["sma_200"])
        out["sma_50_rising"] = bool(out.get("slope_50_5sess", 0) > 0)
        out["sma_200_rising"] = bool(out.get("slope_200_5sess", 0) > 0)
    except Exception:
        pass

    if out.get("price") and out.get("atr_14"):
        out["atr_pct_of_price"] = round(out["atr_14"] / out["price"] * 100, 2)

    return out


def main() -> int:
    cfg = risk_check.load_config()

    print("== per-ticker data ==")
    snapshots = {}
    for sym in TICKERS:
        snap = per_ticker(sym)
        snapshots[sym] = snap
        print(json.dumps(snap, indent=None))

    print("\n== macro state ==")
    macro = alpaca_client.get_macro_state(cfg["macro_overlays"]["proxies"])
    print(json.dumps(macro, indent=2))

    # Account state for the portfolio note.
    print("\n== account ==")
    acct = alpaca_client.get_account()
    print(json.dumps({
        "equity": acct.get("equity"),
        "cash": acct.get("cash"),
        "shorting_enabled": acct.get("shorting_enabled"),
    }, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
