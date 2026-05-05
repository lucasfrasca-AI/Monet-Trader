"""Dry-run simulation of the pre-market routine's *programmatic* path.

Verifies the wiring between modules (memory reads, alpaca account/clock,
ATR + sizing, kill-switch evaluation, challenger call, validation, log
write, Discord post) WITHOUT calling /trade quick or submitting any
orders. Per CLAUDE.md, no order submission may happen here.

Run:
    python3 scripts/_dry_run_premarket.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import alpaca_client, deepseek_challenge, discord_notify, risk_check  # noqa: E402

PROBE_TICKER = "NVDA"


def main() -> int:
    print(f"== Monet-Trader pre-market dry run ({datetime.now().isoformat(timespec='seconds')}) ==\n")

    print("[1/8] Reading memory files...")
    for fname in ("CLAUDE.md", "config.yaml",
                  "memory/strategy.md", "memory/portfolio.md",
                  "memory/trade_log.md", "memory/lessons.md"):
        path = ROOT / fname
        if not path.exists():
            print(f"  MISSING: {fname}")
            return 1
        size = path.stat().st_size
        print(f"  ok  {fname:32s} ({size} bytes)")

    print("\n[2/8] Loading config...")
    cfg = risk_check.load_config()
    print(f"  universe: {len(cfg['universe']['tickers'])} tickers")
    print(f"  long_enabled={cfg['direction']['long_enabled']} "
          f"short_enabled={cfg['direction']['short_enabled']}")

    print("\n[3/8] Alpaca account + clock...")
    acct = alpaca_client.get_account()
    equity = float(acct["equity"])
    cash = float(acct["cash"])
    print(f"  status={acct['status']}  equity=${equity:,.2f}  cash=${cash:,.2f}")
    clock = alpaca_client.get_clock()
    print(f"  market_open={clock['is_open']}  next_open={clock['next_open']}")

    print("\n[4/8] Kill-switch evaluation (with mock daily/weekly P&L)...")
    ks = risk_check.evaluate_kill_switches(
        equity=equity,
        daily_pnl_pct=0.0,
        weekly_pnl_pct=0.0,
        vix=18.0,             # mock — pre-market would optionally fetch
        alpaca_failure_minutes=0.0,
        cfg=cfg,
    )
    print(f"  halt={ks.halt_new_orders}  reduce_factor={ks.reduce_size_factor}")
    if ks.reasons:
        for r in ks.reasons:
            print(f"   - {r}")

    print(f"\n[5/8] Sampling ATR + price for {PROBE_TICKER}...")
    atr = alpaca_client.calculate_atr(PROBE_TICKER, period=cfg["stops"]["atr_period_days"])
    if atr is None:
        print(f"  ATR unavailable for {PROBE_TICKER}")
        return 1
    trade = alpaca_client.get_latest_trade(PROBE_TICKER)
    price = float(trade.get("p", 0))
    if price <= 0:
        print(f"  latest trade price unavailable for {PROBE_TICKER}")
        return 1
    print(f"  ATR(14)={atr:.2f}  latest_price=${price:.2f}")

    print("\n[6/8] Sizing + portfolio validation (mock high-conv long)...")
    direction = "long"
    conviction = "high"
    stop = risk_check.compute_stop_price(price, atr, direction, cfg=cfg)
    tp1, tp2 = risk_check.compute_take_profits(price, stop, direction, cfg=cfg)
    sizing = risk_check.size_position(equity, price, stop, direction, conviction, cfg=cfg, vix=18.0)
    print(f"  stop=${stop:.2f}  TP1=${tp1:.2f}  TP2=${tp2:.2f}")
    print(f"  qty={sizing.qty}  $size=${sizing.dollar_size:,.2f}  "
          f"position%={sizing.position_pct_of_equity:.2%}  capped_by={sizing.capped_by}")

    positions = alpaca_client.get_positions()
    val = risk_check.validate_new_position(
        PROBE_TICKER, direction, sizing, positions, equity, cfg=cfg
    )
    print(f"  validation.allowed={val.allowed}  reasons={val.reasons or 'none'}")

    print("\n[7/8] DeepSeek challenger probe...")
    challenge_result = deepseek_challenge.challenge(
        ticker=PROBE_TICKER,
        direction=direction,
        entry=price,
        target=tp1,
        stop=stop,
        conviction=conviction,
        rationale="Dry-run smoke test of challenger path; not a real thesis.",
    )
    print(f"  available={challenge_result.available}  "
          f"strength={challenge_result.bear_case_strength}/10  "
          f"recommendation={challenge_result.counter_recommendation}")

    print("\n[8/8] Discord dry-run post...")
    posted = discord_notify.info(
        title="🎨 Monet-Trader dry-run successful",
        description="Scaffolding complete. Pre-market routine wiring verified end-to-end.",
        fields=[
            {"name": "equity", "value": f"${equity:,.2f}", "inline": True},
            {"name": "probe", "value": f"{PROBE_TICKER} ${price:.2f}", "inline": True},
            {"name": "sized_qty", "value": str(sizing.qty), "inline": True},
            {"name": "challenger",
             "value": f"{challenge_result.bear_case_strength}/10 "
                      f"{challenge_result.counter_recommendation}",
             "inline": True},
            {"name": "halt_orders", "value": str(ks.halt_new_orders), "inline": True},
            {"name": "mode", "value": "dry-run (NO orders submitted)", "inline": False},
        ],
    )
    print(f"  discord posted: {posted}")

    print("\nNOTE: No orders were submitted. No state was committed to git.")
    print("Dry run complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
