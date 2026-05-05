# Research log — daily theses + challenger outputs

> Per-routine research notes, candidate trades, and DeepSeek challenger
> verdicts. Append a fresh dated section for each routine run. Keep the
> challenger response verbatim — it is the audit trail for size/skip calls.

## Format

```
## YYYY-MM-DD — pre-market | midday | close

### Account snapshot
- equity: $X
- cash: $X
- positions: N
- daily P&L: ±X%

### Watchlist scan
| Ticker | direction | conviction | entry | stop | TP1 | TP2 | qty | summary |
|---|---|---|---|---|---|---|---|---|
| NVDA | long | high | 145.00 | 138.00 | 152.00 | 159.00 | 68 | beat-and-raise pattern intact |

### Per-ticker theses
#### NVDA
**Thesis:** ...
**Challenger output:**
- bear_case_strength: 6/10
- counter_recommendation: reduce_size
- top_risks: [...]
- missing_evidence: [...]
- rationale: ...
**Decision:** proceeded at half size given strength=6; entry 145.00, stop 138.00.

### Routine outcome
- orders submitted: ...
- orders blocked by risk_check: ...
- kill switches active: ...
- next-routine handoff: ...
```

---

## 2026-05-06 — baseline seed (pre-routine)

> Initial thesis snapshot for all 10 universe tickers. Populated from
> /trade quick + alpaca_client technical data + current narrative search.
> Routines will overwrite/append per their own schedule starting next
> pre-market. This entry exists so the first scheduled routine doesn't
> start cold.

### Account snapshot
- Equity: $100,000 | Cash: $100,000 | Open positions: 0
- Shorting enabled: True
- Trading mode: paper (ALPACA_BASE_URL=paper-api.alpaca.markets)

### Macro tape (intraday at seed time; ^VIX/^TNX via yfinance, USO/CPER/SPY via Alpaca)

- SPY: $723.56, +1.66% intraday, ABOVE 20DMA ($664) — broad-tape downgrade does NOT fire
- ^VIX: 17.47 spot, 20DMA 18.52, intraday -2.67% → low-vol regime. All VIX-based caps inactive (VIX > 25 / > 35 thresholds). NVDA-short VIX > 18 floor also inactive (17.47 < 18) → no NVDA shorts eligible today on volatility regime alone.
- ^TNX (10Y yield, direct): 4.414%, intraday **-1.20bps** (yields slightly DOWN), 20DMA 4.325%. Both rate rules silent — DTCR-block needs +5bps, tech-downgrade needs +10bps.
- WTI (USO proxy): $143.70, +2.95% intraday, ABOVE 20DMA — favours XOM longs, blocks XOM shorts.
- Copper (CPER proxy): $36.37, +0.36% intraday — within ±0.5% band; FCX direction unconstrained by macro.

**Macro overlay rule firings (live):**
- FIRES (1): `xom_wti_short_block` — USO +2.95% ≥ +0.5% threshold → no XOM shorts today.
- SILENT (6): `dtcr_yield_long_block` (need +5bps, observed -1.20bps) · `tech_yield_downgrade` (need +10bps, observed -1.20bps) · `spy_basket_downgrade` (SPY above 20DMA AND positive intraday) · `fcx_copper_long_block` / `fcx_copper_short_block` (CPER within ±0.5%) · `xom_wti_long_block` (USO up, not down).

Net effect: macro tape is *permissive* today for everything except XOM-short. The earlier draft's "yields rising" framing was a TLT-proxy artifact and is corrected here.

### Sector dispersion (intraday)
- AI/tech names split: AIQ +6.99%, DTCR +4.20% (broad theme bid) vs NVDA -7.32%, MSFT -4.43% (mega-cap distribution)
- Healthcare bifurcated: LLY +12.42% (post-earnings continuation) vs ISRG -3.76% (lagging)
- Energy strong: XOM +2.82% (oil rally tailwind)
- Materials weak: FCX -1.01% (Grasberg guidance overhang)
- Defence flat: LMT -0.13%

---

