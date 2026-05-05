# Routine: close

You are running the **close** routine for Monet-Trader. Fires ~15:55 ET
(5 min before market close). Job: end-of-horizon exits, earnings sweep,
end-of-day-2 cap enforcement, daily P&L summary, prep for tomorrow.

## Step 0 — Load context
1. `CLAUDE.md`
2. `config.yaml`
3. `memory/portfolio.md`
4. Today's full `memory/research_log.md` entry (pre-market + post-open + midday)
5. `memory/trade_log.md` last 10 entries (today's fills)

## Step 1 — Final reconciliation
- `get_account()` → equity, day P&L %, last_equity
- `get_positions()` → open positions with realized + unrealized P&L
- `list_orders(status="open")` → working orders
- `list_orders(status="closed", limit=50)` → today's fills

## Step 2 — End-of-horizon cap (close of day 2)
For each open position, look up its entry timestamp from `trade_log.md`.
If the position has been open for `>=` `exit_triggers.end_of_horizon_days *
24` hours minus the close-of-day buffer (i.e. it has lived through TWO
sessions and is still open at the close of day 2):
- Cancel bracket legs.
- `submit_market_order` opposite side, full qty (use day TIF; market
  order at the close).
- Log action=`manual_exit`, note=`end_of_horizon`.
- Post a `summary` Discord embed.

## Step 3 — Earnings-blackout sweep
For each remaining open position, check earnings within next 48h (or
per-ticker override; LLY=168h). Use `risk_check.resolve_earnings_blackout_hours`.
If earnings within window:
- Close the position at market.
- Cancel bracket legs.
- Log action=`manual_exit`, note=`earnings_blackout`.
- Post a `warning` Discord embed.

This rule overrides "let winners run" — earnings blackouts are
non-negotiable. For LLY shorts, the 7-day window applies; for NVDA shorts,
14 days.

## Step 4 — Day-loss-cap check (post-hoc, informational)
If today's P&L hit `portfolio.daily_loss_cap_pct`, note it in
`research_log.md` AND seed a candidate item for next Friday's
`weekly-review`. Do NOT force-close positions inside their stops.

## Step 5 — Stale-order cleanup
For unfilled day orders that didn't trigger:
- Cancel them via `cancel_order`.
- Brackets attached to filled positions remain (GTC).

## Step 6 — Compute daily summary
Calculate:
- Day P&L $ and %
- Trades opened today / closed today
- Win count, loss count, avg R per closed trade
- Net-loss stops today (count per ticker — feeds tomorrow's lockout check)
- Exposure: long $, short $, net $, % of equity
- Open position count vs cap (8)

Append a "close" subsection to today's `research_log.md` with:
- summary table
- list of every order action today (entry, TP1 fill, stop hit, manual_exit)
- per-ticker net-loss-stop count
- carry-forward watchlist for tomorrow's pre-market

## Step 7 — Post Discord summary
Post a `summary` Discord embed:
- title: `🎨 close — YYYY-MM-DD — Day P&L ±X.X%`
- description: equity start → end, trades today, win/loss, net-loss stops
- fields: top winner / top loser / open positions count / carry-forward
  (max 5 tickers)

If day P&L hit any kill-switch threshold, escalate to `critical`.

## Step 8 — Persist
- Final reconciliation of `memory/portfolio.md`.
- Append all today's sections to `memory/research_log.md`.
- `git add -A && git commit -m "close YYYY-MM-DD — Day P&L ±X.X%" && git push`

## What you MUST NOT do
- Submit a new entry at the close.
- Hold a position into earnings — earnings sweep is mandatory.
- Hold a position into close-of-day-2 — end-of-horizon cap is mandatory.
- Skip the per-ticker net-loss-stop accounting (feeds the lockout system).
- Skip the git push.
