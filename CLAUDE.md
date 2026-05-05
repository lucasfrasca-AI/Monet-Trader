# Monet-Trader — operating rules

## 1. Project purpose

Monet-Trader is a personal automated trading system for US equities and
ETFs. It runs as scheduled Claude Code Routines in the Anthropic cloud
and trades through Alpaca. Both **long and short** positions are enabled.
The system is **paper-first** — live capital is enabled only after weeks
of validated paper performance.

## 2. Paper ↔ live switch

The ONLY way to switch between paper and live trading is by changing
`ALPACA_BASE_URL` in the Cloud Environment env vars:

- Paper: `https://paper-api.alpaca.markets`
- Live:  `https://api.alpaca.markets`

No code changes are required. No other config flips. **Do not bypass this.**
Routines must never override `ALPACA_BASE_URL` at runtime, conditionally
swap endpoints, or hardcode a URL anywhere.

## 3. Hard rules — NEVER violate

1. Never hardcode secrets — all keys via `os.environ`.
2. Never bypass `risk_check.py` before order submission.
3. Never write directly to `memory/portfolio.md` — always reconcile from Alpaca first.
4. Never invoke `/trade analyze` (5-subagent heavy skill) from within a routine.
5. Never place an order without an attached stop-loss (use `submit_bracket_order`).
6. Never short a stock flagged hard-to-borrow.
7. Never enter a new position within its earnings blackout window (48h global; 168h LLY; 336h NVDA shorts; per-ticker overrides in `config.yaml → ticker_overrides`).
8. Never exceed the daily loss cap — if breached, hold existing positions but reject new orders.
9. If Alpaca API fails for >5 min during market hours, post a `critical` Discord alert and halt.
10. Never modify `CLAUDE.md`, `config.yaml`, `memory/strategy.md`, or `scripts/risk_check.py` from inside a routine — these are owner-edits only.
11. Never widen a stop-loss after attachment. Stops only tighten.
12. Never pyramid (add to a winning position) — no exceptions.
13. Never average down (add to a losing position) — no exceptions. Same-ticker re-entry after a clean stop-out is a separate trade and follows `re_entry` rules.
14. Never skip the DeepSeek challenger for a candidate that survived filters; if challenger is unavailable, flag the decision as `unilateral` in research_log. For SHORTS the challenger inverts to a CONFIRMER — skip the trade if it does not confirm the bear thesis.
15. Never persist research conclusions to `memory/strategy.md` or `memory/lessons.md` outside the **weekly-review** routine.
16. Never bypass `git push` at the end of a routine — state persistence is mandatory; failure must trigger a `critical` alert.
17. Never headline-chase or trade out-of-cycle. The bot trades the next scheduled routine; manual intervention via the Alpaca dashboard is the owner's job.
18. Never enter premarket. Bot enters only after 09:30 ET (`entry_constraints.no_premarket_entries`).
19. Never enter on Friday after `entry_constraints.friday_no_new_entries_after_hour_et` (default 14:00 ET) — weekend gap risk.
20. Never override an exit triggered by `evaluate_exit_triggers` (setup invalidation / trade kill / time discipline) once acted on; treat it as a fired stop.

## 4. File map

| File | Role |
|---|---|
| `CLAUDE.md` | Operating rules, file map (this file) |
| `config.yaml` | Risk parameters, tickers, conviction tiers, kill-switch thresholds |
| `requirements.txt` | Python deps for routines |
| `.env` | Local secrets (gitignored) — Cloud Environment provides the same vars |
| `.env.example` | Empty template of required env vars |
| `memory/strategy.md` | Owner's prose trading rules — read every run, edited between runs only |
| `memory/portfolio.md` | Current positions mirrored from Alpaca; rebuilt every routine |
| `memory/trade_log.md` | Append-only fill record (entries, partial exits, stops) |
| `memory/research_log.md` | Per-routine research, theses, challenger outputs |
| `memory/lessons.md` | Weekly post-mortems; long memory of patterns and rule edits |
| `routines/pre-market.md` | Research only — build trade plan, no orders |
| `routines/market-open.md` | Execute pre-market plan via bracket orders |
| `routines/post-open.md` | 30-min setup-invalidation check on today's fills (10:00 ET) |
| `routines/midday.md` | Layered exit triggers, news classifier, TP1 management |
| `routines/close.md` | End-of-horizon cap, earnings sweep, daily summary |
| `routines/weekly-review.md` | Friday post-mortem; updates lessons.md |
| `scripts/alpaca_client.py` | All Alpaca trading + market-data calls |
| `scripts/deepseek_challenge.py` | DeepSeek adversarial challenger |
| `scripts/discord_notify.py` | Discord webhook poster (embed colour-coded) |
| `scripts/risk_check.py` | Sizing, portfolio caps, kill switches, pre-trade filters |
| `.claude/skills/` | Pre-existing research skills (`/trade quick`, `/trade thesis`, etc.) |

