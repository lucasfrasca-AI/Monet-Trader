"""Risk sizing + portfolio caps + kill switches + macro overlays.

Every order routed through Monet-Trader must be validated by this module
BEFORE submission. The CLAUDE.md hard rules enforce this.

Public API (core):
  - load_config()                        -> dict (cached)
  - size_position(...)                   -> SizingResult
  - validate_new_position(...)           -> ValidationResult
  - evaluate_kill_switches(...)          -> KillSwitchResult
  - validate_pre_trade_filters(...)      -> FilterResult

Public API (extensions):
  - get_ticker_overrides(symbol)         -> dict
  - score_to_position_pct(direction, score) -> float | None
  - evaluate_macro_overlays(...)         -> MacroResult
  - evaluate_event_window(...)           -> EventWindowResult
  - validate_re_entry(...)               -> ReEntryResult
  - evaluate_exit_triggers(...)          -> ExitResult
  - next_monday_open_iso(after)          -> ISO timestamp string
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Ticker overrides + scoring lookup
# ---------------------------------------------------------------------------

def get_ticker_overrides(symbol: str | None, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the per-ticker override block from config (empty dict if none)."""
    if symbol is None:
        return {}
    cfg = cfg or load_config()
    return (cfg.get("ticker_overrides") or {}).get(symbol, {}) or {}


def resolve_atr_multiplier(symbol: str | None, direction: str, cfg: dict[str, Any] | None = None) -> float:
    """Return the effective ATR multiplier for `symbol/direction`, falling
    back to the global stops.atr_multiplier.
    """
    cfg = cfg or load_config()
    base = cfg["stops"]["atr_multiplier"]
    overrides = get_ticker_overrides(symbol, cfg)
    mult = overrides.get("atr_multiplier")
    if mult is None:
        return float(base)
    if isinstance(mult, dict):
        return float(mult.get(direction, base))
    return float(mult)


def resolve_max_conviction(symbol: str | None, requested: str, cfg: dict[str, Any] | None = None) -> str:
    """Clamp the requested conviction tier to the per-ticker max.

    Order: high > medium > hold. If override says max_conviction='medium' and
    requested='high', returns 'medium'. Returns the requested value if no
    override or override is more permissive.
    """
    order = {"hold": 0, "medium": 1, "high": 2}
    cfg = cfg or load_config()
    overrides = get_ticker_overrides(symbol, cfg)
    cap = overrides.get("max_conviction")
    if cap is None:
        return requested
    if order.get(requested, 0) > order.get(cap, 2):
        return cap
    return requested


def resolve_earnings_blackout_hours(
    symbol: str | None,
    direction: str = "long",
    cfg: dict[str, Any] | None = None,
) -> int:
    """Resolve earnings-blackout window in hours for a symbol/direction.

    Honours per-ticker overrides:
      ticker_overrides[symbol].earnings_blackout_hours       (long + global)
      ticker_overrides[symbol].short_earnings_blackout_hours (shorts only)
    Falls back to filters.earnings_blackout_hours.
    """
    cfg = cfg or load_config()
    overrides = get_ticker_overrides(symbol, cfg)
    if direction == "short" and "short_earnings_blackout_hours" in overrides:
        return int(overrides["short_earnings_blackout_hours"])
    if "earnings_blackout_hours" in overrides:
        return int(overrides["earnings_blackout_hours"])
    return int(cfg["filters"]["earnings_blackout_hours"])


def score_to_position_pct(
    direction: str,
    score: int,
    cfg: dict[str, Any] | None = None,
) -> float | None:
    """Map a 0-6 conviction score to position pct.

    Returns None if the score is below the floor for that direction (i.e. skip).
    """
    cfg = cfg or load_config()
    s = cfg.get("scoring") or {}
    if direction == "long":
        table = s.get("long_score_to_pct", {})
        floor = s.get("long_score_floor", 4)
    elif direction == "short":
        table = s.get("short_score_to_pct", {})
        floor = s.get("short_score_floor", 5)
    else:
        return None
    if score < floor:
        return None
    # YAML int keys may load as ints; tolerate both.
    return float(table.get(score, table.get(str(score), 0.0))) or None


# ---------------------------------------------------------------------------
# Position sizing
# ---------------------------------------------------------------------------

@dataclass
class SizingResult:
    qty: int
    dollar_size: float
    position_pct_of_equity: float
    stop_distance_pct: float
    risk_dollars: float
    rationale: str
    capped_by: str            # "risk_budget" | "position_cap" | "min_qty_zero"


def size_position(
    equity: float,
    entry_price: float,
    stop_price: float,
    direction: str,            # "long" or "short"
    conviction: str,           # "high" | "medium" | "hold"
    cfg: dict[str, Any] | None = None,
    vix: float | None = None,
    symbol: str | None = None,
    score: int | None = None,
    desired_pct: float | None = None,
) -> SizingResult:
    """Compute integer share quantity, with all caps applied.

    Cap precedence (smallest wins):
      1. risk_budget = (max_portfolio_risk_pct × equity) / stop_distance_pct
      2. global position cap (long: max_long_position_pct; short: max_short_position_pct)
      3. per-ticker override (max_long_pct / max_short_pct)
      4. conviction tier max_pct (clamped per resolve_max_conviction)
      5. VIX > threshold: vix_high_max_position_pct
      6. score lookup OR explicit desired_pct (takes the smaller)

    `symbol` triggers ticker overrides (max_conviction clamp, max_short_pct
    override). `score` and `desired_pct` are alternative ways to set a target
    pct from the routine; if both omitted, the conviction tier's max_pct is
    used (legacy behaviour).
    """
    cfg = cfg or load_config()

    # Apply per-ticker conviction clamp first.
    conviction = resolve_max_conviction(symbol, conviction, cfg)

    if conviction == "hold":
        return SizingResult(0, 0.0, 0.0, 0.0, 0.0, "conviction=hold; no entry", "min_qty_zero")
    if entry_price <= 0 or equity <= 0:
        return SizingResult(0, 0.0, 0.0, 0.0, 0.0, "non-positive equity or price", "min_qty_zero")

    stop_distance = abs(entry_price - stop_price)
    if stop_distance == 0:
        return SizingResult(0, 0.0, 0.0, 0.0, 0.0, "stop equal to entry", "min_qty_zero")
    stop_distance_pct = stop_distance / entry_price

    # Risk-budget dollar cap (1% of equity ÷ stop distance %).
    max_risk_pct = cfg["per_trade"]["max_portfolio_risk_pct"]
    risk_budget_dollars = max_risk_pct * equity
    risk_dollar_size = risk_budget_dollars / stop_distance_pct

    # Position-pct cap (asymmetric long vs short, with per-ticker overrides).
    overrides = get_ticker_overrides(symbol, cfg)
    if direction == "long":
        cap_pct = overrides.get("max_long_pct", cfg["position_caps"]["max_long_position_pct"])
    elif direction == "short":
        cap_pct = overrides.get("max_short_pct", cfg["position_caps"]["max_short_position_pct"])
    else:
        return SizingResult(0, 0.0, 0.0, 0.0, 0.0, f"invalid direction '{direction}'", "min_qty_zero")
    cap_dollar = float(cap_pct) * equity

    # VIX kill-switch override (cap at vix_high_max_position_pct).
    vix_threshold = cfg["kill_switches"]["vix_high_threshold"]
    if vix is not None and vix > vix_threshold:
        vix_cap = cfg["kill_switches"]["vix_high_max_position_pct"] * equity
        cap_dollar = min(cap_dollar, vix_cap)

    # Conviction tier provides an additional ceiling pct of equity.
    tier = cfg["conviction"].get(conviction, {"min_pct": 0.0, "max_pct": 0.0})
    conviction_cap_dollar = tier["max_pct"] * equity
    cap_dollar = min(cap_dollar, conviction_cap_dollar)

    # Score- or desired-pct-driven target (further ceiling).
    target_pct: float | None = desired_pct
    if score is not None:
        score_pct = score_to_position_pct(direction, score, cfg)
        if score_pct is None:
            return SizingResult(0, 0.0, 0.0, 0.0, 0.0,
                                f"score={score} below floor for direction={direction}; skip",
                                "min_qty_zero")
        target_pct = score_pct if target_pct is None else min(target_pct, score_pct)
    if target_pct is not None:
        target_dollar = float(target_pct) * equity
        cap_dollar = min(cap_dollar, target_dollar)

    chosen_dollar = min(risk_dollar_size, cap_dollar)
    capped_by = "risk_budget" if chosen_dollar == risk_dollar_size else "position_cap"

    qty = int(math.floor(chosen_dollar / entry_price))
    dollar_size = qty * entry_price
    position_pct = dollar_size / equity if equity else 0.0
    risk_dollars = qty * stop_distance

    rationale = (
        f"risk_budget=${risk_dollar_size:,.0f} cap=${cap_dollar:,.0f} "
        f"chosen=${chosen_dollar:,.0f} -> {qty} sh @ ${entry_price:.2f}"
    )
    return SizingResult(
        qty=qty,
        dollar_size=dollar_size,
        position_pct_of_equity=position_pct,
        stop_distance_pct=stop_distance_pct,
        risk_dollars=risk_dollars,
        rationale=rationale,
        capped_by=capped_by,
    )


