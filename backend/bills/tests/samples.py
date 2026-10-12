"""Access to samples/ground_truth.json for tests."""

import json
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from django.conf import settings

from bills.parsing.base import DocumentInput
from bills.parsing.text import extract_pdf_text


@lru_cache(maxsize=1)
def ground_truth() -> list[dict]:
    return json.loads((settings.SAMPLES_DIR / "ground_truth.json").read_text(encoding="utf-8"))["samples"]


def sample(file: str) -> dict:
    return next(s for s in ground_truth() if s["file"] == file)


def sample_paths(entry: dict) -> list[Path]:
    """'images/x-p1.png + -p2.png' -> both paths."""
    first, *others = entry["file"].split(" + ")
    paths = [settings.SAMPLES_DIR / first]
    for suffix in others:
        stem = first.rsplit("-", 1)[0]
        paths.append(settings.SAMPLES_DIR / f"{stem}{suffix}")
    return paths


def pdf_input(relative: str) -> DocumentInput:
    path = settings.SAMPLES_DIR / relative
    return DocumentInput(path=path, content_type="application/pdf", filename=path.name,
                         text=extract_pdf_text(path))


def expected_values(entry: dict) -> dict:
    """ground-truth `expected` flattened and converted to Python types."""
    bill, period = entry["expected"]["bill"], entry["expected"]["entry"]
    out = dict(bill)
    for key, value in period.items():
        if value is None:
            out[key] = None
        elif key.endswith("billing_period"):
            out[key] = date.fromisoformat(value)
        else:
            out[key] = Decimal(value)
    return out
