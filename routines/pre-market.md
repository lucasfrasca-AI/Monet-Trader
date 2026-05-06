# Routine: pre-market

You are running the **pre-market** routine for Monet-Trader. Your sole job
is research and planning. **You will NOT submit any orders during this run.**

## Setup (always run first)
Before any other action:
1. Run: `pip install -r requirements.txt --break-system-packages --quiet`
2. Verify imports: `python -c "import alpaca, yfinance, requests, dotenv, yaml"`
3. If either fails, post a critical Discord alert via `python scripts/discord_notify.py --critical "Setup failed in pre-market"` and halt. Do NOT proceed with the routine logic.

## Step 0 — Load context (in order)
1. `CLAUDE.md` (operating rules — non-negotiable).
2. `config.yaml` (risk parameters, scoring tables, macro overlays, ticker overrides).
3. `memory/strategy.md` (owner's playbook — read in full).
4. `memory/portfolio.md` (last reconciled state — informational).
5. Last 5 entries of `memory/trade_log.md` (recent fills).
6. Last 5 entries of `memory/lessons.md` (long memory).

## Step 1 — Reconcile account state
Run `python3 scripts/alpaca_client.py` to confirm the API is up. Then in
Python fetch:
- `get_account()` → equity, cash, last_equity (for daily P&L)
- `get_positions()` → current open positions with market_value
- `get_clock()` → confirm clock state

Update `memory/portfolio.md` with the snapshot.

## Step 2 — Fetch macro state (ETF proxies)
```python
from scripts.alpaca_client import get_macro_state
cfg = risk_check.load_config()
proxies = cfg["macro_overlays"]["proxies"]
macro_state = get_macro_state(proxies)
```
Capture: WTI/USO direction, copper/CPER direction, 10Y/TLT direction, SPY
direction + below_20DMA, VIX value (or VXX direction as fallback).

Save the snapshot into research_log.

## Step 3 — Identify macro / event blackout days
- Web search "FOMC CPI PCE NFP schedule [today's date YYYY-MM-DD]" to detect
  scheduled macro events. Cross-reference with `config.yaml →
  macro_event_blackout.events`.
- Build `macro_events_today: list[str]`.
- For any held ticker, web-search-confirm upcoming earnings + FDA dates;
  populate `earnings_schedule = {symbol: ISO8601}`,
  `recent_earnings = {symbol: ISO8601 of MOST RECENT earnings within 48h past}`,
  `fda_schedule = {symbol: [ISO8601]}`.

## Step 4 — Run kill-switch evaluation
```python
ks = risk_check.evaluate_kill_switches(
    equity=equity,
    daily_pnl_pct=(equity - last_equity)/last_equity,
    weekly_pnl_pct=<from lessons.md last entry; 0.0 if unknown>,
    vix=macro_state.get("vix_value") or <fallback heuristic from VXX>,
    alpaca_failure_minutes=0.0,
)
```
If `ks.halt_new_orders=True`: post a `critical` Discord embed with reasons,
write the halt event to `research_log.md`, commit, push, and stop.

## Step 5 — Build today's watchlist
For each ticker in `config.yaml → universe.tickers`:
- Invoke `/trade quick <ticker>` (lightweight).
- Record signal, key levels, near-term catalyst into research_log.
- Skip tickers where `/trade quick` returns no actionable signal.
- For `low_activity` tickers (AIQ, DTCR per `ticker_overrides`): expect <10%
  of trades to land here; do not force entries.

**Hard rule:** Do NOT invoke `/trade analyze`. Only `/trade quick` and (where
merited) `/trade thesis` or `/trade earnings`.

## Step 6 — Score each candidate against the conviction rubric
For each ticker with a Buy/Sell signal, ENUMERATE the 6 criteria from
`memory/strategy.md` and tick ✓/✗ for each into research_log:

**LONG (size from `scoring.long_score_to_pct`):**
1. Trend regime: price > 50DMA AND > 200DMA, both up-sloping (use
   `alpaca_client.get_moving_average` and `get_ma_slope`).
2. Volume: today's `get_today_volume / get_avg_volume(20)` ≥ 1.2.
3. Setup pattern: pullback / consolidation breakout / HH+HL continuation.
4. Catalyst: positive in last 5 sessions OR scheduled within 14 days.
5. Challenger: pending step 9 — assume tentatively pass; will re-check.
6. Skill score: `/trade quick` ≥ 75 OR `/trade thesis` "Strong"/"Moderate".

**SHORT (size from `scoring.short_score_to_pct`):**
1. Trend break: lost 50DMA on heavy volume in last 5 sessions OR
   distribution-top breakdown.
2. Distribution pattern: down-day volume > rally-day volume.
3. Sector rotation OUT: sector ETF (`config.sector_etfs`) bottom 1/3 RS in 5
   sessions.
4. Negative catalyst (≤5 days actual or ≤7 days scheduled).
5. Failed breakout pattern.
6. HTB clear (`is_hard_to_borrow=False`) AND challenger confirms (pending).

Compute `score_count`. Determine `desired_pct`:
- LONG: 6 → 10%, 5 → 8%, 4 → 6% (medium), <4 → skip.
- SHORT: 6 → 7%, 5 → 5%, <5 → skip. **No medium-short tier.**
- NVDA short: requires ALL 6 + SPY < 20DMA + VIX > 18.

## Step 7 — Apply ticker overrides + macro overlays
For each candidate:
```python
from scripts.risk_check import (
    resolve_max_conviction, evaluate_macro_overlays
)
# Conviction clamp
conviction = "high" if score in (5,6) else "medium"
conviction = resolve_max_conviction(symbol, conviction, cfg)

# Macro overlay
macro = evaluate_macro_overlays(symbol, direction, macro_state, cfg)
if macro.blocked:
    record reason; drop candidate
elif macro.downgrade_to_medium:
    conviction = "medium" if conviction == "high" else conviction
```

Apply VIX downgrade: if `vix > scoring.vix_downgrade_threshold`, downgrade
one tier; if `vix > scoring.vix_max_medium_threshold`, force medium.

## Step 8 — Event-window evaluation
```python
from scripts.risk_check import evaluate_event_window
ev = evaluate_event_window(
    symbol, direction,
    earnings_schedule=earnings_schedule,
    recent_earnings=recent_earnings,
    fda_schedule=fda_schedule,
    macro_events_today=macro_events_today,
)
```
- `ev.allowed=False` → drop the candidate; record reason.
- `ev.size_factor < 1` → multiply qty later by this factor.
- `ev.atr_multiplier_override` → use this in `compute_stop_price` instead of default.
- `ev.challenger_must_address=True` → flag for step 9.

## Step 9 — Compute stop, TPs, sizing
For each surviving candidate:
```python
atr = alpaca_client.calculate_atr(symbol)
entry = float(alpaca_client.get_latest_trade(symbol)["p"])
stop = risk_check.compute_stop_price(
    entry, atr, direction, cfg=cfg, symbol=symbol,
    atr_multiplier_override=ev.atr_multiplier_override,
)
tp1, tp2 = risk_check.compute_take_profits(entry, stop, direction, cfg=cfg)

sizing = risk_check.size_position(
    equity, entry, stop, direction, conviction,
    cfg=cfg, vix=vix, symbol=symbol,
    desired_pct=score_to_position_pct(direction, score, cfg),
)

# Apply event-window size factor.
if ev.size_factor < 1.0:
    sizing.qty = int(sizing.qty * ev.size_factor)

# Apply kill-switch reduce factor (e.g. equity 94% -> 0.5).
if ks.reduce_size_factor < 1.0:
    sizing.qty = int(sizing.qty * ks.reduce_size_factor)
```

## Step 10 — Pre-trade filters
For each candidate:
```python
f = risk_check.validate_pre_trade_filters(
    symbol, direction,
    is_htb=alpaca_client.is_hard_to_borrow(symbol),
    earnings_within_blackout=False,        # already enforced via evaluate_event_window
    avg_daily_volume=get_avg_volume(symbol, 20),
    spread_pct=<computed from get_latest_quote>,
)
```
Drop any candidate with `f.allowed=False`.

## Step 11 — Re-entry validation
For each candidate, build the re-entry context from `trade_log.md`:
- `today_re_entries`: count of prior same-direction entry attempts on this
  symbol today.
- `week_re_entries`: same, within current calendar week.
- `last_stop_out`: most recent stop-out on this symbol (any direction).
- `recent_net_loss_stops`: net-loss stops on this symbol in last 5 sessions.
- `has_distinct_new_catalyst`: routine's judgement (set False unless macro
  /news/sector/breakdown introduced new info).

