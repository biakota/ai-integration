"""Small, dependency-free helpers to read numbers and dates as printed on bills.

Shared by the deterministic parsers and the model-output validator.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

# Thin / no-break spaces that pdfplumber and OCR leave inside numbers.
_SPACES = "   "


def normalize_spaces(text: str) -> str:
    for ch in _SPACES:
        text = text.replace(ch, " ")
    return text


def parse_amount(raw: str) -> Decimal | None:
    """'1 380,95' / '1,380.95' / '-412,86' / '$169.02' -> Decimal. None if unreadable."""
    s = normalize_spaces(raw).strip().replace("$", "").replace("€", "").strip()
    negative = s.startswith(("-", "−", "–"))
    s = s.lstrip("-−– ")
    if s.endswith("CR"):  # Hydro-Québec prints credits as "20,62 $ CR"
        negative, s = True, s[:-2].strip()
    s = s.replace(" ", "")
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", s):      # 1,380.95 (English)
        s = s.replace(",", "")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", s):    # 1.380,95 (France)
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        value = Decimal(s)
    except InvalidOperation:
        return None
    return -value if negative else value


def parse_dmy(raw: str) -> date | None:
    """'10-04-2025' (day-month-year, as Hydro-Québec prints French dates)."""
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", raw.strip())
    if not m:
        return None
    try:
        return date(int(m[3]), int(m[2]), int(m[1]))
    except ValueError:
        return None


def parse_mdy(raw: str) -> date | None:
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", raw.strip())
    if not m:
        return None
    try:
        return date(int(m[3]), int(m[1]), int(m[2]))
    except ValueError:
        return None


def digits_only(raw: str) -> str:
    return re.sub(r"\D", "", raw or "")