# ---------------------------------------------------------------------------
# ATR-based stop helper
# ---------------------------------------------------------------------------

def compute_stop_price(
    entry_price: float,
    atr: float,
    direction: str,
    cfg: dict[str, Any] | None = None,
    symbol: str | None = None,
    atr_multiplier_override: float | None = None,
) -> float:
    """Stop = N×ATR from entry, clamped to [floor%, ceiling%] of entry.

    N comes from (in priority order):
      1. explicit `atr_multiplier_override` (e.g. post-earnings 1.5×)
      2. per-ticker override (TSLA: 1.5×, NVDA-short: 1.5×)
      3. global stops.atr_multiplier (2.0)
    """
    cfg = cfg or load_config()
    if atr_multiplier_override is not None:
        multiplier = float(atr_multiplier_override)
    else:
        multiplier = resolve_atr_multiplier(symbol, direction, cfg)
    raw_distance = multiplier * atr
    floor = cfg["stops"]["floor_pct"] * entry_price
    ceil_ = cfg["stops"]["ceiling_pct"] * entry_price
    distance = max(floor, min(ceil_, raw_distance))
    if direction == "long":
        return round(entry_price - distance, 2)
    elif direction == "short":
        return round(entry_price + distance, 2)
    raise ValueError(f"invalid direction '{direction}'")


def compute_take_profits(
    entry_price: float,
    stop_price: float,
    direction: str,
    cfg: dict[str, Any] | None = None,
) -> tuple[float, float]:
    """Return (TP1, TP2) at 1R and 2R from entry."""
    cfg = cfg or load_config()
    r = abs(entry_price - stop_price)
    tp1_r = cfg["take_profit"]["tp1_r_multiple"]
    tp2_r = cfg["take_profit"]["tp2_r_multiple"]
    if direction == "long":
        return round(entry_price + tp1_r * r, 2), round(entry_price + tp2_r * r, 2)
    elif direction == "short":
        return round(entry_price - tp1_r * r, 2), round(entry_price - tp2_r * r, 2)
    raise ValueError(f"invalid direction '{direction}'")


# ---------------------------------------------------------------------------
# Portfolio-level validation
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    allowed: bool
    reasons: list[str] = field(default_factory=list)

    def block(self, reason: str) -> None:
        self.allowed = False
        self.reasons.append(reason)


def _exposure_breakdown(positions: list[dict[str, Any]], equity: float) -> dict[str, float]:
    """Compute long/short/net exposure as fractions of equity."""
    long_dollars = 0.0
    short_dollars = 0.0
    for p in positions:
        market_value = float(p.get("market_value", 0))
        if market_value >= 0:
            long_dollars += market_value
        else:
            short_dollars += abs(market_value)
    return {
        "long_pct": long_dollars / equity if equity else 0.0,
        "short_pct": short_dollars / equity if equity else 0.0,
        "net_pct": (long_dollars - short_dollars) / equity if equity else 0.0,
    }


def _sector_exposure(
    positions: list[dict[str, Any]],
    equity: float,
    sector_map: dict[str, str],
) -> dict[str, float]:
    sectors: dict[str, float] = {}
    for p in positions:
        symbol = p.get("symbol", "")
        sector = sector_map.get(symbol, "unknown")
        sectors[sector] = sectors.get(sector, 0.0) + abs(float(p.get("market_value", 0)))
    return {k: v / equity for k, v in sectors.items()} if equity else {}


def validate_new_position(
    symbol: str,
    direction: str,
    sizing: SizingResult,
    positions: list[dict[str, Any]],
    equity: float,
    cfg: dict[str, Any] | None = None,
) -> ValidationResult:
    """Apply portfolio-level caps. Returns allowed=False with reasons if any cap
    would be breached by adding this position.
    """
    cfg = cfg or load_config()
    p_cfg = cfg["portfolio"]
    sector_map: dict[str, str] = cfg.get("sectors", {})
    result = ValidationResult(allowed=True, reasons=[])

    if sizing.qty <= 0:
        result.block("sizing produced qty <= 0")
        return result

    # Per-ticker long-only enforcement.
    overrides = get_ticker_overrides(symbol, cfg)
    if overrides.get("long_only", False) and direction == "short":
        result.block(f"{symbol} is configured long_only; short rejected")
        return result

    # Don't double-up on an existing position in same direction.
    for p in positions:
        if p.get("symbol") == symbol:
            existing_side = "long" if float(p.get("qty", 0)) > 0 else "short"
            if existing_side == direction:
                result.block(f"already {existing_side} {symbol}; no add-on (no pyramiding / no averaging)")

    # Concurrent positions cap.
    if len(positions) >= p_cfg["max_concurrent_positions"]:
        result.block(
            f"max_concurrent_positions {p_cfg['max_concurrent_positions']} reached"
        )

    # Project exposure if this trade fills.
    new_dollar = sizing.dollar_size if direction == "long" else -sizing.dollar_size
    projected = list(positions) + [{"symbol": symbol, "market_value": new_dollar}]
    exp = _exposure_breakdown(projected, equity)

    if exp["long_pct"] > p_cfg["max_long_exposure_pct"] + 1e-9:
        result.block(
            f"long exposure {exp['long_pct']:.1%} > cap {p_cfg['max_long_exposure_pct']:.0%}"
        )
    if exp["short_pct"] > p_cfg["max_short_exposure_pct"] + 1e-9:
        result.block(
            f"short exposure {exp['short_pct']:.1%} > cap {p_cfg['max_short_exposure_pct']:.0%}"
        )
    if abs(exp["net_pct"]) > p_cfg["max_net_exposure_pct"] + 1e-9:
        result.block(
            f"|net exposure| {abs(exp['net_pct']):.1%} > cap {p_cfg['max_net_exposure_pct']:.0%}"
        )

    # Sector concentration.
    sec_exp = _sector_exposure(projected, equity, sector_map)
    sector_for_symbol = sector_map.get(symbol, "unknown")
    if sec_exp.get(sector_for_symbol, 0.0) > p_cfg["max_sector_concentration_pct"] + 1e-9:
        result.block(
            f"sector '{sector_for_symbol}' concentration "
            f"{sec_exp[sector_for_symbol]:.1%} > cap "
            f"{p_cfg['max_sector_concentration_pct']:.0%}"
        )

    return result


# ---------------------------------------------------------------------------
# Pre-trade filters (HTB, earnings, liquidity, spread)
# ---------------------------------------------------------------------------

@dataclass
class FilterResult:
    allowed: bool
    reasons: list[str] = field(default_factory=list)