```python
re = risk_check.validate_re_entry(
    symbol, direction, today_iso=today, ...
)
if not re.allowed:
    drop candidate; record re.reasons
elif re.size_factor < 1.0:
    sizing.qty = int(sizing.qty * re.size_factor)
```

## Step 12 — Run challenger on every survivor
For each surviving candidate, call:
```python
result = deepseek_challenge.challenge(
    ticker=symbol, direction=direction,
    entry=entry, target=tp1, stop=stop,
    conviction=conviction,
    rationale=<summary including any post-earnings or news context>,
)
```

If `ev.challenger_must_address=True` (post-earnings day+1), the rationale
text MUST mention the earnings reaction explicitly. If the challenger
response does not address it, skip the trade.

Apply challenger verdict per `strategy.md`:
- strength 1-3: proceed
- strength 4-5: tighten stop OR trim 25%
- strength 6-7: halve size
- strength 8-10: skip
- challenger=unavailable: proceed but flag `unilateral` in research_log

For SHORTS: challenger role inverts — must CONFIRM the bear thesis. If it
does not, skip.

## Step 13 — Validate against portfolio caps
```python
val = risk_check.validate_new_position(
    symbol, direction, sizing, current_positions, equity, cfg=cfg
)
```
Drop any candidate that breaches concurrent-position / sector / exposure
caps. If multiple candidates would pass individually but together breach,
prefer higher score + higher challenger margin.

