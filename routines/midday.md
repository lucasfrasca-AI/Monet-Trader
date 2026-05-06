# Routine: midday

You are running the **midday** routine for Monet-Trader. Fires ~12:00 ET.
Job: layered exit-trigger evaluation, news classification on held tickers,
and protective stop adjustments. **No new entries.**

## Setup (always run first)
Before any other action:
1. Run: `pip install -r requirements.txt --break-system-packages --quiet`
2. Verify imports: `python -c "import alpaca, yfinance, requests, dotenv, yaml"`
3. If either fails, post a critical Discord alert via `python scripts/discord_notify.py --critical "Setup failed in midday"` and halt. Do NOT proceed with the routine logic.

## Step 0 — Load context
1. `CLAUDE.md`
2. `config.yaml`
3. `memory/strategy.md`
4. `memory/portfolio.md`
5. Today's `memory/research_log.md` entry (pre-market plan + market-open + post-open)
6. `memory/trade_log.md` last 10 entries (today's actions)

## Step 1 — Reconcile
- `get_account()` → equity, daily P&L
- `get_positions()` → current positions with unrealized P&L, qty, avg_entry_price
- `list_orders(status="open")` → working brackets / stops / TPs

Update `memory/portfolio.md`.

## Step 2 — Macro events: tighten stops on event days
If today's pre-market detected a macro blackout event (FOMC/CPI/NFP/PCE
in `macro_events_today`), tighten the working stop on each open position
by `macro_event_blackout.stop_tighten_pct` (default 25%).

```python
for position in positions:
    current_stop = <fetch from working orders>
    new_stop_distance = abs(entry - current_stop) * (1 - 0.25)
    new_stop_price = entry - new_stop_distance  # long; reverse for short
    # Cancel old stop leg, submit new tighter one (same qty, GTC)
    cancel_order(old_stop_id)
    submit_stop_order(symbol, qty, opposite_side, new_stop_price, time_in_force="gtc")
```
Log each tightening.

## Step 3 — Kill-switch re-check
If `evaluate_kill_switches(...).halt_new_orders=True`, post `critical`
Discord — but DO NOT close positions reflexively. Continue with the
position management below.

## Step 4 — Per-position news classification
For each open position, invoke `/trade quick <ticker>` once. Classify the
output as one of:

- **`direct-clean`** — major-firm downgrade, guidance cut, hard regulatory
  action, peer FDA reject for LLY, securities lawsuit. UNAMBIGUOUS thesis
  invalidation.
- **`direct-ambiguous`** — CEO change of unclear bias, narrow product-
  liability suit, mixed-signal news. Falls through to indirect rule.
- **`indirect`** — peer warning, sector rotation, macro shift, related-
  ticker news.
- **`positive`** — upgrade, beat aftermath, supportive macro.
- **`none`** — no material news today.

## Step 5 — Apply news-driven actions
For each classified position:

| Class | Profitable now? | Action |
|---|---|---|
| `direct-clean` | any | Close at market. Cancel bracket legs. Log `manual_exit` note=`thesis_invalidated`. Post `stop_loss` embed. |
| `direct-ambiguous` | profitable | Move stop to breakeven (cancel old stop leg; submit new). Log. |
| `direct-ambiguous` | underwater | Hold. If signal is strongly negative (peer miss >15% per `news.indirect_strong_negative_thresholds.peer_earnings_miss_pct` OR sector ETF down >3%), reduce qty by 50% via `submit_market_order` (opposite side). Log. |
| `indirect` | profitable | Move stop to breakeven only if breakeven > current stop (`MAX(current_stop, entry)`). Never move stop adversely. |
| `indirect` | underwater | Hold; reduce qty 50% only if signal strongly negative per thresholds above. Stop unchanged. |
| `positive` | any | Ignore. TP geometry already encodes upside. |
| `none` | n/a | Skip; proceed to step 6. |

Log every action to `trade_log.md` AND `research_log.md` with the
classification reason.

## Step 6 — Layered exit triggers (evaluate per-position)
For each open position:
```python
fill_time = <from trade_log entry>
minutes_since_entry = (now_utc - fill_time).total_seconds() / 60

current_price = get_latest_trade(symbol)["p"]
entry_price = float(position["avg_entry_price"])
atr = alpaca_client.calculate_atr(symbol)

# Excursion in ATR units (positive = unfavourable)
if direction == "long":
    excursion = max(0, (entry_price - current_price) / atr)
else:
    excursion = max(0, (current_price - entry_price) / atr)

# R-multiple
initial_risk_per_share = abs(entry_price - planned_stop)
unrealized_per_share = (current_price - entry_price) if direction == "long" else (entry_price - current_price)
current_r = unrealized_per_share / initial_risk_per_share

# Distance to TP1 in R units
tp1 = <from research_log>
distance_to_tp1 = abs(tp1 - current_price)
proximity_to_tp1_in_r = distance_to_tp1 / initial_risk_per_share

et_hour = <current ET hour, e.g. 12>

result = risk_check.evaluate_exit_triggers(
    minutes_since_entry, excursion, current_r, et_hour, proximity_to_tp1_in_r
)
```

If `result.should_exit`:
- Cancel bracket legs.
- `submit_market_order` opposite side, full qty.
- Append to `trade_log.md` with action=`manual_exit`, note=result.trigger_id.
- Post `stop_loss` Discord embed.

## Step 7 — TP1 management on winners
For positions that have reached TP1 (1R):
- If bracket TP1 auto-filled (50% closed): cancel original bracket stop on
  remaining qty; submit new GTC stop at breakeven (entry price).
- If TP1 not auto-filled but price past TP1: sell 50% via market order;
  trail stop on remaining 50% to breakeven.
- Log action=`tp1`. Post `fill` embed.

## Step 8 — Tighten stops on strong winners (optional)
For positions up >1.5R and not yet at TP2:
- If `/trade quick` confirms momentum continuation: keep breakeven trail.
- If momentum exhausted (RSI overbought + key resistance): tighten to
  recent swing low (long) / swing high (short). Log.

## Step 9 — Post midday brief
Post a `summary` Discord embed:
- title: `🎨 midday — YYYY-MM-DD`
- fields: open positions | day P&L | exits triggered (count + reasons) |
  stops tightened | unrealized P&L

## Step 10 — Persist
- Update `memory/portfolio.md`.
- Append midday section to today's `research_log.md` with all classifications,
  exit triggers fired, stop adjustments.
- `git add -A && git commit -m "midday YYYY-MM-DD — <summary>" && git push`

## What you MUST NOT do
- Submit any new entry. New entries are pre-market only.
- Add to a winning position. No pyramiding.
- Add to a losing position. No averaging down. EVER.
- Widen a stop. Stops only tighten.
- Override a fired stop-loss bracket exit.
- Modify `CLAUDE.md`, `config.yaml`, `memory/strategy.md`, or
  `scripts/risk_check.py`.