def validate_pre_trade_filters(
    symbol: str,
    direction: str,
    is_htb: bool,
    earnings_within_blackout: bool,
    avg_daily_volume: float | None,
    spread_pct: float | None,
    cfg: dict[str, Any] | None = None,
) -> FilterResult:
    cfg = cfg or load_config()
    f_cfg = cfg["filters"]
    result = FilterResult(allowed=True, reasons=[])

    if direction == "short" and is_htb and f_cfg["hard_to_borrow_blocks_short"]:
        result.allowed = False
        result.reasons.append(f"{symbol} hard-to-borrow; short blocked")

    if earnings_within_blackout:
        result.allowed = False
        result.reasons.append(
            f"{symbol} within {f_cfg['earnings_blackout_hours']}h earnings blackout"
        )

    if avg_daily_volume is not None and avg_daily_volume < f_cfg["min_avg_daily_volume_shares"]:
        result.allowed = False
        result.reasons.append(
            f"{symbol} avg daily volume {avg_daily_volume:,.0f} < floor "
            f"{f_cfg['min_avg_daily_volume_shares']:,}"
        )

    if spread_pct is not None and spread_pct > f_cfg["max_spread_pct"]:
        result.allowed = False
        result.reasons.append(
            f"{symbol} spread {spread_pct:.4%} > cap {f_cfg['max_spread_pct']:.4%}"
        )

    return result


# ---------------------------------------------------------------------------
# Account-level kill switches
# ---------------------------------------------------------------------------

@dataclass
class KillSwitchResult:
    halt_new_orders: bool
    reduce_size_factor: float          # 1.0 = full size; 0.5 = half size
    reasons: list[str] = field(default_factory=list)


def evaluate_kill_switches(
    equity: float,
    daily_pnl_pct: float,
    weekly_pnl_pct: float,
    vix: float | None,
    alpaca_failure_minutes: float = 0.0,
    cfg: dict[str, Any] | None = None,
) -> KillSwitchResult:
    """Return halt/reduce decisions based on equity drawdown, P&L caps, VIX, and API health."""
    cfg = cfg or load_config()
    k = cfg["kill_switches"]
    p = cfg["portfolio"]
    start = k["starting_balance_usd"]
    halt = False
    factor = 1.0
    reasons: list[str] = []

    equity_ratio = equity / start if start else 1.0

    if equity_ratio < k["halt_threshold_pct"]:
        halt = True
        reasons.append(
            f"equity {equity_ratio:.1%} of start < halt threshold "
            f"{k['halt_threshold_pct']:.0%}"
        )
    elif equity_ratio < k["reduce_size_threshold_pct"]:
        factor = min(factor, k["reduce_size_factor"])
        reasons.append(
            f"equity {equity_ratio:.1%} of start < reduce threshold "
            f"{k['reduce_size_threshold_pct']:.0%}; sizes scaled by "
            f"{k['reduce_size_factor']:.0%}"
        )

    if daily_pnl_pct <= -p["daily_loss_cap_pct"]:
        halt = True
        reasons.append(
            f"daily P&L {daily_pnl_pct:.1%} hit cap -{p['daily_loss_cap_pct']:.0%}"
        )
    if weekly_pnl_pct <= -p["weekly_loss_cap_pct"]:
        halt = True
        reasons.append(
            f"weekly P&L {weekly_pnl_pct:.1%} hit cap -{p['weekly_loss_cap_pct']:.0%}"
        )

    if vix is not None and vix > k["vix_high_threshold"]:
        reasons.append(
            f"VIX {vix:.1f} > {k['vix_high_threshold']}; sizes capped at "
            f"{k['vix_high_max_position_pct']:.0%} (handled in size_position)"
        )

    if alpaca_failure_minutes >= k["alpaca_failure_minutes"]:
        halt = True
        reasons.append(
            f"Alpaca API down {alpaca_failure_minutes:.1f}min >= "
            f"{k['alpaca_failure_minutes']}min threshold"
        )

    return KillSwitchResult(halt_new_orders=halt, reduce_size_factor=factor, reasons=reasons)


# ---------------------------------------------------------------------------
# Macro overlays (same-day cross-asset filters via ETF proxies)
# ---------------------------------------------------------------------------

@dataclass
class MacroResult:
    blocked: bool = False
    downgrade_to_medium: bool = False
    reasons: list[str] = field(default_factory=list)


def evaluate_macro_overlays(
    symbol: str,
    direction: str,
    macro_state: dict[str, Any],
    cfg: dict[str, Any] | None = None,
) -> MacroResult:
    """Apply macro overlays from config.macro_overlays.rules to a candidate.

    `macro_state` is the dict returned by alpaca_client.get_macro_state — keyed
    by proxy alias (wti, copper, rates_10y, spy). Each value has change_pct,
    below_20dma, etc. Missing data is treated as "skip the check" (not block).

    Returns MacroResult with blocked / downgrade_to_medium flags and reasons.
    """
    cfg = cfg or load_config()
    overlays = cfg.get("macro_overlays") or {}
    if not overlays.get("enabled", True):
        return MacroResult()

    result = MacroResult()
    rules = overlays.get("rules", []) or []

    for rule in rules:
        # Direction filter.
        if rule.get("direction") and rule["direction"] != direction:
            continue
        # Symbol filter (single, list, or 'ALL').
        symbols = rule.get("symbols") if "symbols" in rule else rule.get("symbol")
        if isinstance(symbols, str):
            if symbols != "ALL" and symbols != symbol:
                continue
        elif isinstance(symbols, list):
            if symbol not in symbols:
                continue
        else:
            # No symbol filter? Skip rule.
            continue

        proxy_key = rule.get("proxy")
        proxy_state = macro_state.get(proxy_key) if proxy_key else None
        if not proxy_state:
            continue  # data unavailable; skip this rule rather than block
        if proxy_state.get("available") is False:
            # Proxy explicitly unavailable (e.g. VIX_UNAVAILABLE / TNX_UNAVAILABLE).
            # Skip rules that depend on it rather than blocking conservatively —
            # the strategy expects routine to record this and continue.
            continue

        # Two threshold modes, mutually exclusive per rule:
        #   bps_change_threshold     -> use proxy_state["bps_change_intraday"] (^TNX)
        #   proxy_change_threshold_pct -> use proxy_state["change_pct"] (ETFs / ^VIX)
        bps_threshold = rule.get("bps_change_threshold")
        pct_threshold = rule.get("proxy_change_threshold_pct")
        below_20dma_required = rule.get("proxy_below_20dma", False)

        fired = False
        observed_str = ""
        threshold_str = ""

        if bps_threshold is not None:
            bps = proxy_state.get("bps_change_intraday")
            if bps is None:
                continue
            # Positive threshold (e.g. 5) => fire when bps >= threshold (yields rising fast).
            # Negative threshold => fire when bps <= threshold (yields dropping fast).
            if bps_threshold > 0 and bps >= bps_threshold:
                fired = True
            elif bps_threshold < 0 and bps <= bps_threshold:
                fired = True
            elif bps_threshold == 0:
                fired = True
            observed_str = f"bps={bps:+.2f}"
            threshold_str = f"bps_threshold={bps_threshold}"
        elif pct_threshold is not None:
            change = proxy_state.get("change_pct")
            if change is None:
                continue
            if pct_threshold < 0 and change <= pct_threshold:
                fired = True
            elif pct_threshold > 0 and change >= pct_threshold:
                fired = True
            elif pct_threshold == 0:
                fired = True
            observed_str = f"change={change:+.2%}"
            threshold_str = f"pct_threshold={pct_threshold}"

        if below_20dma_required and not proxy_state.get("below_20dma", False):
            fired = False  # AND condition: need both threshold + below 20DMA

        if not fired:
            continue

        action = rule.get("action", "block")
        rule_id = rule.get("id", proxy_key)
        reason = (
            f"macro rule '{rule_id}': proxy={proxy_state.get('symbol')} "
            f"{observed_str} {threshold_str} -> {action}"
        )
        if action == "block":
            result.blocked = True
        elif action == "downgrade_to_medium":
            result.downgrade_to_medium = True
        result.reasons.append(reason)

    return result