## Step 14 — Friday cutoff check
If today is Friday AND the routine fires after `entry_constraints.
friday_no_new_entries_after_hour_et`, mark all candidates as
`WATCH_ONLY` regardless of score. (The pre-market routine fires at 06:00
ET so this is rarely active, but the logic must exist.)

## Step 15 — Write the trade plan
Append to `memory/research_log.md` a section dated today with:
- account snapshot, kill-switch state
- macro state snapshot
- macro_events_today, earnings_schedule, fda_schedule
- watchlist scan table
- per-ticker scoring (✓/✗ per criterion)
- per-ticker challenger output (verbatim)
- final candidate list: ticker | direction | score | conviction | entry |
  stop | TP1 | TP2 | qty | $size | risk$ | flags (post-earnings, indirect,
  re-entry, ATR override)

Mark each as `EXECUTE_AT_OPEN` or `WATCH_ONLY`.

## Step 16 — Post Discord brief
Post a `summary` (or `critical` if halted) Discord embed:
- title: `🎨 pre-market plan — YYYY-MM-DD`
- description: count of EXECUTE_AT_OPEN / WATCH_ONLY, equity, VIX
- fields: one per EXECUTE_AT_OPEN with score, qty @ entry, stop, TP1

## Step 17 — Persist state
1. Save updated `memory/portfolio.md`.
2. Save trade plan into `memory/research_log.md`.
3. `git add -A && git commit -m "pre-market YYYY-MM-DD — N candidates" && git push`.
4. If `git push` fails, retry once. If it fails again, post a `critical`
   Discord alert and stop.

## What you MUST NOT do in this routine
- Submit any order to Alpaca.
- Modify `CLAUDE.md`, `config.yaml`, `memory/strategy.md`, or `scripts/risk_check.py`.
- Invoke `/trade analyze`.
- Skip the challenger on any surviving candidate.
- Skip the per-criterion ✓/✗ scoring write-up — auditability is mandatory.
- Approve a SHORT entry where the challenger does not CONFIRM the bear thesis.
