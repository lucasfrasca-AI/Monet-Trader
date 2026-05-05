# Trading strategy — Monet-Trader

> Read every routine. Decision rules, not philosophy. Bot follows literally.
> Owner edits between runs only. Numeric thresholds live in `config.yaml`;
> this file encodes the rules and the rationale.

## Core operating principles

- Capital preservation first. A 10% drawdown needs 11% to recover; a 50% needs 100%. The asymmetry of losses is the dominant constraint.
- Rules over reads. Discipline beats discretion in a 4-routine/day cadence; the bot waits for the next cycle and never freelances.
- Challenger is a brake. When DeepSeek raises a credible bear case, reduce or skip — both are wins.
- Edge is process. Same setup + same risk repeated > one-shot conviction.

## Time horizon

- Default: intraday. Flat by close most days.
- Stretch: 1–2 day swings allowed when setup quality requires.
- Hard cap: never hold past close of day 2. Any position open at close-of-day-2 → market exit.
- No new entries after 14:00 ET on Friday (weekend gap risk).
- Never enter premarket. Bot enters only after 09:30 ET.

## Universe and per-ticker handling

| Ticker | Direction | Notes |
|---|---|---|
| MSFT | long-only | breakout-buying allowed; trends cleanly |
| ISRG | long-only | compounding name; treat dips as accumulation |
| LMT | long-only, max conviction = medium | fade spikes, never chase; smaller size |
| TSLA | both, max conviction = medium, 1.5× ATR | sentiment vehicle; smaller size; never hold through Elon events |
| NVDA | both with constraints | dip-only longs (no breakout chase); shorts require all 6 signals + extras |
| LLY | both, 7d earnings blackout | binary news risk; cut faster than MSFT on bad news |
| FCX | both | macro cyclical; respect copper direction |
| XOM | both | energy cyclical; respect WTI direction |
| AIQ | both, expect <10% of trades | ETF; redundant with NVDA/MSFT/DTCR; let conviction tiering self-deprioritise |
| DTCR | both, expect <10% of trades | slow REIT-style; news-light; let conviction tiering self-deprioritise |

## Conviction scoring — LONG (6-item checklist; routine ticks each ✓/✗ in research_log)

1. Trend regime: price > 50DMA AND > 200DMA, both up-sloping.
2. Volume: today ≥ 1.2× the 20-day average.
3. Setup pattern is one of:
   - pullback to rising 20DMA / 50DMA + bullish reversal candle, OR
   - breakout from multi-day consolidation on volume, OR
   - higher-low + higher-high continuation
4. Catalyst: positive in last 5 sessions OR scheduled within 14 days.
5. Challenger: no thesis-breaking risk (strength ≤ 5 AND counter ≠ skip).
6. Skill score: `/trade quick` ≥ 75 OR `/trade thesis` "Strong"/"Moderate".

Score → size: `6/6 → 10%`, `5/6 → 8%`, `4/6 → drop to medium 5–7%`, `≤3/6 → skip`.

## Conviction scoring — SHORT (6-item; HTB-clear AND challenger-confirms are mandatory)

1. Trend break: lost 50DMA on heavy volume in last 5 sessions, OR clean distribution-top breakdown.
2. Distribution: down-day volume > rally-day volume + multiple red-volume spikes in last 10 sessions.
3. Sector rotation OUT: sector ETF in bottom third RS over last 5 sessions.
4. Negative catalyst: ≤5 days actual OR ≤7 days scheduled.
5. Failed breakout pattern (cleanest single signal).
6. HTB clear AND challenger confirms (challenger role inverts to confirmer).

Score → size: `6/6 → 7%`, `5/6 → 5%`, `≤4/6 → skip`.

**No medium-short tier.** Clean bear case or sit out.

## NVDA short — additional bar

NVDA shorts require ALL 6 signals above PLUS:
- SPY < 20DMA AND weakening.
- VIX > 18.
- 14-day earnings blackout (vs the global 7d / 48h).
- Stop = 1.5× ATR.
- Max size = 5% of equity.

## Auto-downgrade overrides (apply before sizing)

- VIX > 25 → all entries downgrade one tier (high → medium, medium → skip).
- VIX > 35 → max conviction = medium across the basket.
- Macro blackout day (FOMC / CPI / NFP / PCE) → skip all new entries; existing stops tightened by 25%.
- 10Y up >10bps intraday → tech longs (NVDA / MSFT / TSLA) max → medium.
- 10Y up >5bps intraday → no new DTCR longs.
- SPY < 20DMA AND down >0.5% intraday → all basket longs max → medium.
- WTI down >0.5% intraday → no XOM longs. WTI up >0.5% → no XOM shorts.
- Copper down >0.5% intraday → no FCX longs. Copper up >0.5% → no FCX shorts.