### NVDA
- Current price: $197.53 (-7.32% intraday)
- Trend regime: ABOVE 50DMA ($182.80, declining 5-sess), ABOVE 200DMA ($161.54, rising)
- 14-day ATR: $5.06 (2.56% of price)
- Bull case: AI capex cycle intact, May 20 earnings catalyst with Strong-Buy consensus (37 analysts; avg target $270.73 ≈ +37% upside) and Blackwell demand strong.
- Bear case: -7.32% selloff today on rising 10Y yields plus pre-earnings de-risking; 50DMA already rolling over and emerging GPU competition (Cerebras / Tenstorrent / d-Matrix) lurking.
- Initial bias: long-biased on dips, NO short today (SPY > 20DMA disqualifies the NVDA-short SPY-weakness gate); NVDA 14d earnings blackout for shorts also active (May 6 = 14 days from May 20)
- Key levels: support $182 (50DMA), $185 (recent consolidation floor); resistance $210, then $215 swing high
- Watch triggers: hold of 50DMA into earnings (bullish setup forming) | break of $182 on volume (bias flips no-trade) | gap-and-go reaction to May 20 earnings (post-earnings day+1 framework activates)
- Conviction score (initial): ~3/6 — trend yes (with caveats), volume marginal (1.10×), setup ✗ (mid-selloff, no clean entry), catalyst ✓ (earnings <14d), challenger pending, skill score ✓ Strong Buy. Tactically NOT a clean entry today.

### MSFT
- Current price: $410.38 (-4.43% intraday)
- Trend regime: ABOVE 50DMA ($406.68, declining), BELOW 200DMA ($479.37, slightly rising) — long-term trend regime is BROKEN
- 14-day ATR: $9.62 (2.34% of price)
- Bull case: Q3 FY26 (reported Apr 29) beat with $4.27 EPS vs $4.06 est, Azure +40%, AI revenue $37B run-rate (+123% YoY); Strong-Buy consensus, targets $556+.
- Bear case: $190B FY26 capex (up 61% YoY) with $25B component-cost headwind; price below 200DMA AND tech-yield downgrade fires today; 50DMA decisively declining.
- Initial bias: neutral / no-trade — long-only configured but trend regime fails the high-conv test (price below 200DMA)
- Key levels: support $400 (round, recent floor), $385 (200DMA pullback target if breach); resistance $430 (50DMA test zone), $480 (200DMA)
- Watch triggers: reclaim of $480 200DMA on volume (long thesis re-engages) | breakdown below $400 (waterfall risk to $385)
- Conviction score (initial): ~2/6 — trend ✗, volume ✗ (0.79×), setup ✗ (sell-off mid-routine), catalyst ✗ (just reported), challenger pending, skill score ✓. Skip today.

### AIQ
- Current price: $58.30 (+6.99% intraday)
- Trend regime: ABOVE 50DMA ($49.73, declining), ABOVE 200DMA ($45.02, rising)
- 14-day ATR: $1.17 (2.00% of price)
- Bull case: Diversified AI exposure (87 holdings, top-weighted SK Hynix / Intel / Samsung / AMD / Micron); +54.4% trailing 1y; trades at 52-week high $57.76 today.
- Bear case: 50DMA declining (-1.2% slope) suggests today's spike is reflexive; ETF lacks stock-specific catalysts so DeepSeek challenger has little to dissect.
- Initial bias: long-biased — but flagged `low_activity` per ticker_overrides; expect <10% of trades here
- Key levels: support $50 (50DMA/200DMA confluence forming), $54 recent base; resistance $58 (52w high), $60 round
- Watch triggers: clean breakout above $58 on volume confirmation | rejection at $58 with 50DMA failure
- Conviction score (initial): ~3/6 — trend ✓ (with declining 50DMA caveat), volume ✗ (0.87×), setup ✓ (52w-high test), catalyst ✗ (no specific), challenger pending, skill score N/A (ETF). Likely no-trade today; let conviction tiering self-deprioritise.

### DTCR
- Current price: $29.27 (+4.20% intraday)
- Trend regime: ABOVE 50DMA ($24.78, RISING), ABOVE 200DMA ($19.17, RISING) — cleanest uptrend in basket
- 14-day ATR: $0.49 (1.69% of price)
- Bull case: AI infra buildout proxy (data-centre REITs); both MAs rising, sitting near 52w-high $29.16; volume confirming today (1.58× avg).
- Bear case: Slow REIT-style name with thin liquidity (avg vol only ~18.5k); structurally rate-sensitive — any sharp 10Y backup re-blocks the long via the macro overlay.
- Initial bias: long-biased — clean uptrend (both MAs rising), 10Y move too small to block today; flagged low_activity per ticker_overrides but a legitimate medium-tier candidate if pre-market routine confirms volume/setup tomorrow.
- Key levels: support $26.50 (recent base), $24.80 (50DMA); resistance $29.16 (52w high), $30 round
- Watch triggers: ^TNX intraday bps move ≥+5bps = activates `dtcr_yield_long_block` (sit out) | reclaim above $29.16 52w-high on volume = continuation | breakdown below $26.50 (uptrend negated)
- Conviction score (initial): ~4/6 — trend ✓, volume ✓ (1.58×), setup ✓, catalyst neutral, challenger pending, skill score N/A. Maps to medium tier (5–7% size) per strategy.md scoring table.

