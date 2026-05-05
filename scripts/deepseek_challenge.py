"""DeepSeek adversarial counter-agent ("challenger" pattern).

Every proposed trade goes through this module before submission. The
challenger is asked to argue the OPPOSITE side of the thesis as forcefully
as possible. Its output is structured JSON the routine can act on:

  - bear_case_strength:   1-10 (10 = highly credible counter-argument)
  - top_risks:            list of concrete failure modes
  - missing_evidence:     what the original thesis omitted or hand-waved
  - counter_recommendation: "skip" | "reduce_size" | "tighten_stop" | "proceed"
  - rationale:            short paragraph

If the challenger times out (>30s) or returns malformed JSON, the routine
proceeds with the original thesis but flags the decision as 'unilateral'.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
TIMEOUT_S = 30
_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")


@dataclass
class ChallengeResult:
    available: bool
    bear_case_strength: int            # 1-10; 0 if unavailable
    top_risks: list[str]
    missing_evidence: list[str]
    counter_recommendation: str        # skip | reduce_size | tighten_stop | proceed
    rationale: str
    raw_response: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_SYSTEM_PROMPT = """You are an adversarial trade challenger. Your sole job is to find the strongest possible counter-argument to a proposed trade thesis. You are NOT a balanced analyst — you must steelman the OPPOSITE side.

You will receive a trade proposal containing: ticker, direction (long or short), entry price, target (take-profit), stop, conviction tier, and a short rationale.

Reply with ONLY a single JSON object — no prose, no markdown, no code fences. The JSON object must have these exact keys:

{
  "bear_case_strength": <integer 1-10, where 10 means the counter-case is overwhelming>,
  "top_risks": [<3 to 5 short concrete failure modes for the trade as proposed>],
  "missing_evidence": [<2 to 4 things the proposer should have addressed but didn't>],
  "counter_recommendation": <one of "skip" | "reduce_size" | "tighten_stop" | "proceed">,
  "rationale": <one short paragraph, max 4 sentences, summarising why your counter-recommendation>
}

counter_recommendation guidance:
  - "skip" if bear_case_strength >= 8
  - "reduce_size" if bear_case_strength 6-7
  - "tighten_stop" if bear_case_strength 4-5
  - "proceed" if bear_case_strength <= 3

Be rigorous. If the thesis is genuinely strong, return a low strength score honestly — do not fabricate weakness."""


def _extract_json(text: str) -> dict[str, Any] | None:
    """Try direct json.loads; if that fails, find the outermost {...} block."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _unavailable(reason: str, raw: str = "") -> ChallengeResult:
    return ChallengeResult(
        available=False,
        bear_case_strength=0,
        top_risks=[],
        missing_evidence=[],
        counter_recommendation="proceed",  # caller flags 'unilateral'; we don't block
        rationale=f"challenger unavailable: {reason}",
        raw_response=raw,
    )


def challenge(
    ticker: str,
    direction: str,            # "long" or "short"
    entry: float,
    target: float,
    stop: float,
    conviction: str,           # "high" | "medium"
    rationale: str,
) -> ChallengeResult:
    """Submit the thesis to DeepSeek; return a ChallengeResult."""
    if not _API_KEY:
        return _unavailable("DEEPSEEK_API_KEY not set")

    proposal = (
        f"Ticker: {ticker}\n"
        f"Direction: {direction}\n"
        f"Entry: ${entry:.2f}\n"
        f"Target (TP): ${target:.2f}\n"
        f"Stop: ${stop:.2f}\n"
        f"Conviction tier: {conviction}\n"
        f"Rationale: {rationale}"
    )

    body = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": proposal},
        ],
        "temperature": 0.3,
        "max_tokens": 600,
        "response_format": {"type": "json_object"},
    }

    try:
        resp = requests.post(
            DEEPSEEK_API_URL,
            headers={
                "Authorization": f"Bearer {_API_KEY}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=TIMEOUT_S,
        )
    except requests.Timeout:
        return _unavailable("timeout (>30s)")
    except requests.RequestException as exc:
        return _unavailable(f"request error: {exc}")

    if not resp.ok:
        return _unavailable(f"http {resp.status_code}", raw=resp.text[:400])

    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as exc:
        return _unavailable(f"unexpected response shape: {exc}", raw=resp.text[:400])

    parsed = _extract_json(content)
    if parsed is None:
        return _unavailable("malformed JSON in response", raw=content[:400])

    try:
        return ChallengeResult(
            available=True,
            bear_case_strength=int(parsed.get("bear_case_strength", 0)),
            top_risks=[str(x) for x in parsed.get("top_risks", [])],
            missing_evidence=[str(x) for x in parsed.get("missing_evidence", [])],
            counter_recommendation=str(parsed.get("counter_recommendation", "proceed")),
            rationale=str(parsed.get("rationale", "")),
            raw_response=content,
        )
    except (TypeError, ValueError) as exc:
        return _unavailable(f"field coercion failed: {exc}", raw=content[:400])


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Running mock thesis through DeepSeek challenger...\n")
    result = challenge(
        ticker="NVDA",
        direction="long",
        entry=145.00,
        target=160.00,
        stop=138.00,
        conviction="high",
        rationale=(
            "Strong AI capex cycle, beat-and-raise pattern, channel checks suggest "
            "datacenter demand for Blackwell holding up; technicals show 50DMA support "
            "with bullish divergence on RSI."
        ),
    )
    print(f"available:              {result.available}")
    print(f"bear_case_strength:     {result.bear_case_strength}/10")
    print(f"counter_recommendation: {result.counter_recommendation}")
    print(f"top_risks:")
    for r in result.top_risks:
        print(f"  - {r}")
    print(f"missing_evidence:")
    for m in result.missing_evidence:
        print(f"  - {m}")
    print(f"rationale: {result.rationale}")