## Catalyst handling

| Event | Rule |
|---|---|
| Earnings day-of (any held ticker) | blackout: 48h global; 7d for LLY |
| Earnings day+1 | size × 0.5; stop = 1.5× ATR; no premarket entry; challenger MUST address the reaction |
| Earnings day+2+ | back to normal sizing |
| FOMC / CPI / NFP / PCE | no new entries; existing stops tightened by 25% |
| LLY major Phase 3 / PDUFA | 48h before → 24h after blackout |
| ISRG FDA action | 7-day window, 50% size, no blackout |
| Geopolitical / unscheduled headlines | rule-bound only — never headline-chase; wait for next routine |
| TSLA narrative event (Shareholder Day, Robotaxi, AI Day, deliveries, model launches) | same as earnings: blackout day-of, day+1 constrained |
| TSLA short + Elon-news risk in research | force-close the short before the event |

## Exit triggers (precedence order)

1. **Setup invalidation** — position down >1× ATR within 30 min of entry → market exit.
2. **Trade kill** — position at -1.5R any time intraday → market exit.
3. **Time discipline** — by 12:00 ET, position underwater >-0.5R AND not within 0.25R of TP1 → market exit.
4. Bracket stop hit.
5. TP1 — sell 50%, trail remaining stop to breakeven; then TP2 closes the rest.
6. End-of-horizon cap — any position still open at close of day 2 → market exit.

Stop respect:
- Stops never widen. Only tighten.
- Position-level dollar pain never overrides the bracket stop or the layered cuts above.
- Portfolio kill switches halt NEW orders only — they never force-exit existing positions inside their stops.

## News reaction during an active routine

The routine MUST classify `/trade quick` output for held tickers as one of:
`direct-clean`, `direct-ambiguous`, `indirect`, `positive`.

| Class | Action | Stop logic |
|---|---|---|
| Direct invalidation, **clean** (major-firm downgrade, guidance cut, hard regulatory action, peer FDA reject for LLY, securities lawsuit) | close at market | n/a |
| Direct invalidation, **ambiguous** (CEO change unclear bias, narrow product-liability suit, mixed signal) | falls through to indirect rule | per below |
| Indirect — position **profitable** | hold | move stop to breakeven |
| Indirect — position **underwater** | hold; reduce size 50% only if signal strongly negative (peer miss >15%, sector ETF down >3% intraday) | keep original stop |
| Positive news on a held position | ignore | leave geometry alone |

## Re-entry rules

After a clean stop-out, re-entry on the same ticker requires:
- New independent entry signal per the conviction rubric (ticked ✓/✗).
- Fresh ATR-based stop recalculated.
- Fresh DeepSeek challenger pass on the new thesis.
- Logged as `stop-out re-entry` in trade_log.md.

Frequency caps:

| Tier | Tickers | Daily cap | Weekly ceiling |
|---|---|---|---|
| High-density | TSLA, NVDA-longs, FCX, XOM | 2 | 4 |
| Medium-density | MSFT, LLY, ISRG, LMT, AIQ, DTCR, NVDA-shorts | 1 | 3 |

- **Same-day re-entry sizing:** 50% of the size the conviction tier would otherwise produce. No exemptions. Full size resets next session.
- **Direction flip:** allowed only after ≥2 hours since the original stop-out AND a distinct new catalyst (macro / news / sector / fresh technical breakdown). Pure price-action flip → blocked.
- **Lockout:** 2 net-loss stop-outs on the same ticker within 5 sessions → lock the ticker until next Monday open. Log to `lessons.md`.
  - Net-loss only: a "TP1 hit, stop trailed to breakeven, then stopped at breakeven" outcome does NOT count.

## Never violate (enforced as CLAUDE.md hard rules)

- Never average down on a losing position.
- Never pyramid into a winning position.
- Never headline-chase or trade out-of-cycle. Wait for the next scheduled routine.
- Never widen a stop after attachment.
- Never enter without an attached stop (use bracket orders).
- Never short hard-to-borrow.
- Never enter inside an earnings blackout window.
- Never override a fired stop or auto-exited position.

## Weekly review (Friday)

Every weekly-review routine must answer, in writing, into `lessons.md`:
1. Which trades worked? Setup or luck?
2. Which trades failed? Did the challenger flag the risk? Did sizing fit?
3. Were any of the rules above violated? Why?
4. Pattern of the week — one observation strong enough to influence next week.
5. ONE proposed adjustment (owner reviews; bot does not apply it).
