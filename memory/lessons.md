# Lessons — post-trade reflections

> Updated by the **weekly-review** routine each Friday after market close.
> This is the long-memory layer — patterns, rules to add or relax, biases
> spotted in the system's behaviour. Routines READ the most recent ~5
> entries at every run to inform decisions.

## Format

```
## YYYY-MM-DD — week of YYYY-MM-DD

### Performance
- starting equity: $X | ending equity: $X | week P&L: ±X%
- trades: N | win rate: X% | avg R: X.X
- best trade: TICKER +XR | worst trade: TICKER -XR

### What worked
- ...

### What failed
- ...

### Rule violations / near-misses
- ...

### Pattern of the week
- (one observation strong enough to influence next week's strategy)

### Adjustment proposed
- (concrete change to strategy.md or config.yaml — if any)
```

---

## 2026-05-06 — pre-trade infrastructure note (out-of-cycle)

- 2026-05-06 — Switched macro feeds from Alpaca/TLT proxies to yfinance ^VIX and ^TNX direct. Affects all macro overlay accuracy.
