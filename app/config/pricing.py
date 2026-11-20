"""
Cost estimation table.
Prices are APPROXIMATE ESTIMATES only — not guaranteed billing amounts.
Source: Publicly available pricing pages, October 2026.
Always label cost outputs as estimates in the UI.
"""
from __future__ import annotations

PRICING_TABLE: dict[str, dict] = {
    "gemini-1.5-flash": {
        "input_per_million_usd": 0.075,
        "output_per_million_usd": 0.30,
        "note": "Google Gemini 1.5 Flash, Oct 2026 estimate",
    },
    "gemini-1.5-pro": {
        "input_per_million_usd": 1.25,
        "output_per_million_usd": 5.00,
        "note": "Google Gemini 1.5 Pro, Oct 2026 estimate",
    },
    "llama-3.1-70b-versatile": {
        "input_per_million_usd": 0.59,
        "output_per_million_usd": 0.79,
        "note": "Groq hosted Llama 3.1 70B, Oct 2026 estimate",
    },
    "gpt-4o-mini": {
        "input_per_million_usd": 0.15,
        "output_per_million_usd": 0.60,
        "note": "OpenAI GPT-4o-mini, Oct 2026 estimate",
    },
    "all-MiniLM-L6-v2": {
        "input_per_million_usd": 0.0,
        "output_per_million_usd": 0.0,
        "note": "Local sentence-transformers model, no API cost",
    },
}


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> dict:
    """
    Return a cost estimate dict. Always marks result as an estimate.

    Args:
        model: Model identifier key (from PRICING_TABLE).
        input_tokens: Reported input token count.
        output_tokens: Reported output token count.

    Returns:
        Dict with cost fields, all labelled as estimates.
    """
    p = PRICING_TABLE.get(
        model,
        {"input_per_million_usd": 0, "output_per_million_usd": 0,
         "note": "pricing unknown — assumed zero"},
    )
    in_cost = (input_tokens / 1_000_000) * p["input_per_million_usd"]
    out_cost = (output_tokens / 1_000_000) * p["output_per_million_usd"]
    return {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_input_cost_usd": round(in_cost, 8),
        "estimated_output_cost_usd": round(out_cost, 8),
        "estimated_total_cost_usd": round(in_cost + out_cost, 8),
        "is_estimate": True,
        "pricing_note": p.get("note", "unknown"),
    }

