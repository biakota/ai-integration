"""Run every sample through the real pipeline and score it against ground truth.

    python manage.py evaluate_samples              # uses AI_PROVIDER from .env
    python manage.py evaluate_samples --only ovpl  # one sample

Uses the real OCR and the configured model (try AI_PROVIDER=ollama). Prints
field-level accuracy, timings, and re-checks that no request carried
personal information. Nothing is written to the database. Output shows
extracted values (not personal fields) and is meant for a developer's
terminal only.
"""

import json
import time
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand

from bills.ai import client as ai_client
from bills.parsing.base import DocumentInput
from bills.parsing.registry import parse
from bills.parsing.text import extract_pdf_text
from bills.privacy.guard import known_info_found
from bills.privacy.redact import unsafe_tokens

FIELDS = ["start_billing_period", "end_billing_period", "consumption", "billed_power", "bill_cost"]
CONTENT_TYPES = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


class Recorder(ai_client.LLMClient):
    def __init__(self, inner):
        self.inner, self.requests = inner, []

    def complete(self, request):
        self.requests.append(request)
        return self.inner.complete(request)


class Command(BaseCommand):
    help = "Score the parsers on samples/ground_truth.json."

    def add_arguments(self, parser):
        parser.add_argument("--only", default="", help="Substring of the sample file name.")

    def handle(self, *args, only="", **options):
        samples = json.loads((settings.SAMPLES_DIR / "ground_truth.json").read_text(encoding="utf-8"))["samples"]
        build = ai_client._build_client
        recorder = Recorder(build())
        ai_client._build_client = lambda: recorder
        correct = total = 0
        try:
            for sample in samples:
                if only not in sample["file"]:
                    continue
                recorder.requests.clear()
                documents = [self._input(p) for p in self._paths(sample["file"])]
                started = time.monotonic()
                result = parse(documents)
                elapsed = time.monotonic() - started
                expected = sample["expected"]["entry"]
                row = []
                for field in FIELDS:
                    got = getattr(result, field, None) if result else None
                    want = expected[field]
                    ok = self._same(got, want)
                    correct += ok
                    total += 1
                    row.append(f"{field.replace('_billing_period', '')}={'✓' if ok else f'✗ {got} (want {want})'}")
                leaked = [
                    "image" for r in recorder.requests for p in r.parts if not isinstance(p, ai_client.TextPart)
                ] + [
                    "tokens" for r in recorder.requests for p in r.parts
                    if isinstance(p, ai_client.TextPart) and unsafe_tokens(p.text)
                ] + [
                    "personal info" for r in recorder.requests for p in r.parts
                    if isinstance(p, ai_client.TextPart) and known_info_found(p.text, sample["personal_information"])
                ]
                status = "declined" if result is None else ("review" if result.needs_review else "trusted")
                self.stdout.write(
                    f"{sample['file']}\n  {result.parser_name if result else '-'} [{status}] "
                    f"{elapsed:.1f}s, {len(recorder.requests)} model call(s), "
                    f"PII sent: {'NONE' if not leaked else leaked}\n  " + "  ".join(row)
                )
                if result and result.warnings:
                    self.stdout.write("  notes: " + " | ".join(result.warnings))
        finally:
            ai_client._build_client = build
        self.stdout.write(f"\nField accuracy: {correct}/{total}")

    @staticmethod
    def _paths(file):
        first, *others = file.split(" + ")
        paths = [settings.SAMPLES_DIR / first]
        paths += [settings.SAMPLES_DIR / f"{first.rsplit('-', 1)[0]}{s}" for s in others]
        return paths

    @staticmethod
    def _input(path):
        content_type = CONTENT_TYPES[path.suffix.lower()]
        text = extract_pdf_text(path) if content_type == "application/pdf" else ""
        return DocumentInput(path=path, content_type=content_type, filename=path.name, text=text)

    @staticmethod
    def _same(got, want):
        if want is None:
            return got is None
        if got is None:
            return False
        if isinstance(got, date):
            return got.isoformat() == want
        return Decimal(str(got)) == Decimal(want)
