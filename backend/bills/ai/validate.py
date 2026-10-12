"""Don't trust the model: check its answer against the text it was given.

Every value must be *grounded*: printed somewhere in the (redacted) text the
model saw, or - for the cost only - the sum of printed amounts the model
lists. Ungrounded values are dropped, not kept "for review": a plausible
invented number is worse than an empty field, because a reviewer skims what
looks filled in. Then consistency checks (day count, date order, unit price,
taxes) add notes for the reviewer.

The result is always `needs_review`. Confidence is computed from what we
could verify, never taken from the model.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from bills.parsing.base import ParsedEntry
from bills.parsing.values import normalize_spaces
from bills.privacy.vocabulary import fold

PARSER_NAME = "model_v1"
REQUIRED = ("start_billing_period", "end_billing_period", "consumption", "bill_cost")
UNITS = {"kwh": "kWh", "m3": "m3", "m³": "m3"}
# Plausible price per unit, all taxes and fees included, CAD/USD/EUR alike.
UNIT_PRICE_RANGE = {"kWh": (Decimal("0.03"), Decimal("0.60")), "m3": (Decimal("0.15"), Decimal("3.00"))}
# GST, QST, HST (ON, Atlantic), PST/RST, France TVA (normal, reduced).
SALES_TAX_RATES = [Decimal(r) for r in ("0.05", "0.09975", "0.13", "0.15", "0.07", "0.06", "0.08", "0.20", "0.055")]
TAX_WORDS = re.compile(r"\b(tps|tvq|tvh|gst|qst|hst|pst|tva|sales tax)\b", re.I)

MONTHS = {
    "jan": 1, "janv": 1, "january": 1, "janvier": 1,
    "feb": 2, "fev": 2, "fevr": 2, "february": 2, "fevrier": 2,
    "mar": 3, "march": 3, "mars": 3,
    "apr": 4, "avr": 4, "april": 4, "avril": 4,
    "may": 5, "mai": 5,
    "jun": 6, "june": 6, "juin": 6,
    "jul": 7, "juil": 7, "july": 7, "juillet": 7,
    "aug": 8, "august": 8, "aout": 8,
    "sep": 9, "sept": 9, "september": 9, "septembre": 9,
    "oct": 10, "october": 10, "octobre": 10,
    "nov": 11, "november": 11, "novembre": 11,
    "dec": 12, "december": 12, "decembre": 12,
}


class InvalidModelOutput(ValueError):
    pass


# --- what is printed -------------------------------------------------------

NUMBER_RE = re.compile(r"\d{1,3}(?:[ ,.]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?")


COMMA_THOUSANDS_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?")   # 1,013 / 1,380.95
DOT_THOUSANDS_RE = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?")     # 1.013 / 1.380,95
DECIMAL_RE = re.compile(r"\d+(?:[.,]\d+)?")                        # 22,31 / 1.013 / 2757


def _meanings(raw: str) -> set[Decimal]:
    """What one printed number (no spaces) could mean.

    A comma or a dot is only dropped as a thousands separator when groups of
    exactly three digits follow it: '1,013' can be 1013, '22,31' can't be 2231.
    """
    values = set()
    if COMMA_THOUSANDS_RE.fullmatch(raw):
        values.add(Decimal(raw.replace(",", "")))
    if DOT_THOUSANDS_RE.fullmatch(raw):
        values.add(Decimal(raw.replace(".", "").replace(",", ".")))
    if DECIMAL_RE.fullmatch(raw):
        values.add(Decimal(raw.replace(",", ".")))
    return values


def printed_numbers(text: str) -> set[Decimal]:
    """Every value a printed number could mean: '1,013' -> {1013, 1.013}."""
    values: set[Decimal] = set()
    for match in NUMBER_RE.finditer(normalize_spaces(text)):
        raw = match[0]
        values |= _meanings(raw.replace(" ", ""))   # 2 757 / 1 380,95: spaces group thousands
        for piece in raw.split(" "):                # pieces of a merged run
            values |= _meanings(piece)
    return values


def printed_dates(text: str) -> set[date]:
    folded = fold(normalize_spaces(text))
    found: set[date] = set()

    def add(y, m, d):
        try:
            found.add(date(int(y), int(m), int(d)))
        except ValueError:
            pass

    for y, m, d in re.findall(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b", folded):
        add(y, m, d)
    for a, b, y in re.findall(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b", folded):
        add(y, b, a)  # day-month-year
        add(y, a, b)  # month-day-year
    month_names = "|".join(sorted(MONTHS, key=len, reverse=True))
    for name, d, y in re.findall(rf"\b({month_names})\.? (\d{{1,2}}),? (\d{{4}})\b", folded):
        add(y, MONTHS[name], d)
    for d, name, y in re.findall(rf"\b(\d{{1,2}}) ({month_names})\.? (\d{{4}})\b", folded):
        add(y, MONTHS[name], d)
    return found


# --- parsing the answer ----------------------------------------------------

def _load(answer: str) -> dict:
    match = re.search(r"\{.*\}", answer or "", re.S)  # tolerate ```json fences / chatter
    if not match:
        raise InvalidModelOutput("no JSON object")
    try:
        data = json.loads(match[0])
    except json.JSONDecodeError as e:
        raise InvalidModelOutput(f"invalid JSON: {e}") from e
    if not isinstance(data, dict):
        raise InvalidModelOutput("not an object")
    return data


def _date(value) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _decimal(value) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def validate(answer: str, source_text: str) -> ParsedEntry | None:
    """Model answer + the text it was given -> a checked ParsedEntry, or None."""
    data = _load(answer)
    notes: list[str] = []
    numbers, dates = printed_numbers(source_text), printed_dates(source_text)

    def grounded(value: Decimal | None, label: str) -> Decimal | None:
        if value is None:
            return None
        if value in numbers or value.normalize() in {n.normalize() for n in numbers}:
            return value
        notes.append(f"Model's {label} ({value}) isn't printed on the bill: left empty.")
        return None

    # Period ------------------------------------------------------------------
    start, end = _date(data.get("start_date")), _date(data.get("end_date"))
    for label, value in (("start date", start), ("end date", end)):
        if value is not None and value not in dates:
            notes.append(f"Model's {label} ({value}) isn't printed on the bill: left empty.")
    start = start if start in dates else None
    end = end if end in dates else None
    days = data.get("days_printed")
    days = days if isinstance(days, int) and Decimal(days) in numbers else None

    if start and end:
        if end <= start:
            notes.append("Model's period ends before it starts: left empty.")
            start = end = None
        else:
            span = (end - start).days
            if days is None:
                notes.append("No day count printed: check whether the end date is inclusive.")
            elif span == days - 1:
                end += timedelta(days=1)  # printed end is the last billed day
                notes.append("End date printed as the last billed day: stored as the next day (exclusive).")
            elif span != days:
                notes.append(f"Period is {span} days but the bill says {days}.")
            if not 20 <= (end - start).days <= 100:
                notes.append(f"Unusual period length: {(end - start).days} days.")

    # Consumption ---------------------------------------------------------------
    consumption = grounded(_decimal(data.get("consumption")), "consumption")
    unit = UNITS.get(str(data.get("consumption_unit") or "").lower(), "")
    billed_power = grounded(_decimal(data.get("billed_power_kw")), "billed power")

    # Cost --------------------------------------------------------------------
    cost = _decimal(data.get("cost_before_taxes"))
    components = data.get("cost_components") or []
    if cost is not None and cost not in numbers:
        amounts = [_decimal(c.get("amount")) for c in components if isinstance(c, dict)]
        if amounts and all(a is not None and abs(a) in numbers for a in amounts) and sum(amounts) == cost:
            notes.append(f"Cost isn't printed as such: computed from {len(amounts)} printed amounts.")
        else:
            notes.append(f"Model's cost ({cost}) isn't printed on the bill nor a sum of printed amounts: left empty.")
            cost = None
    if cost is not None and TAX_WORDS.search(source_text):
        # A pre-tax cost (or the subtotal it was computed from) times a sales
        # tax rate should be printed as a tax line. If none is, the model may
        # have taken a total that already includes taxes.
        bases = {cost} | {_decimal(c.get("amount")) for c in components if isinstance(c, dict)} - {None}
        tax_found = any(
            abs((base * rate).quantize(Decimal("0.01")) - n) <= Decimal("0.02")
            for base in bases for rate in SALES_TAX_RATES for n in numbers if n > 0
        )
        if not tax_found:
            notes.append("No printed tax line matches this cost: does it include taxes?")
    if cost is not None and consumption and unit in UNIT_PRICE_RANGE:
        low, high = UNIT_PRICE_RANGE[unit]
        price = cost / consumption
        if not low <= price <= high:
            notes.append(f"Unusual price: {price:.3f} $/{unit}.")

    rate = str(data.get("rate_code") or "").strip()[:30]
    if rate and fold(rate) not in fold(source_text):
        notes.append(f"Rate code {rate!r} isn't printed as such.")

    values = dict(start_billing_period=start, end_billing_period=end, consumption=consumption, bill_cost=cost)
    found = sum(v is not None for v in values.values())
    if found == 0:
        return None
    missing = [k for k, v in values.items() if v is None]
    if missing:
        notes.append("Missing: " + ", ".join(m.replace("_", " ") for m in missing) + ".")
    return ParsedEntry(
        source="ai",
        parser_name=PARSER_NAME,
        needs_review=True,
        confidence=round(found / len(REQUIRED) * 0.9 ** len(notes), 2),
        rate_code=rate,
        consumption_unit=unit,
        billed_power=billed_power,
        warnings=notes,
        **values,
    )
