"""A stand-in for a model that answers from samples/ground_truth.json.

Not extraction: it recognises the bills shipped in samples/ and answers with
their expected values, instantly. Any other bill gets an empty answer and
stays unparsed. Useful to demo or work on everything around the model
(redaction, guard, validation, review) without waiting for a real one.

It sits behind the same interface as a real model: it only sees the
pseudonymised text, and its answer goes through `bills.ai.validate` like
any other.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from functools import lru_cache
from itertools import permutations

from django.conf import settings

from .client import LLMClient, LLMRequest, TextPart

PARSER_NAME = "ground_truth"
NOTE = "Read from samples/ground_truth.json, not by a model."


@lru_cache(maxsize=1)
def samples() -> list[dict]:
    path = settings.SAMPLES_DIR / "ground_truth.json"
    return json.loads(path.read_text(encoding="utf-8"))["samples"]


def _cost_components(cost: Decimal, numbers: set[Decimal]) -> list[dict] | None:
    """[] when the cost is printed, else the two printed amounts it is the difference of."""
    if cost in numbers:
        return []
    for total, credit in permutations(numbers, 2):
        if total - credit == cost:  # e.g. a subtotal minus a rebate
            return [
                {"label": "Subtotal", "amount": float(total)},
                {"label": "Credit", "amount": -float(credit)},
            ]
    return None


def answer_for(text: str) -> str:
    """The expected values of the sample `text` comes from, as a model would answer."""
    from .validate import printed_dates, printed_numbers  # imports the parsing package

    numbers, dates = printed_numbers(text), printed_dates(text)
    for sample in samples():
        entry, bill = sample["expected"]["entry"], sample["expected"]["bill"]
        start, end = (date.fromisoformat(entry[f"{k}_billing_period"]) for k in ("start", "end"))
        consumption, cost = Decimal(entry["consumption"]), Decimal(entry["bill_cost"])
        components = _cost_components(cost, numbers)
        if start not in dates or consumption not in numbers or components is None:
            continue
        return json.dumps({
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "days_printed": (end - start).days,
            "consumption": float(consumption),
            "consumption_unit": bill["consumption_unit"],
            "billed_power_kw": entry["billed_power"] and float(entry["billed_power"]),
            "cost_before_taxes": float(cost),
            "cost_components": components,
            "rate_code": bill["rate_code"],
        })
    return "{}"


class GroundTruthClient(LLMClient):
    def complete(self, request: LLMRequest) -> str:
        return answer_for("\n".join(p.text for p in request.parts if isinstance(p, TextPart)))
