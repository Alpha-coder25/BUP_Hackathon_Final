"""GenAI explanations: structured facts → LLM → exactly 3 sentences.

PRD F5: 3-sentence GenAI explanation on alerts/recommendations, with a
deterministic template fallback when the LLM is unavailable or misbehaves.
LLM is optional (LLM_API_KEY in .env); the platform never depends on it.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request

log = logging.getLogger(__name__)

LLM_MODEL = os.getenv("LLM_MODEL", "glm-4.6")
LLM_TIMEOUT_SECONDS = 8.0


def _facts_sentence(facts: dict) -> str:
    station = facts.get("station_id") or "the network"
    fuel = facts.get("fuel_type")
    hours = facts.get("hours_to_stockout")
    risk = facts.get("risk_before")
    parts = [f"{station}" + (f" {fuel}" if fuel else "")]
    if hours is not None:
        parts.append(f"projects stockout in {hours}h")
    if risk is not None:
        parts.append(f"risk {risk:.0%}")
    return ", ".join(parts) or "Conditions changed"


def _action_sentence(facts: dict) -> str:
    policy = facts.get("policy")
    items = facts.get("items") or []
    if items:
        first = items[0]
        more = f" (+{len(items) - 1} more)" if len(items) > 1 else ""
        return (
            f"Recommended: ship {first.get('quantity', 0):.0f} L {first.get('fuel_type', '')} "
            f"from {first.get('source_depot_id', '')} via {first.get('route_id', '')}{more}"
        )
    if policy == "heuristic":
        return "Heuristic plan generated — manual review requested"
    return "Monitor closely; no shipment recommended yet"


def template_explanation(facts: dict) -> str:
    """Deterministic fallback — always available, always 3 sentences."""
    s1 = _facts_sentence(facts)
    cause = facts.get("cause") or "recent demand and supply trends"
    s2 = f"Driven by {cause}."
    s3 = _action_sentence(facts)
    return " ".join(x if x.endswith(".") else x + "." for x in (s1, s2, s3))


def _llm_explanation(facts: dict) -> str | None:
    """Call the LLM with only the structured facts. None on any failure."""
    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        return None
    prompt = (
        "Explain this fuel supply alert to an operator in exactly 3 short sentences. "
        "Facts (JSON):\n" + json.dumps(facts, default=str)[:1200]
    )
    body = json.dumps({
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 160,
    }).encode()
    req = urllib.request.Request(
        "https://api.z.ai/api/paas/v4/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT_SECONDS) as resp:
            content = json.loads(resp.read())["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001 — fallback path, never fatal
        log.warning("LLM explanation failed (%s); using template", exc)
        return None
    sentences = [s.strip() for s in content.replace("\n", " ").split(".") if s.strip()]
    return ". ".join(sentences[:3]) + "." if sentences else None


def explain(facts: dict, use_llm: bool = True) -> dict:
    """Returns {text, source}. source: 'llm' | 'template'."""
    if use_llm:
        text = _llm_explanation(facts)
        if text:
            return {"text": text, "source": "llm"}
    return {"text": template_explanation(facts), "source": "template"}
