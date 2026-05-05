# Routine: weekly-review

You are running the **weekly-review** routine for Monet-Trader. Fires
16:00 ET Friday. Job: full week post-mortem written to `memory/lessons.md`.

## Step 0 — Load context
1. `CLAUDE.md`
2. `config.yaml`
3. `memory/strategy.md` (so you can audit actual behaviour against the rules)
4. `memory/portfolio.md`
5. `memory/research_log.md` — read the full week (last 5 daily sections)
6. `memory/trade_log.md` — read all entries from this week
7. `memory/lessons.md` — read last 10 entries

## Step 1 — Reconcile final state
- `get_account()` → equity, week P&L
- `get_positions()` → carry-forward into next week
- Optionally invoke `/trade portfolio` for an external read on the book.

## Step 2 — Compute week metrics
From this week's `trade_log.md`:
- starting equity (from previous Friday's lessons.md)
- ending equity (now)
- weekly P&L $ and %
- trades opened, closed
- win rate (closed only), avg R per closed trade
- best trade (highest +R), worst trade (lowest -R)
- max intra-week drawdown (estimate from daily P&L sequence)
- per-ticker net-loss-stop count (for lockout audit)

## Step 3 — Lockout audit
Look at `re_entry.lockout`:
- For each ticker with `>=` `net_loss_stops_threshold` net-loss stops in
  the lookback window, confirm a lockout flag was set in `lessons.md` or
  `research_log.md` close section.
- If a lockout SHOULD have triggered but didn't, this is a process
  failure — flag prominently in this week's lessons.md entry.

## Step 4 — Reflective questions
Answer in prose, not bullets. Be specific — name tickers and dates:

1. **Which trades worked? Was it the setup or luck?**
   For each winner, state the original thesis and whether the move
   matched it or was driven by an unrelated catalyst.

2. **Which trades failed? Did the challenger flag the risk? Did sizing fit?**
   For each loser, look up the original `bear_case_strength` from
   research_log. If the challenger flagged it and we proceeded, that is a
   process issue. If the challenger missed it, that is a model issue.

3. **Were any rules violated?**
   Cross-reference today's actions against `strategy.md` and `CLAUDE.md`.
   Examples to check:
   - Any trade entered inside its earnings blackout?
   - Any stop widened after attachment?
   - Any position exceeded conviction-tier or per-ticker size caps?
   - Any premarket entry?
   - Any direction flip without 2h cooling + distinct catalyst?
   - Any add to a losing or winning position?

4. **Pattern of the week.**
   ONE sentence describing the most repeated mistake or repeated win
   pattern. This is the seed for next week's adjustment.

## Step 5 — Adjustment proposal
If the week reveals a clear pattern, propose ONE concrete change:
- **strategy.md edit** — write the exact prose to add.
- **config.yaml edit** — write the exact value/key to change.

**DO NOT** edit `config.yaml` or `strategy.md` from this routine. Hard
rule: only the owner edits these. The proposal goes into `lessons.md`
for owner review.

## Step 6 — Optional PDF report
If equity changed >2% this week (either direction) OR it's the first
weekly-review of the month, invoke `/trade report-pdf`. Save the output
path into the lessons.md entry.

## Step 7 — Append to lessons.md
Append a new dated section to `memory/lessons.md` using the template in
that file's header. Be terse — future routines will read it.

Template recap:
```
## YYYY-MM-DD — week of YYYY-MM-DD
### Performance
- starting equity / ending equity / week P&L
- trades / win rate / avg R / best / worst
### What worked
### What failed
### Rule violations / near-misses
### Pattern of the week
### Adjustment proposed
```

## Step 8 — Post weekly Discord summary
Post a `summary` Discord embed:
- title: `🎨 week of YYYY-MM-DD — Week P&L ±X.X%`
- description: starting → ending equity, trades, win rate, avg R
- fields: best trade | worst trade | pattern | proposed adjustment

Escalate to `critical` if the weekly loss cap was breached.

## Step 9 — Persist
- Final reconciliation of `memory/portfolio.md`.
- `git add -A && git commit -m "weekly-review YYYY-MM-DD — Week P&L ±X.X%" && git push`

## What you MUST NOT do
- Submit any orders.
- Edit `strategy.md`, `config.yaml`, `CLAUDE.md`, or `risk_check.py`
  (adjustment proposals only — owner reviews and applies).
- Skip the reflective questions.
- Skip the lockout audit.