# ---------------------------------------------------------------------------
# Event window (earnings, post-earnings, FDA, macro events)
# ---------------------------------------------------------------------------

@dataclass
class EventWindowResult:
    allowed: bool = True
    size_factor: float = 1.0
    atr_multiplier_override: float | None = None
    challenger_must_address: bool = False
    reasons: list[str] = field(default_factory=list)


def _hours_until(iso_timestamp: str, now: datetime | None = None) -> float | None:
    """Return hours until iso_timestamp from `now` (UTC). Negative if past."""
    try:
        when = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return (when - now).total_seconds() / 3600.0


def evaluate_event_window(
    symbol: str,
    direction: str,
    today_iso: str | None = None,
    earnings_schedule: dict[str, str] | None = None,
    recent_earnings: dict[str, str] | None = None,
    fda_schedule: dict[str, list[str]] | None = None,
    macro_events_today: list[str] | None = None,
    cfg: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> EventWindowResult:
    """Evaluate all event-window constraints for a candidate trade.

    Inputs (all optional; routine populates from research):
      earnings_schedule: {symbol: ISO8601 of next earnings}
      recent_earnings:   {symbol: ISO8601 of MOST RECENT earnings — used for day+1 logic}
      fda_schedule:      {symbol: [ISO8601 of upcoming FDA events]}
      macro_events_today: list of event labels active today (e.g. ["FOMC"])

    Returns EventWindowResult with allowed/size/atr_override and human-readable reasons.
    """
    cfg = cfg or load_config()
    result = EventWindowResult()
    now = now or datetime.now(timezone.utc)

    # 1) Macro blackout day.
    mb_cfg = cfg.get("macro_event_blackout") or {}
    if macro_events_today and mb_cfg.get("block_new_entries", True):
        watched = set(mb_cfg.get("events", []))
        active = [e for e in macro_events_today if e in watched]
        if active:
            result.allowed = False
            result.reasons.append(f"macro blackout: {', '.join(active)}")
            return result

    # 2) Earnings blackout (per-ticker / per-direction).
    blackout_hours = resolve_earnings_blackout_hours(symbol, direction, cfg)
    if earnings_schedule and symbol in earnings_schedule:
        h = _hours_until(earnings_schedule[symbol], now=now)
        if h is not None and 0 <= h <= blackout_hours:
            result.allowed = False
            result.reasons.append(
                f"{symbol} within {h:.1f}h of earnings (blackout {blackout_hours}h)"
            )
            return result

    # 3) FDA blackout / window per ticker.
    fda_cfg = (cfg.get("fda_blackout") or {}).get(symbol)
    if fda_cfg and fda_schedule and symbol in fda_schedule:
        before_h = float(fda_cfg.get("blackout_hours_before", 0))
        after_h = float(fda_cfg.get("blackout_hours_after", 0))
        yellow_days = float(fda_cfg.get("yellow_flag_days_before", 0))
        for event_iso in fda_schedule[symbol]:
            h = _hours_until(event_iso, now=now)
            if h is None:
                continue
            # Hard blackout window.
            if before_h > 0 and 0 <= h <= before_h:
                result.allowed = False
                result.reasons.append(
                    f"{symbol} within {h:.1f}h of FDA event (blackout {before_h}h before)"
                )
                return result
            if after_h > 0 and -after_h <= h < 0:
                result.allowed = False
                result.reasons.append(
                    f"{symbol} {abs(h):.1f}h post FDA event (blackout {after_h}h after)"
                )
                return result
            # Yellow-flag size cut.
            if yellow_days > 0 and 0 <= h <= yellow_days * 24:
                size_factor = float(fda_cfg.get("size_factor", 0.5))
                result.size_factor = min(result.size_factor, size_factor)
                result.reasons.append(
                    f"{symbol} within {h:.1f}h of FDA action: yellow flag, size×{size_factor}"
                )

    # 4) Post-earnings day+1 constraints.
    pe_cfg = cfg.get("post_earnings") or {}
    if recent_earnings and symbol in recent_earnings:
        h = _hours_until(recent_earnings[symbol], now=now)
        if h is not None and -24 * pe_cfg.get("window_days", 1) <= h < 0:
            result.size_factor = min(result.size_factor, float(pe_cfg.get("size_factor", 0.5)))
            result.atr_multiplier_override = float(pe_cfg.get("atr_multiplier", 1.5))
            result.challenger_must_address = bool(pe_cfg.get("challenger_must_address_reaction", True))
            result.reasons.append(
                f"{symbol} post-earnings day+1: size×{pe_cfg.get('size_factor')}, "
                f"ATR×{pe_cfg.get('atr_multiplier')}, challenger must address reaction"
            )

    return result


# ---------------------------------------------------------------------------
# Re-entry rules (caps, lockouts, direction-flip cooling)
# ---------------------------------------------------------------------------

@dataclass
class ReEntryResult:
    allowed: bool = True
    size_factor: float = 1.0
    reasons: list[str] = field(default_factory=list)
    locked_until: str | None = None


def _is_high_density(symbol: str, direction: str, cfg: dict[str, Any]) -> bool:
    re_cfg = cfg.get("re_entry") or {}
    high = (re_cfg.get("daily_caps") or {}).get("high_density") or {}
    if symbol in (high.get("tickers") or []):
        return True
    if symbol == "NVDA" and direction == "long":
        return True
    return False


def _daily_cap_for(symbol: str, direction: str, cfg: dict[str, Any]) -> int:
    re_cfg = cfg.get("re_entry") or {}
    if symbol == "NVDA":
        return int((re_cfg.get("nvda") or {}).get(f"{direction}_daily_cap", 1))
    if _is_high_density(symbol, direction, cfg):
        return int(((re_cfg.get("daily_caps") or {}).get("high_density") or {}).get("cap", 2))
    return int(((re_cfg.get("daily_caps") or {}).get("medium_density") or {}).get("cap", 1))


def _weekly_cap_for(symbol: str, direction: str, cfg: dict[str, Any]) -> int:
    re_cfg = cfg.get("re_entry") or {}
    wk = re_cfg.get("weekly_ceiling") or {}
    if symbol == "NVDA":
        return int(wk.get(f"nvda_{direction}", 3 if direction == "short" else 4))
    if _is_high_density(symbol, direction, cfg):
        return int(wk.get("high_density", 4))
    return int(wk.get("medium_density", 3))


def next_monday_open_iso(after: datetime | None = None) -> str:
    """Return ISO timestamp of next Monday 09:30 ET as UTC.

    NOTE: 09:30 ET wraps DST; we approximate using fixed UTC-4 (EDT) since the
    bot's universe is during US trading hours and this is consumed for a
    human-readable lockout-until field. Routine logic does not rely on
    second-precision here.
    """
    after = after or datetime.now(timezone.utc)
    days_ahead = (0 - after.weekday()) % 7    # Monday is 0
    if days_ahead == 0 and after.time() >= time(13, 30):  # already past Mon 09:30 ET (~13:30 UTC EDT)
        days_ahead = 7
    if days_ahead == 0:
        days_ahead = 7 if after.weekday() != 0 else 0
    target = (after + timedelta(days=days_ahead)).replace(hour=13, minute=30, second=0, microsecond=0)
    return target.isoformat()


def validate_re_entry(
    symbol: str,
    direction: str,
    today_iso: str,
    today_re_entries: list[dict[str, Any]] | None = None,
    week_re_entries: list[dict[str, Any]] | None = None,
    last_stop_out: dict[str, Any] | None = None,
    recent_net_loss_stops: list[dict[str, Any]] | None = None,
    has_distinct_new_catalyst: bool = False,
    cfg: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> ReEntryResult:
    """Validate a same-day or same-week re-entry attempt.

    Inputs (all optional; routine builds from trade_log.md):
      today_re_entries: same-symbol entries already attempted today
      week_re_entries:  same-symbol entries this calendar week
      last_stop_out:    {symbol, direction, timestamp_iso, was_net_loss} or None
      recent_net_loss_stops: list of {symbol, timestamp_iso} within lookback_sessions
      has_distinct_new_catalyst: routine sets True if direction-flip warranted

    Returns ReEntryResult with allowed/size_factor/reasons. size_factor is 0.5
    when this IS a same-day re-entry (penalty); 1.0 if no prior stop today.
    """
    cfg = cfg or load_config()
    re_cfg = cfg.get("re_entry") or {}
    result = ReEntryResult()
    now = now or datetime.now(timezone.utc)

    today_re_entries = today_re_entries or []
    week_re_entries = week_re_entries or []
    recent_net_loss_stops = recent_net_loss_stops or []

    # 1) Lockout check first — overrides all else.
    threshold = int((re_cfg.get("lockout") or {}).get("net_loss_stops_threshold", 2))
    same_symbol_losses = [s for s in recent_net_loss_stops if s.get("symbol") == symbol]
    if len(same_symbol_losses) >= threshold:
        result.allowed = False
        result.locked_until = next_monday_open_iso(after=now)
        result.reasons.append(
            f"{symbol} lockout: {len(same_symbol_losses)} net-loss stops in lookback window "
            f"(threshold {threshold}); locked until {result.locked_until}"
        )
        return result

    # 2) Daily cap (count includes prior re-entry attempts today).
    daily_cap = _daily_cap_for(symbol, direction, cfg)
    if len(today_re_entries) >= daily_cap:
        result.allowed = False
        result.reasons.append(
            f"{symbol} {direction}: daily re-entry cap {daily_cap} reached"
        )
        return result

    # 3) Weekly ceiling.
    weekly_cap = _weekly_cap_for(symbol, direction, cfg)
    if len(week_re_entries) >= weekly_cap:
        result.allowed = False
        result.reasons.append(
            f"{symbol} {direction}: weekly re-entry ceiling {weekly_cap} reached"
        )
        return result

    # 4) Direction-flip cooling period + distinct-catalyst requirement.
    if last_stop_out and last_stop_out.get("symbol") == symbol:
        prior_dir = last_stop_out.get("direction")
        if prior_dir and prior_dir != direction:
            cool_h = float((re_cfg.get("direction_flip") or {}).get("cooling_period_hours", 2))
            ts = last_stop_out.get("timestamp_iso")
            if ts:
                hours_since = -1 * (_hours_until(ts, now=now) or 0)
                if hours_since < cool_h:
                    result.allowed = False
                    result.reasons.append(
                        f"{symbol} direction flip {prior_dir}->{direction}: "
                        f"only {hours_since:.1f}h since stop-out, need >={cool_h}h"
                    )
                    return result
            requires_catalyst = bool(
                (re_cfg.get("direction_flip") or {}).get("requires_distinct_catalyst", True)
            )
            if requires_catalyst and not has_distinct_new_catalyst:
                result.allowed = False
                result.reasons.append(
                    f"{symbol} direction flip {prior_dir}->{direction}: "
                    f"distinct new catalyst required; routine flagged none"
                )
                return result

    # 5) Same-day re-entry size penalty.
    if last_stop_out and last_stop_out.get("symbol") == symbol:
        ts = last_stop_out.get("timestamp_iso", "")
        if ts.startswith(today_iso[:10]):
            result.size_factor = float(re_cfg.get("same_day_size_factor", 0.5))
            result.reasons.append(
                f"{symbol} same-day re-entry after stop-out: size×{result.size_factor}"
            )

    return result


# ---------------------------------------------------------------------------
# Exit triggers (layered cuts: 30-min invalidation / -1.5R / 0.5R-by-noon)
# ---------------------------------------------------------------------------

@dataclass
class ExitResult:
    should_exit: bool = False
    trigger_id: str = ""
    reasons: list[str] = field(default_factory=list)


def evaluate_exit_triggers(
    minutes_since_entry: float,
    atr_excursion_atrs: float,        # signed: positive = unfavourable excursion against position
    current_r_multiple: float,        # signed: -1.0 = at 1× initial risk loss; +1.0 = at TP1
    et_hour: int,                     # 0-23 in US/Eastern
    proximity_to_tp1_in_r: float,     # 0.0 = at TP1; 0.25 = within 0.25R of TP1
    cfg: dict[str, Any] | None = None,
) -> ExitResult:
    """Evaluate the 3 layered exit triggers in precedence order.

    Inputs are computed by the routine from the held position + market state:
      minutes_since_entry      — how long the position has been open
      atr_excursion_atrs       — how many ATR units the position has moved
                                 against entry (positive = unfavourable; e.g.
                                 long down 1.2× ATR -> 1.2)
      current_r_multiple       — P&L in R units (negative = loss)
      et_hour                  — current US/Eastern hour (0-23)
      proximity_to_tp1_in_r    — distance to TP1 in R units (0 if already past)

    Returns ExitResult with should_exit + trigger_id + reasons.
    """
    cfg = cfg or load_config()
    e = cfg.get("exit_triggers") or {}
    result = ExitResult()

    # 1) Setup invalidation: down >1× ATR within 30 min of entry.
    inv_minutes = float(e.get("setup_invalidation_minutes", 30))
    inv_atr_mult = float(e.get("setup_invalidation_atr_mult", 1.0))
    if minutes_since_entry <= inv_minutes and atr_excursion_atrs >= inv_atr_mult:
        result.should_exit = True
        result.trigger_id = "setup_invalidation"
        result.reasons.append(
            f"down {atr_excursion_atrs:.2f}× ATR within {minutes_since_entry:.0f}min "
            f"(threshold {inv_atr_mult}× ATR within {inv_minutes}min)"
        )
        return result

    # 2) Trade kill: at -1.5R any time intraday.
    kill_r = float(e.get("trade_kill_r_multiple", -1.5))
    if current_r_multiple <= kill_r:
        result.should_exit = True
        result.trigger_id = "trade_kill"
        result.reasons.append(
            f"position at {current_r_multiple:.2f}R (threshold {kill_r}R)"
        )
        return result

    # 3) Time discipline: by 12:00 ET, underwater >-0.5R AND not within 0.25R of TP1.
    cutoff_h = int(e.get("time_discipline_cutoff_hour_et", 12))
    r_thresh = float(e.get("time_discipline_r_threshold", -0.5))
    tp_proximity_thresh = float(e.get("time_discipline_tp1_proximity_r", 0.25))
    if et_hour >= cutoff_h and current_r_multiple <= r_thresh:
        if proximity_to_tp1_in_r > tp_proximity_thresh:
            result.should_exit = True
            result.trigger_id = "time_discipline"
            result.reasons.append(
                f"after {cutoff_h}:00 ET; underwater at {current_r_multiple:.2f}R "
                f"(threshold {r_thresh}R) and {proximity_to_tp1_in_r:.2f}R from TP1 "
                f"(>{tp_proximity_thresh}R)"
            )
            return result

    return result


# ---------------------------------------------------------------------------
# Self-test — exhaustive checks on sizing, caps, and kill switches
# ---------------------------------------------------------------------------

def _check(label: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        raise AssertionError(label)


if __name__ == "__main__":
    cfg = load_config()
    print(f"Loaded config from {CONFIG_PATH}\n")

    print("== sizing math ==")
    # NVDA long, $145 entry, $138 stop -> stop_distance = 7 / 145 = 4.83%
    # equity $100k -> risk budget = $1000 / 0.0483 = $20,705 dollar size
    # high conviction cap = 10% of equity = $10,000 -> position_cap binds
    # qty = floor(10,000 / 145) = 68
    res = size_position(100_000, 145.0, 138.0, "long", "high", cfg=cfg)
    _check("NVDA high-conv long sizing", res.qty == 68 and res.capped_by == "position_cap",
           f"qty={res.qty} capped_by={res.capped_by} pos%={res.position_pct_of_equity:.2%}")

    # Same trade, medium conviction -> max 7%, qty = floor(7000/145) = 48
    res = size_position(100_000, 145.0, 138.0, "long", "medium", cfg=cfg)
    _check("NVDA medium-conv long sizing", res.qty == 48,
           f"qty={res.qty} pos%={res.position_pct_of_equity:.2%}")

    # Hold conviction -> qty 0
    res = size_position(100_000, 145.0, 138.0, "long", "hold", cfg=cfg)
    _check("hold conviction returns qty 0", res.qty == 0)

    # Wider stop (10% raw, clamped to 8% ceiling): stop = $130.5
    # Actually we don't clamp here — caller computes via compute_stop_price.
    # Let's test that helper.
    stop = compute_stop_price(145.0, 8.0, "long", cfg=cfg)         # 2*8=16 raw, ceil = 0.08*145=11.6
    _check("compute_stop_price ceil clamp", stop == round(145.0 - 11.6, 2),
           f"stop={stop}")
    stop = compute_stop_price(145.0, 1.0, "long", cfg=cfg)         # 2*1=2, floor = 0.03*145=4.35
    _check("compute_stop_price floor clamp", stop == round(145.0 - 4.35, 2),
           f"stop={stop}")
    stop_short = compute_stop_price(145.0, 5.0, "short", cfg=cfg)  # 2*5=10
    _check("compute_stop_price short", stop_short == round(145.0 + 10.0, 2),
           f"stop={stop_short}")

    tp1, tp2 = compute_take_profits(145.0, 138.0, "long", cfg=cfg)
    _check("compute_take_profits long", tp1 == 152.0 and tp2 == 159.0,
           f"tp1={tp1} tp2={tp2}")

    # Short cap is 7% (asymmetric). Equity 100k, entry 145, stop 152 (4.83%)
    # risk budget = $20,705; short cap = 7,000 -> qty = floor(7000/145) = 48
    res = size_position(100_000, 145.0, 152.0, "short", "high", cfg=cfg)
    _check("short cap 7% binds", res.qty == 48, f"qty={res.qty}")

    # VIX > 35 caps at 5%
    res = size_position(100_000, 145.0, 138.0, "long", "high", cfg=cfg, vix=40.0)
    _check("VIX>35 caps long at 5%", res.qty == int(5000 / 145),
           f"qty={res.qty}")

    print("\n== validate_new_position ==")
    # Empty portfolio, valid sizing -> allowed
    sizing = size_position(100_000, 145.0, 138.0, "long", "high", cfg=cfg)
    val = validate_new_position("NVDA", "long", sizing, [], 100_000, cfg=cfg)
    _check("empty portfolio allows new position", val.allowed, str(val.reasons))

    # 8 positions already -> blocked
    fake = [{"symbol": f"X{i}", "market_value": 1000, "qty": 10} for i in range(8)]
    val = validate_new_position("NVDA", "long", sizing, fake, 100_000, cfg=cfg)
    _check("max concurrent positions blocks", not val.allowed, str(val.reasons))

    # Already long NVDA -> blocked from adding
    val = validate_new_position(
        "NVDA", "long", sizing,
        [{"symbol": "NVDA", "market_value": 5000, "qty": 30}],
        100_000, cfg=cfg,
    )
    _check("existing long NVDA blocks add-on", not val.allowed, str(val.reasons))

    # Sector concentration: 30% tech already, adding NVDA tech blocks
    heavy_tech = [
        {"symbol": "MSFT", "market_value": 15_000, "qty": 30},
        {"symbol": "AIQ",  "market_value": 15_000, "qty": 100},
    ]
    val = validate_new_position("NVDA", "long", sizing, heavy_tech, 100_000, cfg=cfg)
    _check("sector concentration cap blocks", not val.allowed, str(val.reasons))

    print("\n== pre-trade filters ==")
    f = validate_pre_trade_filters("NVDA", "short", is_htb=True,
                                   earnings_within_blackout=False,
                                   avg_daily_volume=10_000_000, spread_pct=0.0005, cfg=cfg)
    _check("HTB blocks short", not f.allowed, str(f.reasons))

    f = validate_pre_trade_filters("NVDA", "long", is_htb=True,
                                   earnings_within_blackout=False,
                                   avg_daily_volume=10_000_000, spread_pct=0.0005, cfg=cfg)
    _check("HTB does NOT block long", f.allowed, str(f.reasons))

    f = validate_pre_trade_filters("NVDA", "long", is_htb=False,
                                   earnings_within_blackout=True,
                                   avg_daily_volume=10_000_000, spread_pct=0.0005, cfg=cfg)
    _check("earnings blackout blocks", not f.allowed, str(f.reasons))

    f = validate_pre_trade_filters("NVDA", "long", is_htb=False,
                                   earnings_within_blackout=False,
                                   avg_daily_volume=1_000_000, spread_pct=0.0005, cfg=cfg)
    _check("low volume blocks", not f.allowed, str(f.reasons))

    f = validate_pre_trade_filters("NVDA", "long", is_htb=False,
                                   earnings_within_blackout=False,
                                   avg_daily_volume=10_000_000, spread_pct=0.005, cfg=cfg)
    _check("wide spread blocks", not f.allowed, str(f.reasons))

    print("\n== kill switches ==")
    k = evaluate_kill_switches(100_000, 0.0, 0.0, vix=20.0, cfg=cfg)
    _check("baseline: no halt, full size", not k.halt_new_orders and k.reduce_size_factor == 1.0, str(k.reasons))

    k = evaluate_kill_switches(94_000, 0.0, 0.0, vix=20.0, cfg=cfg)
    _check("equity 94% triggers half size", not k.halt_new_orders and k.reduce_size_factor == 0.5, str(k.reasons))

    k = evaluate_kill_switches(89_000, 0.0, 0.0, vix=20.0, cfg=cfg)
    _check("equity 89% triggers halt", k.halt_new_orders, str(k.reasons))

    k = evaluate_kill_switches(100_000, -0.05, 0.0, vix=20.0, cfg=cfg)
    _check("daily loss cap halts", k.halt_new_orders, str(k.reasons))

    k = evaluate_kill_switches(100_000, 0.0, -0.10, vix=20.0, cfg=cfg)
    _check("weekly loss cap halts", k.halt_new_orders, str(k.reasons))

    k = evaluate_kill_switches(100_000, 0.0, 0.0, vix=20.0, alpaca_failure_minutes=6, cfg=cfg)
    _check("alpaca outage >5min halts", k.halt_new_orders, str(k.reasons))

    print("\n== ticker overrides ==")
    _check("MSFT long_only blocks short",
           not validate_new_position("MSFT", "short",
                                     size_position(100_000, 400, 380, "short", "high", cfg=cfg, symbol="MSFT"),
                                     [], 100_000, cfg=cfg).allowed)
    _check("LMT max_conviction clamps high->medium",
           resolve_max_conviction("LMT", "high", cfg=cfg) == "medium")
    _check("TSLA long ATR multiplier resolves to 1.5",
           resolve_atr_multiplier("TSLA", "long", cfg=cfg) == 1.5)
    _check("NVDA long ATR multiplier 2.0",
           resolve_atr_multiplier("NVDA", "long", cfg=cfg) == 2.0)
    _check("NVDA short ATR multiplier 1.5",
           resolve_atr_multiplier("NVDA", "short", cfg=cfg) == 1.5)
    _check("LLY earnings blackout 168h (long)",
           resolve_earnings_blackout_hours("LLY", "long", cfg=cfg) == 168)
    _check("NVDA short earnings blackout 336h (14d)",
           resolve_earnings_blackout_hours("NVDA", "short", cfg=cfg) == 336)
    _check("MSFT earnings blackout falls back to global 48h",
           resolve_earnings_blackout_hours("MSFT", "long", cfg=cfg) == 48)

    # Per-ticker max_short_pct: NVDA short capped at 5% even with high conviction.
    nvda_short = size_position(100_000, 197.0, 207.0, "short", "high", cfg=cfg, symbol="NVDA")
    _check("NVDA short capped at 5% via override",
           nvda_short.position_pct_of_equity <= 0.05 + 1e-6,
           f"pos%={nvda_short.position_pct_of_equity:.2%}")

    # TSLA max_conviction=medium: even if requested high, sizing uses medium tier.
    tsla = size_position(100_000, 250.0, 240.0, "long", "high", cfg=cfg, symbol="TSLA")
    _check("TSLA long_high requested -> medium tier (max 7%)",
           tsla.position_pct_of_equity <= 0.07 + 1e-6,
           f"pos%={tsla.position_pct_of_equity:.2%}")

    # Stop computation honours TSLA's 1.5× ATR.
    tsla_stop = compute_stop_price(250.0, 5.0, "long", cfg=cfg, symbol="TSLA")
    # 1.5*5 = 7.5 raw; floor 0.03*250=7.5; ceil 0.08*250=20 -> 7.5
    _check("TSLA stop uses 1.5x ATR override", tsla_stop == round(250.0 - 7.5, 2),
           f"stop={tsla_stop}")

    # ATR multiplier override (post-earnings 1.5×).
    pe_stop = compute_stop_price(100.0, 4.0, "long", cfg=cfg, atr_multiplier_override=1.5)
    _check("Post-earnings ATR override", pe_stop == round(100.0 - 6.0, 2),
           f"stop={pe_stop}")

    print("\n== scoring ==")
    _check("long score 6 -> 10%", score_to_position_pct("long", 6, cfg) == 0.10)
    _check("long score 5 -> 8%",  score_to_position_pct("long", 5, cfg) == 0.08)
    _check("long score 4 -> 6%",  score_to_position_pct("long", 4, cfg) == 0.06)
    _check("long score 3 -> None (skip)", score_to_position_pct("long", 3, cfg) is None)
    _check("short score 6 -> 7%", score_to_position_pct("short", 6, cfg) == 0.07)
    _check("short score 5 -> 5%", score_to_position_pct("short", 5, cfg) == 0.05)
    _check("short score 4 -> None (skip)", score_to_position_pct("short", 4, cfg) is None)

    # Score-driven sizing.
    s = size_position(100_000, 200.0, 190.0, "long", "high", cfg=cfg, symbol="MSFT", score=5)
    # 5/6 = 8% -> $8,000 -> 40 shares
    _check("MSFT score=5 -> 40 sh ($8k)", s.qty == 40, f"qty={s.qty}")

    s = size_position(100_000, 200.0, 190.0, "long", "high", cfg=cfg, symbol="MSFT", score=3)
    _check("score below floor -> qty 0", s.qty == 0)

    print("\n== macro overlays ==")
    # New state structure: ETF proxies use change_pct; ^TNX uses bps_change_intraday;
    # ^VIX uses change_pct (and the rule set doesn't reference VIX % moves directly,
    # only absolute VIX value via scoring/kill_switches).
    macro_state = {
        "wti":      {"symbol": "USO",  "available": True, "change_pct": -0.01, "below_20dma": False},
        "copper":   {"symbol": "CPER", "available": True, "change_pct": -0.01, "below_20dma": False},
        "rates_10y":{"symbol": "^TNX", "available": True, "bps_change_intraday": 7,
                     "yield_pct": 4.5, "below_20dma": False},  # +7bps -> DTCR block fires; tech downgrade does NOT
        "spy":      {"symbol": "SPY",  "available": True, "change_pct": -0.008, "below_20dma": True},
        "vix":      {"symbol": "^VIX", "available": True, "value": 18.0, "change_pct": 0.0},
    }
    m = evaluate_macro_overlays("XOM", "long", macro_state, cfg=cfg)
    _check("XOM long blocked when WTI down >0.5%", m.blocked, str(m.reasons))

    m = evaluate_macro_overlays("XOM", "short", macro_state, cfg=cfg)
    _check("XOM short NOT blocked when WTI down (only blocked when WTI up)",
           not m.blocked, str(m.reasons))

    m = evaluate_macro_overlays("FCX", "long", macro_state, cfg=cfg)
    _check("FCX long blocked when copper down >0.5%", m.blocked, str(m.reasons))

    m = evaluate_macro_overlays("DTCR", "long", macro_state, cfg=cfg)
    # 10Y +7bps >= 5bps threshold -> block
    _check("DTCR long blocked when 10Y +7bps (>5bps threshold)", m.blocked, str(m.reasons))

    m = evaluate_macro_overlays("NVDA", "long", macro_state, cfg=cfg)
    # 10Y +7bps < 10bps tech threshold -> NO downgrade from rates rule
    # But SPY -0.8% AND below_20dma fires basket downgrade -> downgrade_to_medium
    _check("NVDA long downgrade fires (SPY rule, NOT tech-yield rule at +7bps)",
           m.downgrade_to_medium, str(m.reasons))

    # Tech-yield specifically: bump 10Y to +12bps to ensure tech rule alone fires.
    state2 = dict(macro_state)
    state2["rates_10y"] = {**macro_state["rates_10y"], "bps_change_intraday": 12}
    state2["spy"] = {**macro_state["spy"], "change_pct": 0.001, "below_20dma": False}  # remove SPY rule
    m = evaluate_macro_overlays("NVDA", "long", state2, cfg=cfg)
    _check("Tech-yield downgrade fires when 10Y +12bps (>10bps)",
           m.downgrade_to_medium and any("tech_yield_downgrade" in r for r in m.reasons),
           str(m.reasons))

    # 10Y under +5bps: DTCR not blocked.
    state3 = dict(macro_state)
    state3["rates_10y"] = {**macro_state["rates_10y"], "bps_change_intraday": 3}
    state3["spy"] = {**macro_state["spy"], "change_pct": 0.001, "below_20dma": False}
    m = evaluate_macro_overlays("DTCR", "long", state3, cfg=cfg)
    _check("DTCR NOT blocked when 10Y +3bps (under 5bps threshold)",
           not m.blocked, str(m.reasons))

    m = evaluate_macro_overlays("MSFT", "long", macro_state, cfg=cfg)
    # SPY -0.8% AND below_20dma=True -> downgrade
    _check("MSFT long downgrade via SPY broad-tape rule", m.downgrade_to_medium, str(m.reasons))

    # Unavailable proxy is skipped, not treated as block.
    state_unavail = {
        "rates_10y": {"symbol": "^TNX", "available": False, "reason": "TNX_UNAVAILABLE"},
        "spy": {"symbol": "SPY", "available": True, "change_pct": 0.001, "below_20dma": False},
    }
    m = evaluate_macro_overlays("DTCR", "long", state_unavail, cfg=cfg)
    _check("Rate-based rules skip when ^TNX unavailable (no false block)",
           not m.blocked, str(m.reasons))

    # All-clear macro state: no rules fire.
    clear = {
        "wti":      {"symbol": "USO",  "available": True, "change_pct": 0.001,  "below_20dma": False},
        "copper":   {"symbol": "CPER", "available": True, "change_pct": 0.001,  "below_20dma": False},
        "rates_10y":{"symbol": "^TNX", "available": True, "bps_change_intraday": 0,
                     "yield_pct": 4.4, "below_20dma": False},
        "spy":      {"symbol": "SPY",  "available": True, "change_pct": 0.001,  "below_20dma": False},
        "vix":      {"symbol": "^VIX", "available": True, "value": 17.0, "change_pct": 0.0},
    }
    m = evaluate_macro_overlays("XOM", "long", clear, cfg=cfg)
    _check("clear macro state -> no block", not m.blocked and not m.downgrade_to_medium,
           str(m.reasons))

    print("\n== event window ==")
    now = datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc)

    # Macro blackout day blocks new entry.
    ev = evaluate_event_window("NVDA", "long", macro_events_today=["FOMC"], cfg=cfg, now=now)
    _check("FOMC macro blackout blocks entry", not ev.allowed, str(ev.reasons))

    # Earnings within 48h blocks (global rule).
    soon_iso = (now + timedelta(hours=24)).isoformat()
    ev = evaluate_event_window("MSFT", "long", earnings_schedule={"MSFT": soon_iso},
                               cfg=cfg, now=now)
    _check("MSFT 24h before earnings blocked (48h global)", not ev.allowed, str(ev.reasons))

    # LLY: 7-day blackout. 100h before earnings still inside 168h window.
    soon_iso = (now + timedelta(hours=100)).isoformat()
    ev = evaluate_event_window("LLY", "long", earnings_schedule={"LLY": soon_iso},
                               cfg=cfg, now=now)
    _check("LLY 100h before earnings blocked (168h override)", not ev.allowed, str(ev.reasons))

    # Earnings 50h away: blocks MSFT (48h global)? NO — 50 > 48. So allowed.
    soon_iso = (now + timedelta(hours=50)).isoformat()
    ev = evaluate_event_window("MSFT", "long", earnings_schedule={"MSFT": soon_iso},
                               cfg=cfg, now=now)
    _check("MSFT 50h before earnings allowed", ev.allowed, str(ev.reasons))

    # Post-earnings day+1: size factor and ATR override.
    earlier_iso = (now - timedelta(hours=18)).isoformat()
    ev = evaluate_event_window("MSFT", "long", recent_earnings={"MSFT": earlier_iso},
                               cfg=cfg, now=now)
    _check("post-earnings day+1: size factor 0.5",
           ev.allowed and ev.size_factor == 0.5 and ev.atr_multiplier_override == 1.5,
           str(ev.reasons))

    # FDA blackout for LLY (48h before).
    fda_iso = (now + timedelta(hours=24)).isoformat()
    ev = evaluate_event_window("LLY", "long", fda_schedule={"LLY": [fda_iso]},
                               cfg=cfg, now=now)
    _check("LLY 24h before FDA event blocked", not ev.allowed, str(ev.reasons))

    # ISRG yellow flag (no blackout, just size cut).
    fda_iso = (now + timedelta(hours=72)).isoformat()
    ev = evaluate_event_window("ISRG", "long", fda_schedule={"ISRG": [fda_iso]},
                               cfg=cfg, now=now)
    _check("ISRG yellow flag: allowed but size_factor=0.5",
           ev.allowed and ev.size_factor == 0.5, str(ev.reasons))

    print("\n== re-entry rules ==")
    today_iso = "2026-05-06T00:00:00+00:00"
    base_now = datetime(2026, 5, 6, 18, 0, tzinfo=timezone.utc)

    # No prior history -> allowed full size.
    r = validate_re_entry("TSLA", "long", today_iso, cfg=cfg, now=base_now)
    _check("no prior stops -> allowed full size", r.allowed and r.size_factor == 1.0)

    # Same-day stop-out -> 50% size penalty.
    last = {"symbol": "TSLA", "direction": "long",
            "timestamp_iso": "2026-05-06T15:00:00+00:00", "was_net_loss": True}
    r = validate_re_entry("TSLA", "long", today_iso, last_stop_out=last, cfg=cfg, now=base_now)
    _check("same-day stop-out -> 50% size penalty",
           r.allowed and r.size_factor == 0.5, str(r.reasons))

    # Daily cap reached for medium-density (MSFT cap=1).
    r = validate_re_entry("MSFT", "long", today_iso,
                          today_re_entries=[{"symbol": "MSFT"}], cfg=cfg, now=base_now)
    _check("MSFT medium-density daily cap=1 reached", not r.allowed, str(r.reasons))

    # High-density TSLA cap=2.
    r = validate_re_entry("TSLA", "long", today_iso,
                          today_re_entries=[{"symbol": "TSLA"}, {"symbol": "TSLA"}],
                          cfg=cfg, now=base_now)
    _check("TSLA high-density daily cap=2 reached", not r.allowed, str(r.reasons))

    # Direction flip < 2h cooling.
    last = {"symbol": "TSLA", "direction": "long",
            "timestamp_iso": (base_now - timedelta(hours=1)).isoformat(),
            "was_net_loss": True}
    r = validate_re_entry("TSLA", "short", today_iso, last_stop_out=last,
                          has_distinct_new_catalyst=True, cfg=cfg, now=base_now)
    _check("direction flip <2h blocked", not r.allowed, str(r.reasons))

    # Direction flip >=2h, no distinct catalyst.
    last = {"symbol": "TSLA", "direction": "long",
            "timestamp_iso": (base_now - timedelta(hours=3)).isoformat(),
            "was_net_loss": True}
    r = validate_re_entry("TSLA", "short", today_iso, last_stop_out=last,
                          has_distinct_new_catalyst=False, cfg=cfg, now=base_now)
    _check("direction flip without distinct catalyst blocked", not r.allowed, str(r.reasons))

    # Direction flip with cooling + catalyst -> allowed.
    r = validate_re_entry("TSLA", "short", today_iso, last_stop_out=last,
                          has_distinct_new_catalyst=True, cfg=cfg, now=base_now)
    _check("direction flip with cooling+catalyst allowed", r.allowed, str(r.reasons))

    # Lockout: 2 net-loss stops in lookback -> locked until next Mon.
    losses = [{"symbol": "TSLA", "timestamp_iso": "2026-05-05T16:00:00+00:00"},
              {"symbol": "TSLA", "timestamp_iso": "2026-05-06T15:00:00+00:00"}]
    r = validate_re_entry("TSLA", "long", today_iso,
                          recent_net_loss_stops=losses, cfg=cfg, now=base_now)
    _check("lockout after 2 net-loss stops", not r.allowed and r.locked_until is not None,
           str(r.reasons))

    print("\n== exit triggers ==")
    # Setup invalidation: down 1.2× ATR within 20 min.
    e = evaluate_exit_triggers(minutes_since_entry=20, atr_excursion_atrs=1.2,
                               current_r_multiple=-0.4, et_hour=10,
                               proximity_to_tp1_in_r=1.0, cfg=cfg)
    _check("setup_invalidation fires", e.should_exit and e.trigger_id == "setup_invalidation")

    # 30-min window passed: invalidation should NOT fire even if down 1.2 ATR.
    e = evaluate_exit_triggers(minutes_since_entry=45, atr_excursion_atrs=1.2,
                               current_r_multiple=-0.4, et_hour=10,
                               proximity_to_tp1_in_r=1.0, cfg=cfg)
    _check("setup_invalidation expires after 30 min", not e.should_exit)

    # Trade kill at -1.5R.
    e = evaluate_exit_triggers(minutes_since_entry=120, atr_excursion_atrs=1.5,
                               current_r_multiple=-1.5, et_hour=11,
                               proximity_to_tp1_in_r=1.0, cfg=cfg)
    _check("trade_kill fires at -1.5R", e.should_exit and e.trigger_id == "trade_kill")

    # Time discipline at 12 ET, -0.6R, far from TP1.
    e = evaluate_exit_triggers(minutes_since_entry=180, atr_excursion_atrs=0.6,
                               current_r_multiple=-0.6, et_hour=12,
                               proximity_to_tp1_in_r=1.0, cfg=cfg)
    _check("time_discipline fires at 12 ET / -0.6R / far from TP1",
           e.should_exit and e.trigger_id == "time_discipline")

    # Time discipline DOESN'T fire if within 0.25R of TP1.
    e = evaluate_exit_triggers(minutes_since_entry=180, atr_excursion_atrs=0.6,
                               current_r_multiple=-0.6, et_hour=12,
                               proximity_to_tp1_in_r=0.2, cfg=cfg)
    _check("time_discipline holds back if near TP1", not e.should_exit)

    # No trigger for healthy trade.
    e = evaluate_exit_triggers(minutes_since_entry=120, atr_excursion_atrs=0.0,
                               current_r_multiple=0.5, et_hour=11,
                               proximity_to_tp1_in_r=0.5, cfg=cfg)
    _check("healthy trade -> no exit", not e.should_exit)

    print("\nAll risk_check self-tests passed ✅")
