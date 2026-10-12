"""Replays recorded OCR output instead of running the OCR engine.

Tests stay fast and deterministic, and don't depend on the OCR models being
downloaded. The real engine is exercised by test_real_ocr.py (opt-in).
"""

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

FIXTURE = Path(__file__).parent / "fixtures" / "ocr_lines.json"


def _pages() -> dict[str, list[str]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["pages"]


def _lookup(filename: str) -> list[str]:
    # Django may have suffixed the stored name ("x-p1_AbC1234.png").
    name = Path(filename).name
    for key, lines in _pages().items():
        file_part, _, page = key.partition("#")
        stem = Path(file_part).stem
        target = Path(name.split("#")[0]).stem
        if (target == stem or target.startswith(stem + "_")) and page == name.partition("#")[2]:
            return lines
    raise KeyError(f"No recorded OCR for {filename}")


def fake_ocr_lines(image) -> list[str]:
    return list(_lookup(image.filename))


def fake_pdf_page_images(path, scale=2.0):
    count = sum(1 for key in _pages() if key.startswith(f"{_base(path)}#") or _matches_pdf(key, path))
    return [SimpleNamespace(filename=f"{Path(path).name}#p{i}") for i in range(1, count + 1)]


def _base(path) -> str:
    return Path(path).name


def _matches_pdf(key: str, path) -> bool:
    file_part, _, _ = key.partition("#")
    stem, target = Path(file_part).stem, Path(path).stem
    return target == stem or target.startswith(stem + "_")


@contextmanager
def recorded_ocr():
    with mock.patch("bills.parsing.model.ocr_lines", fake_ocr_lines), \
            mock.patch("bills.parsing.model.pdf_page_images", fake_pdf_page_images):
        yield


def recorded_lines(sample_file: str) -> list[str]:
    """All OCR lines of a ground-truth sample (images, or scanned PDF pages)."""
    pages = _pages()
    files = [f.strip() for f in sample_file.split(" + ")]
    first = files[0]
    keys = [first] + [first.rsplit("-", 1)[0] + suffix for suffix in files[1:]]
    lines: list[str] = []
    for key in keys:
        matching = [k for k in pages if k == key or k.startswith(key + "#")]
        for k in sorted(matching):
            lines.extend(pages[k])
    return lines