### LLY
- Current price: $982.35 (+12.42% intraday)
- Trend regime: BELOW 50DMA ($1,001.85, declining), ABOVE 200DMA ($831.44, rising)
- 14-day ATR: $26.43 (2.69% of price)
- Bull case: Q1 2026 (reported Apr 30) blew estimates — revenue $19.8B +55.5% YoY, EPS $8.55 vs $6.79 est, full-year guide raised to $82-85B; 60% GLP-1 market share; Foundayo (oral GLP-1) just launched.
- Bear case: Trading $20 below 50DMA on a +12% bounce — bearish trend regime with sharp reflex rally, classic "dead-cat" risk; oral GLP-1 generic competition expected 2027-2028 hangs over the multi-year thesis.
- Initial bias: long-biased on a clean continuation, neutral on today's spike (chasing an extended bounce inside a downtrend = poor R:R). 7-day earnings blackout: Q1 was Apr 30, so day+6 today — out of blackout for entries.
- Key levels: support $920 (recent intraday low post-earnings), $850 (analyst low target); resistance $1,001 (50DMA — first test), $1,050 (recent swing high)
- Watch triggers: reclaim of $1,001 50DMA on hold-day volume = high-conv long setup forms | rejection at 50DMA + close below $960 = neutral / no-trade
- Conviction score (initial): ~3/6 — trend ✗ (below 50DMA), volume ✗ (0.84×), setup ✗ (chasing extended spike), catalyst ✓ (post-earnings continuation narrative), challenger pending, skill score ✓ (Buy avg target $1,194). Wait for 50DMA test.

### LMT
- Current price: $511.53 (-0.13% intraday)
- Trend regime: BELOW 50DMA ($632.93 — significant ~19% below; slightly rising), ABOVE 200DMA ($466.82, rising)
- 14-day ATR: $14.37 (2.81% of price)
- Bull case: Defence primes carry multi-year backlog tailwind from persistent geopolitical instability; 200DMA rising; analyst median target $665 = ~30% upside from here.
- Bear case: 2Q25 program losses ($1.6B), FY26 FCF guidance cut to ~$6B; Hold consensus (15 holds vs 6 buys); deeply broken below 50DMA suggests structural concern beyond a normal pullback.
- Initial bias: no-trade today — long-only configured + max conviction medium per ticker_overrides, but trend regime is broken (price 19% below 50DMA), which fails the high-conv trend test. Wait for stabilisation.
- Key levels: support $500 (round, recent low zone), $467 (200DMA — last-line); resistance $540 (recent failed bounce), $632 (50DMA, far)
- Watch triggers: reclaim of recent swing $540 + RS turn-up vs XLI = re-engage | breach of $500 with volume = thesis fully invalidated, sit out indefinitely
- Conviction score (initial): ~1/6 — trend ✗, volume ✗ (1.46× but in distribution context not buying), setup ✗, catalyst ✗, challenger pending, skill score ✗ (Hold). Skip.

### TSLA
- Current price: $392.14 (+4.27% intraday)
- Trend regime: BELOW 50DMA ($405.63, declining), ABOVE 200DMA ($363.16, rising)
- 14-day ATR: $16.38 (4.18% of price — highest volatility in basket)
- Bull case: Q1 2026 EPS beat 41¢ vs 37¢ on stronger gross margin and FCF (per Goldman); robotaxi/Optimus narrative still active; 200DMA rising.
- Bear case: Q1 deliveries 358k vs 365-370k consensus; "growth story is dead" per Electrek headlines; underperformed all megacap-tech peers YTD; tech-yield downgrade to medium fires today; below 50DMA.
- Initial bias: both directions allowed but max conviction = medium per ticker_overrides (TSLA also gets 1.5× ATR stops). Short-leaning if a clean failed-bounce pattern forms; no clean long setup today.
- Key levels: support $370 (recent swing low), $363 (200DMA); resistance $405 (50DMA test), $420 (recent failed-bounce shelf)
- Watch triggers: rejection at 50DMA $405 = clean short setup forms | reclaim of 50DMA on volume = neutral and reassess
- Conviction score (initial): ~2/6 (long), ~3/6 (short) — long: trend ✗, volume ✗ (0.62×), setup ✗. Short: trend break ✓ (below 50DMA), distribution forming, sector RS (XLY) check needed; HTB unverified. Watch only today.

