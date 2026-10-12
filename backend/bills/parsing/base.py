"""Contract between the upload pipeline and bill parsers.

This is a starting point, not a spec: change the shapes if your design needs
it, and say why in NOTES.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Protocol


@dataclass
class DocumentInput:
    """One uploaded file, as handed to parsers."""

    path: Path
    content_type: str
    filename: str
    text: str  # PDF text layer; empty for images and scanned PDFs
    # What we already know about this bill's owner (customer name, account
    # number, building address, user). Lets the privacy layer mask it even
    # where it has no recognisable shape. Never logged (repr=False).
    known_personal_info: list[str] = field(default_factory=list, repr=False)
    # The bill's account number, if known: checked locally, never sent.
    account_number_on_file: str = field(default="", repr=False)


@dataclass
class ParsedEntry:
    """What a parser read from one bill document.

    Account-level fields match `bills.models.Bill`, period fields match
    `bills.models.BillEntry`.
    """

    source: str  # BillEntry.Source value: "deterministic" or "ai"
    parser_name: str
    needs_review: bool = True
    confidence: float | None = None

    # Account level (Bill). Personal information: kept out of repr() so that
    # logging a ParsedEntry (services.py does) never writes it to the logs.
    utility: str = ""
    account_number: str = field(default="", repr=False)
    customer_name: str = field(default="", repr=False)
    rate_code: str = ""
    consumption_unit: str = ""

    # Billing period (BillEntry)
    start_billing_period: date | None = None
    end_billing_period: date | None = None  # exclusive
    consumption: Decimal | None = None
    billed_power: Decimal | None = None
    bill_cost: Decimal | None = None  # before taxes

    warnings: list[str] = field(default_factory=list)


class BillParser(Protocol):
    name: str

    def parse(self, documents: list[DocumentInput]) -> ParsedEntry | None:
        """Return a ParsedEntry, or None if this parser doesn't handle these documents."""
        ...