## 5. Memory file protocol

**Read order at routine start:**
1. `CLAUDE.md` (this file)
2. `config.yaml`
3. `memory/strategy.md`
4. `memory/portfolio.md`
5. `memory/trade_log.md` (last 5 entries)
6. `memory/lessons.md` (last 5 entries)

**Write order at routine end:**
1. Reconcile `memory/portfolio.md` from Alpaca account state.
2. Append any fills to `memory/trade_log.md`.
3. Append today's research/decisions to `memory/research_log.md`.
4. (`close` routine only) Append daily summary section.
5. (`weekly-review` only) Append to `memory/lessons.md`.
6. `git add -A && git commit -m "<routine-name> <date> — <summary>" && git push`

## 6. Per-routine focus

- **pre-market** — Research only. Score each candidate against the 6-item
  conviction rubric. Apply ticker overrides + macro overlays + event
  windows. Run the DeepSeek challenger on every survivor. Output the
  trade plan to `memory/research_log.md`. **NEVER place orders.**

- **market-open** — Execute the pre-market plan via **bracket** orders only
  (`alpaca_client.submit_bracket_order`). Re-validate macro state, event
  windows, and portfolio caps before each fill. No discretionary entries;
  no premarket; no Friday late entries.

- **post-open** — 10:00 ET. Single job: enforce the 30-minute setup-
  invalidation rule on today's new fills. If a position is down >1× ATR
  within 30 min of entry, market-exit and log `setup_invalidation`.

- **midday** — Position management only. Run the news classifier on each
  held ticker (`direct-clean` / `direct-ambiguous` / `indirect` / `positive`
  / `none`) and apply the rule table. Evaluate `risk_check.evaluate_exit_triggers`
  per position (trade kill at -1.5R; time discipline at 12:00 ET).
  Manage TP1 fills + trail stops to breakeven. **No new entries.**

- **close** — End-of-horizon cap (close any position open since day 2);
  earnings blackout sweep (close anything with earnings within window);
  daily P&L summary; net-loss-stop accounting for tomorrow's lockout
  evaluation.

- **weekly-review** — Friday post-mortem. Compute weekly metrics. Audit
  rule violations and lockout triggers. Reflect on challenger accuracy.
  Append to `memory/lessons.md`. Propose at most ONE adjustment for owner
  review (do not apply it).

## 7. Decision-making framework

- Direction (long, short, or skip) is the routine's call, informed by
  research, technicals, and sentiment.
- Conviction tier (high / medium / hold) determines position size; do not
  size up beyond what conviction supports.
- Every proposed trade goes through the DeepSeek challenger; if challenger
  raises a credible bear case (`bear_case_strength` ≥ 4), reduce size,
  tighten stop, or skip per `strategy.md`.
- Risk is non-negotiable: always reference `risk_check.py` outputs before
  submitting orders.
- When in doubt between two interpretations of the data, choose the
  smaller position or skip.

## 8. Skill usage discipline

- **Pre-market**: `/trade quick <ticker>` ONLY (lightweight, no subagent spawn).
- **New-position entry candidates**: `/trade thesis <ticker>` ONCE per ticker;
  cache the output verbatim into `memory/research_log.md`.
- **Earnings within 7 days** for any candidate: auto-invoke `/trade earnings <ticker>`.
- **Weekly review**: `/trade portfolio` and optionally `/trade report-pdf`.
- **NEVER** auto-invoke `/trade analyze` from a routine — the 5-subagent
  spawn is too heavy for scheduled use; reserve for interactive sessions.

## 9. Failure modes — what to do when things break

- **Alpaca returns 5xx or auth error** → retry once with 5s backoff. If
  still failing, post `critical` Discord alert and halt.
- **DeepSeek timeout (>30s)** → proceed with the original thesis but flag
  the routine output: "challenger unavailable, decision unilateral".
  Note this in research_log so weekly-review can audit it.
- **Discord webhook fails** → log to `memory/research_log.md` and continue.
  Notifications are not blocking; trading state is.
- **`/trade quick` returns no data** → proceed using technicals from
  `alpaca_client` (latest trade + ATR + bars) and flag in research_log.
- **`git push` fails** → retry once. If it fails again, halt and post a
  `critical` alert. State persistence is mandatory.
- **Bracket-order submit raises** → DO NOT fall back to a plain market
  order. Skip the candidate, log the failure, post a `warning` embed.

## 10. Disclaimer

Research-grade automation for personal use. Not financial advice.
Paper-first; live trading requires explicit single-env-var change. Past
performance does not predict future results. The owner is responsible
for all decisions.
