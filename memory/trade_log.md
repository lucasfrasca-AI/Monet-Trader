# Trade log — append-only fill record

> **APPEND ONLY.** Routines must NEVER edit or delete existing entries.
> One row per fill (entry, partial exit, full exit, stop trigger).

## Format

Each entry is a markdown subsection like:

```
### YYYY-MM-DD HH:MM ET — TICKER side action
- order_id: <alpaca_order_id>
- qty: <shares>
- price: <fill_price>
- direction: long | short
- action: entry | tp1 | tp2 | stop_hit | manual_exit | reverse
- conviction: high | medium
- challenger_strength: 0-10 (0 = unavailable)
- challenger_recommendation: proceed | tighten_stop | reduce_size | skip
- thesis_link: research_log entry pointer (e.g. `research_log.md#2026-05-06-NVDA`)
- notes: one-line context
```

---

(no fills yet — first market-open routine will append below)