### ISRG
- Current price: $449.19 (-3.76% intraday)
- Trend regime: BELOW 50DMA ($492.33, declining), BELOW 200DMA ($512.73, slightly rising) — both MAs failed
- 14-day ATR: $11.36 (2.53% of price)
- Bull case: Q1 2026 strong — revenue +23%, EBIT +40%, EBIT margin 39% (vs 34%); 2026 procedure guide RAISED to 14-16%; mean analyst target $577 = 28% upside.
- Bear case: Despite the fundamental beat, price has decisively broken both 50DMA AND 200DMA — classic "good earnings, bad chart" — meaning institutional flows are leaving regardless of headline numbers; today -3.76% on elevated volume (1.48×) confirms distribution.
- Initial bias: no-trade today — long-only configured, but trend regime fully broken. Strong fundamentals do NOT override technical regime in an intraday system.
- Key levels: support $445 (recent intraday low), $420 (next visible base); resistance $492 (50DMA), $512 (200DMA)
- Watch triggers: reclaim of 200DMA $512 on volume = trend regime restored | breach of $420 = next leg lower opens
- Conviction score (initial): ~2/6 — trend ✗, volume ✓ (1.48× but distribution-coloured), setup ✗, catalyst ✗ (already digested), challenger pending, skill score ✓. Wait for technical reset.

### XOM
- Current price: $154.79 (+2.82% intraday)
- Trend regime: ABOVE 50DMA ($150.54, RISING), ABOVE 200DMA ($111.80, RISING) — clean uptrend
- 14-day ATR: $5.64 (3.64% of price)
- Bull case: WTI at $99.81 with USO +2.73% intraday and above 20DMA → macro overlay actively favours XOM longs; Q1 2026 (May 1) adjusted EPS $1.16 vs $1.02 est; record Guyana production; both MAs rising.
- Bear case: Macro-driven name with high beta to oil — any reversal in WTI hits XOM 1:1; analyst median target $165 only ~7% upside from here so room is limited; large-cap so post-earnings drift is bounded.
- Initial bias: long-biased — clean uptrend + macro tailwind + within ±5% of analyst median target. No XOM shorts today (USO macro overlay blocks shorts when oil up >0.5%).
- Key levels: support $150 (50DMA), $148 (recent breakout retest); resistance $158 (recent intraday high), $165 (analyst target)
- Watch triggers: pullback to $150 50DMA = clean dip-buy setup | WTI/USO reversal -0.5%+ = blocks longs and reassess | break $158 on volume = continuation
- Conviction score (initial): ~5/6 — trend ✓, volume ✗ (0.73×), setup arguable (already extended +2.82%), catalyst ✓ (post-earnings continuation, oil rally), challenger pending, skill score ✓ (Buy, 25 analysts). Best long candidate in basket today; 5/6 (volume gap) means tactically wait for pullback or volume confirmation rather than chasing.

### FCX
- Current price: $57.62 (-1.01% intraday)
- Trend regime: BELOW 50DMA ($61.19, slightly declining), ABOVE 200DMA ($41.82, rising)
- 14-day ATR: $2.42 (4.20% of price — highest beta in basket alongside TSLA)
- Bull case: Q1 2026 (Apr 23) beat — EPS $0.57 vs $0.47 est (+21%), EBITDA $2.47B (+24%); copper at $5.93/lb supportive; Buy consensus, median target $67.
- Bear case: Grasberg Block Cave guidance cut (wet-ore handling bottleneck) is the overhang dragging price 19% below the Apr-20 ATH of $70.97; below 50DMA in clear pullback.
- Initial bias: neutral — both directions theoretically open per config, but neither has clean conditions today. Copper +0.36% is below the ±0.5% macro overlay threshold so neither direction is macro-blocked. Trend below 50DMA fails high-conv long; failed-breakout pattern from $70 ATH could become a clean short setup if confirmed.
- Key levels: support $55 (recent low zone), $50 (round + uptrend support); resistance $61 (50DMA), $67 (analyst target), $70.97 (ATH)
- Watch triggers: copper futures breakout >+0.5% intraday + FCX reclaim 50DMA = long setup | failed bounce at 50DMA + heavy volume = clean short setup
- Conviction score (initial): ~3/6 (either direction) — trend ✗ for long; trend break ✓ for short but no fresh distribution day yet. Watch only today.

