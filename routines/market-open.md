# Routine: market-open

You are running the **market-open** routine for Monet-Trader. Fires at
09:30 ET. Job: execute today's pre-market plan with discipline.

## Step 0 — Load context
1. `CLAUDE.md`
2. `config.yaml`
3. `memory/strategy.md`
4. `memory/portfolio.md`
5. Most recent `memory/research_log.md` entry (today's pre-market plan)
6. Last 5 entries of `memory/trade_log.md` and `memory/lessons.md`

## Step 1 — Confirm market is open + account is OK
- `alpaca_client.get_clock()` → `is_open=True`. If False, post a `warning`
  Discord (clock mismatch / holiday) and abort.
- `alpaca_client.get_account()` → confirm `trading_blocked=False`.

## Step 2 — Re-run kill switches
Re-evaluate `evaluate_kill_switches(...)`. If `halt_new_orders=True`, post
`critical` embed, append the halt event to `research_log.md`, commit, push,
and stop.

## Step 3 — Re-fetch macro state
```python
macro_state = alpaca_client.get_macro_state(cfg["macro_overlays"]["proxies"])
```
Compare with the pre-market snapshot. If any macro signal flipped (e.g.
WTI was up at pre-market but is now down >0.5%), re-run
`evaluate_macro_overlays` for affected XOM/FCX/DTCR candidates and drop
those that now block.

## Step 4 — Friday cutoff guard
If today is Friday AND clock hour ≥ `entry_constraints.
friday_no_new_entries_after_hour_et`, abort all entries for the day.
(Defensive — pre-market should have already flagged WATCH_ONLY.)

## Step 5 — Premarket guard
The clock at 09:30 ET = market open. Reject any candidate whose
`order_class` would fire as `extended_hours=True`. We use `time_in_force=
"day"` and `extended_hours=False` (default) — never accept a candidate
that requires premarket execution. This enforces `entry_constraints.
no_premarket_entries`.

## Step 6 — Per-candidate re-validation
For each EXECUTE_AT_OPEN candidate from today's plan:
1. Pull current price via `get_latest_trade(ticker)`.
2. If price drifted >1% from planned entry, recompute stop preserving the
   ORIGINAL ATR-based distance and recompute TP1/TP2. Log the change.
3. Re-run `validate_pre_trade_filters` (HTB status can flip overnight).
4. Re-run `validate_new_position` (existing positions may have changed).
5. Re-run `evaluate_event_window` (catches macro events that materialised).
6. If any check fails, drop the candidate. **Do not relax filters.**

## Step 7 — Submit bracket orders
For each surviving candidate:
```python
order = alpaca_client.submit_bracket_order(
    symbol=ticker, qty=qty,
    side="buy" if direction == "long" else "sell",
    stop_price=stop,
    take_profit_price=tp1,             # TP1 only — TP2 handled manually after TP1 hits
    time_in_force="day",
    client_order_id=f"monet-{date}-{ticker}-entry",
)
```

**Hard rules:**
- Every entry MUST be a bracket order with attached stop-loss.
- Never fall back to a plain market order if `submit_bracket_order` raises;
  post a `warning` Discord and skip the candidate.
- `time_in_force="day"` only (no GTC entries).

After submission:
- Wait 5-10s, call `get_order(order_id)` to confirm filled.
- Append to `memory/trade_log.md` with actual fill price, action=`entry`,
  recording score, conviction, challenger strength, any flags
  (post_earnings / re_entry / macro_downgrade).
- Post a `fill` Discord embed per filled order:
  - title: `🟢 ENTRY: TICKER side qty @ price`
  - fields: stop | TP1 | conviction | score | challenger | flags

## Step 8 — Partial fill handling
If an order is partially filled:
- Log actual filled qty in trade_log.
- Bracket auto-adjusts to filled qty — verify via `get_order`.
- If <50% filled, treat as "partial entry"; do NOT chase by submitting
  another order.

## Step 9 — Reconcile and persist
- Refresh `memory/portfolio.md` from `get_positions()`.
- Append "market-open execution summary" to `research_log.md`:
  attempted / filled / partial / skipped (with reasons).
- Post a `summary` Discord embed: counts and total $ deployed.
- `git add -A && git commit -m "market-open YYYY-MM-DD — N filled" && git push`

## What you MUST NOT do in this routine
- Submit any plain (non-bracket) market order for an entry.
- Take a position not in the pre-market plan. **No discretionary entries.**
- Submit any premarket order (no `extended_hours=True`).
- Widen any stop or modify a stop attached to a fresh bracket.
- Submit Friday entries past the cutoff hour.
- Modify `CLAUDE.md`, `config.yaml`, `memory/strategy.md`, or `scripts/risk_check.py`.
