"""Deterministic reader for Hydro-Québec bills downloaded as PDF (text layer).

Built from the layout of Hydro-Québec's bills (bilingual, 3 pages: account
summary, consumption + cost details, history). Reads one billing period.

Philosophy:
- *Decline* (return None) as soon as the document isn't clearly a Hydro-Québec
  bill with a text layer, or a required field can't be found. The next parser
  (model-based) then gets a chance. Never guess.
- When everything is found, *cross-check* it with the redundancy the bill
  itself prints (FR vs EN dates, day counts, meter difference vs total,
  line items vs subtotal, subtotal + taxes vs total, page-1 summary vs
  details, account number on every page). The entry is only `parsed`
  (trusted) when every check passes; any failed check -> `needs_review`
  with the reason in `warnings`.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from .base import DocumentInput, ParsedEntry
from .values import normalize_spaces, parse_amount, parse_dmy, parse_mdy

NAME = "hydro_quebec_pdf_v1"

# Rates whose layout this parser was built against. Other rates (M, G, DT,
# Flex D, ...) print extra sections (e.g. winter credits, peak events): still
# read, but always sent to review.
KNOWN_RATES = {"D", "DP"}
DEMAND_RATES = {"DP", "M", "G", "LG"}

_N = r"\d{1,3}(?: \d{3})*"                 # 12 480
_AMT = r"-?\d{1,3}(?: \d{3})*,\d{2}"         # 1 380,95
_APOS = "[’']"

HEADER_RE = re.compile(
    r"^(\d{3} \d{3} \d{3} \d{3}) \d{3} \d{3} \d{3} \d{3} \d{3} \d{3} \d{3} (\d+) / (\d+)$", re.M
)
NAME_RE = re.compile(rf"^(.+?) Facture d{_APOS}électricité du \d{{1,2}} \w+ \d{{4}}$", re.M)
STUB_NAME_RE = re.compile(r"^(.+?) Due date \d\d-\d\d-\d{4}$", re.M)
STUB_ACCOUNT_RE = re.compile(r"N° de compte (\d{3} \d{3} \d{3} \d{3})$", re.M)
COSTS_HEADER_RE = re.compile(r"^DÉTAIL DES COÛTS\s*[–-]\s*TARIF (?:DOMESTIQUE )?([A-Z0-9]+)\b", re.M)
PERIOD_FR_RE = re.compile(r"Du (\d\d-\d\d-\d{4}) au (\d\d-\d\d-\d{4}) \((\d+) jours\)")
PERIOD_EN_RE = re.compile(r"From (\d\d-\d\d-\d{4}), to (\d\d-\d\d-\d{4}) \((\d+) days\)")
TOTAL_USE_RE = re.compile(rf"^Consommation totale ({_N}) kWh$", re.M)
METER_USE_RE = re.compile(rf"= ({_N}) kWh$", re.M)
SUBTOTAL_RE = re.compile(rf"^Total partiel ({_AMT}) \$$", re.M)
SUMMARY_COST_RE = re.compile(rf"^Coûts de l{_APOS}électricité ({_AMT}) \$$", re.M)
GST_RE = re.compile(rf"^TPS / GST \(5 %\) ({_AMT}) \$$", re.M)
QST_RE = re.compile(rf"^TVQ / QST \(9,975 %\) ({_AMT}) \$$", re.M)
TOTAL_COSTS_RE = re.compile(rf"^Total des coûts de l{_APOS}électricité ({_AMT}) \$$", re.M)
LINE_AMOUNT_RE = re.compile(rf"\$ ({_AMT}) \$$", re.M)   # "... x 0,06905 $ 165,72 $"
DEMAND_RE = re.compile(r"Puissance à facturer \((\d+(?:,\d+)?) kW")


def _num(raw: str) -> Decimal:
    return Decimal(raw.replace(" ", ""))


def _amt(raw: str) -> Decimal:
    value = parse_amount(raw)
    assert value is not None, raw  # regexes above only match well-formed amounts
    return value


class HydroQuebecPdfParser:
    name = NAME

    def parse(self, documents: list[DocumentInput]) -> ParsedEntry | None:
        if len(documents) != 1 or documents[0].content_type != "application/pdf":
            return None
        text = normalize_spaces(documents[0].text)
        if "Hydro-Québec" not in text or "N° de compte / Account No." not in text:
            return None  # not Hydro-Québec, or a scan without text layer
        return _Reader(text).read()


class _Reader:
    def __init__(self, text: str):
        self.text = text
        self.warnings: list[str] = []

    def check(self, ok: bool, message: str) -> None:
        if not ok:
            self.warnings.append(message)

    def read(self) -> ParsedEntry | None:
        text = self.text

        headers = HEADER_RE.findall(text)
        costs_headers = COSTS_HEADER_RE.findall(text)
        if not headers or len(costs_headers) != 1:
            # No account header, or several cost sections (several contracts or
            # meters on one bill): one entry can't represent it. Decline.
            return None
        costs_start = COSTS_HEADER_RE.search(text).end()
        costs = text[costs_start:]

        fr = PERIOD_FR_RE.search(costs)
        total_use = TOTAL_USE_RE.search(costs)
        subtotal = SUBTOTAL_RE.search(costs)
        if not (fr and total_use and subtotal):
            return None

        # --- account ------------------------------------------------------
        accounts = {a for a, _, _ in headers}
        stub = STUB_ACCOUNT_RE.search(text)
        if stub:
            accounts.add(stub[1])
        self.check(len(accounts) == 1, "Account number differs between pages.")
        account = headers[0][0].replace(" ", "")
        page_count = int(headers[0][2])
        self.check(len(headers) == page_count, f"Expected {page_count} pages, found {len(headers)}.")

        # --- customer name (layout-dependent: warn, don't decline) --------
        name_match, stub_name = NAME_RE.search(text), STUB_NAME_RE.search(text)
        customer = name_match[1].strip() if name_match else ""
        self.check(bool(customer), "Customer name not found.")
        if customer and stub_name:
            self.check(stub_name[1].strip() == customer, "Customer name differs between bill and payment stub.")

        # --- rate -----------------------------------------------------------
        rate = costs_headers[0]
        self.check(rate in KNOWN_RATES, f"Rate {rate} has not been validated with this parser.")

        # --- period ---------------------------------------------------------
        start, end, days = parse_dmy(fr[1]), parse_dmy(fr[2]), int(fr[3])
        if start is None or end is None:
            return None
        # Hydro-Québec's "au" date is the next period's start: (end - start)
        # equals the printed day count, i.e. it is already exclusive.
        self.check((end - start).days == days, f"Period {start} → {end} is not {days} days.")
        en = PERIOD_EN_RE.search(costs)
        self.check(
            bool(en) and (parse_mdy(en[1]), parse_mdy(en[2])) == (start, end),
            "French and English billing periods disagree.",
        )
        consumption_period = PERIOD_FR_RE.search(text)
        self.check(
            consumption_period is not None
            and (parse_dmy(consumption_period[1]), parse_dmy(consumption_period[2])) == (start, end),
            "Consumption and cost sections have different periods.",
        )
        self.check(20 <= days <= 70, f"Unusual period length: {days} days.")

        # --- consumption ----------------------------------------------------
        consumption = _num(total_use[1])
        meters = [_num(m) for m in METER_USE_RE.findall(text[: costs_start])]
        self.check(
            bool(meters) and sum(meters) == consumption,
            "Total consumption doesn't match the meter readings.",
        )

        # --- cost (before taxes) -------------------------------------------
        bill_cost = _amt(subtotal[1])
        items = [_amt(a) for a in LINE_AMOUNT_RE.findall(costs[: subtotal.start()])]
        self.check(bool(items) and sum(items) == bill_cost, "Cost lines don't add up to the subtotal.")
        summary = SUMMARY_COST_RE.search(text)
        self.check(
            summary is not None and _amt(summary[1]) == bill_cost,
            "Electricity costs on page 1 don't match the cost details.",
        )
        gst, qst, total = GST_RE.search(costs), QST_RE.search(costs), TOTAL_COSTS_RE.search(costs)
        self.check(
            bool(gst and qst and total) and bill_cost + _amt(gst[1]) + _amt(qst[1]) == _amt(total[1]),
            "Subtotal + taxes doesn't match the total.",
        )

        # --- demand ---------------------------------------------------------
        demand = DEMAND_RE.search(costs)
        billed_power = Decimal(demand[1].replace(",", ".")) if demand else None
        if rate in DEMAND_RATES:
            self.check(billed_power is not None, f"Rate {rate} is demand-billed but no billed power was found.")

        return ParsedEntry(
            source="deterministic",
            parser_name=NAME,
            needs_review=bool(self.warnings),
            confidence=1.0 if not self.warnings else 0.5,
            utility="hydro_quebec",
            account_number=account,
            customer_name=customer,
            rate_code=rate,
            consumption_unit="kWh",
            start_billing_period=start,
            end_billing_period=end,
            consumption=consumption,
            billed_power=billed_power,
            bill_cost=bill_cost,
            warnings=self.warnings,
        )