---

### Single observation for the basket

**Today is pure dispersion — rotation within tech, not yield-driven multiple compression.** With ^TNX -1.20bps intraday and ^VIX at 17.47 (low-vol regime), rates are NOT the driver of today's tape. That makes mega-cap tech selling (NVDA -7.32%, MSFT -4.43%) alongside thematic-AI buying (DTCR +4.20%, AIQ +6.99%) cleaner to read: it is unambiguous sector rotation — institutional capital moving WITHIN tech (out of mega-cap, into thematic / infra), not draining out because of macro. The broad index (SPY +1.66%) is masking the rotation. The bot's first scheduled pre-market run inherits a basket where 6/10 names are below their 50DMAs (MSFT, LLY, LMT, TSLA, ISRG, FCX) — trend-regime criterion will fail for those by default. But TWO clean candidates are live tomorrow: **XOM** (uptrend + WTI macro tailwind, both MAs rising) and **DTCR** (cleanest uptrend in basket, both MAs rising, no macro block). Expect **1–3 EXECUTE_AT_OPEN** candidates from tomorrow's pre-market routine.

### Routine handoff
- Next scheduled routine: pre-market (`0 11 * * 1-5` UTC standard; `0 10` UTC during DST) tomorrow morning.
- The pre-market routine WILL re-fetch all this data fresh and re-score from scratch — this baseline is for context only, not binding.
- Anything in this entry should be treated as `WATCH_ONLY` framing; no orders implied.

### Sources used (10 web searches at seed time)
- NVDA: [marketbeat forecast](https://www.marketbeat.com/stocks/NASDAQ/NVDA/forecast/) · [Motley Fool May 20 catalyst](https://www.fool.com/investing/2026/05/05/prediction-nvidia-stock-going-to-soar-after-may-20/)
- MSFT: [CNBC Q3 FY26 earnings](https://www.cnbc.com/2026/04/29/microsoft-msft-q3-earnings-report-2026.html) · [FX Leaders forecast](https://www.fxleaders.com/news/2026/05/02/microsoft-stock-forecast-may-3-2026-azure-and-copilot-drive-ai-growth-even-as-capital-spending-rises/)
- AIQ: [stockanalysis holdings](https://stockanalysis.com/etf/aiq/holdings/)
- DTCR: [Global X fund page](https://www.globalxetfs.com/funds/dtcr)
- LLY: [CNBC Q1 2026 earnings](https://www.cnbc.com/2026/04/30/eli-lilly-lly-earnings-q1-2026.html) · [247WallSt 60% GLP-1 share](https://247wallst.com/investing/2026/05/04/eli-lilly-captures-60-of-the-glp-1-market-as-mounjaro-revenue-soars-125/)
- LMT: [public.com forecast](https://public.com/stocks/lmt/forecast-price-target) · [Seeking Alpha Q1 2026](https://seekingalpha.com/article/4898424-lockheed-martin-q1-2026-noise-vs-signal-in-the-defense-sector)
- TSLA: [CNBC Q1 deliveries](https://www.cnbc.com/2026/04/02/tesla-tsla-q1-2026-vehicle-delivery-production.html) · [CNBC Q1 earnings](https://www.cnbc.com/2026/04/22/tesla-tsla-q1-2026-earnings-report.html)
- ISRG: [TIKR Q1 2026 analysis](https://www.tikr.com/blog/intuitive-surgical-raises-2026-procedure-guidance-after-a-40-ebit-jump-analysts-price-isrg-above-700)
- XOM: [Globe and Mail Q1 2026](https://www.theglobeandmail.com/investing/markets/stocks/XOM-N/pressreleases/1665066/exxonmobil-reports-lower-q1-2026-earnings-highlights-resilience/) · [Meyka earnings preview](https://meyka.com/blog/xom-exxon-mobil-earnings-preview-may-1-2026-3004/)
- FCX: [TIKR Q1 2026 analysis](https://www.tikr.com/blog/freeport-mcmoran-beat-q1-2026-earnings-why-is-the-stock-still-under-61) · [Quiver copper-linked rally](https://www.quiverquant.com/news/Freeport-McMoRan+jumps+3.9%25+as+copper-linked+optimism+builds+ahead+of+earnings)
