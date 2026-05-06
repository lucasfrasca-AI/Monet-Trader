# Routine: post-open

You are running the **post-open** routine for Monet-Trader. Fires at
10:00 ET (30 minutes after market open). Single job: enforce the
**setup-invalidation rule** on positions opened during today's
market-open routine.

This routine exists because the 30-minute setup-invalidation rule cannot
be enforced by either market-open (it ends at ~09:35) or midday (12:00 ET
is past the window). Cron: `0 14 * * 1-5` UTC (DST) / `0 15` UTC (standard).

## Setup (always run first)
Before any other action:
1. Run: `pip install -r requirements.txt --break-system-packages --quiet`
2. Verify imports: `python -c "import alpaca, yfinance, requests, dotenv, yaml"`
3. If either fails, post a critical Discord alert via `python scripts/discord_notify.py --critical "Setup failed in post-open"` and halt. Do NOT proceed with the routine logic.

## Step 0 — Load context
1. `CLAUDE.md`
2. `config.yaml`
3. `memory/portfolio.md`
4. Today's `memory/research_log.md` entry (pre-market plan + market-open execution)
5. `memory/trade_log.md` last 5 entries (to identify today's fills)

## Step 1 — Identify today's new fills
Use `alpaca_client.list_orders(status="closed", limit=50)` and filter:
- `filled_at` falls within today's market session (after 09:30 ET)
- `side` matches the entry direction (buy for long, sell for short)
- `client_order_id` starts with `monet-{date}-` and contains `-entry`

Skip positions opened *before* today (held overnight from a 1-2 day swing).

## Step 2 — For each new fill, evaluate setup-invalidation
For each fill, compute:
```python
from datetime import datetime, timezone
import zoneinfo

now_utc = datetime.now(timezone.utc)
fill_time = datetime.fromisoformat(order["filled_at"])
minutes_since_entry = (now_utc - fill_time).total_seconds() / 60

# Current market state for this symbol
latest = alpaca_client.get_latest_trade(symbol)
current_price = float(latest["p"])
entry_price = float(order["filled_avg_price"])
atr = alpaca_client.calculate_atr(symbol, period=14)

# Excursion in ATR units (positive = unfavourable for the position)
if direction == "long":
    excursion = (entry_price - current_price) / atr if atr else 0.0
else:
    excursion = (current_price - entry_price) / atr if atr else 0.0
```

Then call:
```python
from scripts.risk_check import evaluate_exit_triggers
result = evaluate_exit_triggers(
    minutes_since_entry=minutes_since_entry,
    atr_excursion_atrs=max(0.0, excursion),
    current_r_multiple=0.0,        # immaterial for the 30-min rule
    et_hour=10,
    proximity_to_tp1_in_r=1.0,     # immaterial for the 30-min rule
)
```

If `result.should_exit and result.trigger_id == "setup_invalidation"`:
- Cancel any working bracket legs for this position via `alpaca_client.cancel_order`.
- Submit a market exit via `alpaca_client.submit_market_order` (opposite side, full qty).
- Append to `memory/trade_log.md` with action=`manual_exit`, note=`setup_invalidation`.
- Post a `stop_loss` Discord embed:
  - title: `🔴 SETUP INVALIDATED: TICKER`
  - fields: minutes_since_entry, ATR excursion, original entry, exit price

## Step 3 — Reconcile and persist
- Refresh `memory/portfolio.md` from `get_positions()`.
- Append a "post-open execution summary" to today's `research_log.md` with:
  - new fills evaluated
  - setup-invalidation exits triggered (with reasons)
  - any positions that passed the 30-min check (these continue under their bracket stops)
- Post a `summary` Discord embed (skip if no actions taken):
  - title: `🎨 post-open — YYYY-MM-DD`
  - fields: positions evaluated, setup invalidations cut

## Step 4 — Persist state
```
git add -A
git commit -m "post-open YYYY-MM-DD — N invalidations cut"
git push
```
If `git push` fails, retry once. If it fails again, post a `critical`
Discord alert and stop.

## What you MUST NOT do in this routine
- Submit any new entries (it's not your job; pre-market plans entries).
- Modify positions opened before today.
- Override the bracket stop-loss on positions that pass the 30-min check.
- Skip the audit log into `research_log.md`.
- Modify `CLAUDE.md`, `config.yaml`, `memory/strategy.md`, or `scripts/risk_check.py`.
