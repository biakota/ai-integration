"""The model path, with canned model answers (AI_PROVIDER=fake).

What we test is everything around the model: what it is given, and how
its answer is checked before anything reaches a reviewer.
"""

import json
import shutil
import tempfile
from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from bills.ai.client import FakeLLMClient, LLMRequest, OllamaClient, TextPart
from bills.ai.ground_truth import GroundTruthClient
from bills.ai.language import detect_language
from bills.ai.prompt import SYSTEM_EN, SYSTEM_FR, system_prompt
from bills.ai.validate import InvalidModelOutput, printed_dates, printed_numbers, validate
from bills.models import Bill, Building
from bills.privacy.redact import redact_lines

from .ocr_fixture import recorded_lines, recorded_ocr
from .samples import expected_values, ground_truth, pdf_input, sample_paths

MODEL_SAMPLES = [
    s for s in ground_truth()
    if not (s["file"].startswith("hydro-quebec/pdf/") and s["has_text_layer"])
]


def perfect_answer(sample: dict, **overrides) -> str:
    """What a model that reads the bill perfectly would answer."""
    entry = sample["expected"]["entry"]
    start, end = date.fromisoformat(entry["start_billing_period"]), date.fromisoformat(entry["end_billing_period"])
    answer = {
        "start_date": entry["start_billing_period"],
        "end_date": entry["end_billing_period"],
        "days_printed": (end - start).days,
        "consumption": float(entry["consumption"]),
        "consumption_unit": sample["expected"]["bill"]["consumption_unit"],
        "billed_power_kw": entry["billed_power"] and float(entry["billed_power"]),
        "cost_before_taxes": float(entry["bill_cost"]),
        "cost_components": [],
        "rate_code": sample["expected"]["bill"]["rate_code"],
    }
    if sample["file"].startswith("other-utilities/ovpl"):
        # Not printed as such: subtotal minus the Ontario Electricity Rebate.
        answer["cost_components"] = [
            {"label": "Subtotal", "amount": 169.19},
            {"label": "Ontario Electricity Rebate", "amount": -22.16},
        ]
    answer.update(overrides)
    return json.dumps(answer)


def redacted_text(sample: dict) -> str:
    lines = (pdf_input(sample["file"]).text.splitlines() if sample["has_text_layer"]
             else recorded_lines(sample["file"]))
    return redact_lines(lines).text


GAS = next(s for s in MODEL_SAMPLES if s["file"] == "other-utilities/gaz-boreal-01.pdf")
OVPL = next(s for s in MODEL_SAMPLES if s["file"] == "other-utilities/ovpl-01-phone-photo.png")


class ValidateTests(SimpleTestCase):
    FIELDS = ["start_billing_period", "end_billing_period", "consumption", "billed_power", "bill_cost"]

    def test_a_correct_answer_survives_validation_on_every_sample(self):
        # Every value the model needs is still in the redacted text, and our
        # checks don't distort a correct answer.
        for sample in MODEL_SAMPLES:
            with self.subTest(sample["file"]):
                result = validate(perfect_answer(sample), redacted_text(sample))
                expected = expected_values(sample)
                self.assertEqual({f: getattr(result, f) for f in self.FIELDS}, {f: expected[f] for f in self.FIELDS})
                self.assertEqual(result.source, "ai")
                self.assertTrue(result.needs_review)  # always, for now

    def test_computed_cost_is_accepted_only_with_printed_components(self):
        result = validate(perfect_answer(OVPL), redacted_text(OVPL))
        self.assertEqual(result.bill_cost, Decimal("147.03"))
        self.assertIn("computed from 2 printed amounts", " ".join(result.warnings))
        without = validate(perfect_answer(OVPL, cost_components=[]), redacted_text(OVPL))
        self.assertIsNone(without.bill_cost)

    def test_invented_values_are_dropped_not_kept(self):
        result = validate(
            perfect_answer(GAS, consumption=421, cost_before_taxes=284.61, start_date="2025-02-04"),
            redacted_text(GAS),
        )
        self.assertIsNone(result.consumption)
        self.assertIsNone(result.bill_cost)
        self.assertIsNone(result.start_billing_period)
        self.assertEqual(result.end_billing_period, date(2025, 3, 4))
        self.assertEqual(len([w for w in result.warnings if "isn't printed" in w]), 3)
        self.assertLess(result.confidence, 0.3)

    def test_cost_with_taxes_is_flagged(self):
        result = validate(perfect_answer(GAS, cost_before_taxes=285.84), redacted_text(GAS))
        self.assertEqual(result.bill_cost, Decimal("285.84"))  # printed, so kept...
        self.assertIn("include taxes", " ".join(result.warnings))  # ...but flagged

    def test_inclusive_end_date_is_made_exclusive(self):
        text = "Billing period: Jan 1, 2025 to Jan 31, 2025 (31 days)\nUsage 812 kWh\nSubtotal $98.10\nGST $4.91"
        answer = json.dumps({"start_date": "2025-01-01", "end_date": "2025-01-31", "days_printed": 31,
                             "consumption": 812, "consumption_unit": "kWh", "cost_before_taxes": 98.10})
        result = validate(answer, text)
        self.assertEqual(result.end_billing_period, date(2025, 2, 1))
        self.assertIn("exclusive", " ".join(result.warnings))

    def test_day_count_mismatch_is_flagged(self):
        result = validate(perfect_answer(GAS, days_printed=29, end_date="2025-03-06"), redacted_text(GAS))
        self.assertIn("days but the bill says 29", " ".join(result.warnings))

    def test_ambiguous_dates_are_read_both_ways(self):
        self.assertTrue({date(2025, 4, 10), date(2025, 10, 4)} <= printed_dates("Du 10-04-2025"))

    def test_garbage_is_rejected(self):
        with self.assertRaises(InvalidModelOutput):
            validate("Sorry, I can't read this bill.", "x")
        self.assertIsNone(validate("{}", redacted_text(GAS)))

    def test_markdown_fenced_json_is_accepted(self):
        result = validate("```json\n" + perfect_answer(GAS) + "\n```", redacted_text(GAS))
        self.assertEqual(result.consumption, Decimal("412"))


class OllamaClientTests(SimpleTestCase):
    def test_sends_text_with_schema_and_returns_content(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({"message": {"content": "{}"}}).encode()
        with mock.patch("bills.ai.client.urllib.request.urlopen", return_value=response) as urlopen:
            answer = OllamaClient("http://localhost:11434", "qwen2.5:7b").complete(
                LLMRequest(system="sys", parts=[TextPart("bill")], response_schema={"type": "object"})
            )
        self.assertEqual(answer, "{}")
        body = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(body["format"], {"type": "object"})
        self.assertEqual(body["options"]["temperature"], 0)


class GroundTruthProviderTests(SimpleTestCase):
    FIELDS = ValidateTests.FIELDS

    def test_reads_every_sample_from_its_redacted_text(self):
        for sample in MODEL_SAMPLES:
            with self.subTest(sample["file"]):
                text = redacted_text(sample)
                result = validate(GroundTruthClient().complete(LLMRequest(system="", parts=[TextPart(text)])), text)
                expected = expected_values(sample)
                self.assertEqual({f: getattr(result, f) for f in self.FIELDS}, {f: expected[f] for f in self.FIELDS})

    def test_unknown_bill_gets_an_empty_answer(self):
        text = "Billing period: Jan 1, 2025 to Jan 31, 2025 (31 days)\nUsage 812 kWh\nSubtotal $98.10"
        self.assertEqual(GroundTruthClient().complete(LLMRequest(system="", parts=[TextPart(text)])), "{}")

    @override_settings(AI_PROVIDER="ground_truth")
    def test_entries_say_they_were_not_read_by_a_model(self):
        from bills.parsing.model import ModelParser

        result = ModelParser().parse([pdf_input(GAS["file"])])
        self.assertEqual(result.bill_cost, Decimal("248.61"))
        self.assertEqual(result.parser_name, "ground_truth")
        self.assertIn("not by a model", " ".join(result.warnings))


class PrintedNumbersTests(SimpleTestCase):
    def test_decimal_separator_is_never_dropped(self):
        # "22,31 $" read as 2231 by the model must not count as printed.
        numbers = printed_numbers("Total partiel 22,31 $ puis 22.31 $")
        self.assertIn(Decimal("22.31"), numbers)
        self.assertNotIn(Decimal("2231"), numbers)

    def test_thousands_separators(self):
        numbers = printed_numbers("1,013 kWh / 1 380,95 $ / 1,380.95 $ / 1.380,95 $ / 2 757 kWh")
        for value in ("1013", "1.013", "1380.95", "2757"):
            self.assertIn(Decimal(value), numbers)

    def test_cost_with_a_misplaced_decimal_point_is_dropped(self):
        answer = json.dumps({"consumption": 157, "consumption_unit": "kWh", "cost_before_taxes": 2231})
        result = validate(answer, "Consommation 157 kWh\nTotal partiel 22,31 $")
        self.assertIsNone(result.bill_cost)
        self.assertEqual(result.consumption, Decimal("157"))


class LanguageTests(SimpleTestCase):
    def test_french_and_english_bills_are_told_apart(self):
        self.assertEqual(detect_language("Période de facturation du 10-04-2025 au 09-06-2025\nMontant à payer"), "fr")
        self.assertEqual(detect_language("Billing period from 2025-04-10 to 2025-06-09\nAmount due"), "en")

    def test_accents_lost_by_ocr_dont_matter(self):
        self.assertEqual(detect_language("Periode de facturation, electricite, releve du compteur"), "fr")

    def test_no_signal_falls_back_to_english(self):
        self.assertEqual(detect_language(""), "en")
        self.assertEqual(detect_language("1 380,95 $ 2025-04-10 kWh"), "en")
        self.assertEqual(system_prompt("de"), SYSTEM_EN)

    def test_samples(self):
        self.assertEqual(detect_language("\n".join(recorded_lines(OVPL["file"]))), "en")
        self.assertEqual(detect_language(pdf_input(GAS["file"]).text), "fr")


TMP_MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TMP_MEDIA, AI_PROVIDER="fake")
class ModelUploadTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP_MEDIA, ignore_errors=True)

    def setUp(self):
        user = get_user_model().objects.create(username="alice")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {Token.objects.create(user=user).key}")
        self.building = Building.objects.create(owner=user, name="Test", address="1, rue Test")

    def upload(self, sample, answer, unit="kWh", account=""):
        bill = Bill.objects.create(building=self.building, name="B", utility="other",
                                   consumption_unit=unit, account_number=account)
        fake = FakeLLMClient(responses=[answer])
        files = [SimpleUploadedFile(p.name, p.read_bytes()) for p in sample_paths(sample)]
        with mock.patch("bills.ai.client._build_client", return_value=fake), recorded_ocr():
            response = self.client.post(f"/api/bills/{bill.pk}/upload/", {"files": files}, format="multipart")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data, fake

    def test_photo_is_read_by_the_model_and_sent_to_review(self):
        data, fake = self.upload(OVPL, perfect_answer(OVPL), account="0000000001")
        self.assertEqual(data["source"], "ai")
        self.assertEqual(data["status"], "needs_review")
        self.assertEqual(data["parser_name"], "model_v1")
        self.assertEqual(data["bill_cost"], "147.03")
        self.assertEqual(data["end_billing_period"], "2025-05-16")
        self.assertNotIn("account number", " ".join(data["review_notes"]))

    def test_model_is_prompted_in_the_language_of_the_bill(self):
        _, fake = self.upload(OVPL, perfect_answer(OVPL))
        self.assertEqual(fake.requests[0].system, SYSTEM_EN)
        _, fake = self.upload(GAS, perfect_answer(GAS), unit="m3")
        self.assertEqual(fake.requests[0].system, SYSTEM_FR)

    def test_scanned_hydro_quebec_pdf_goes_to_the_model(self):
        scan = next(s for s in MODEL_SAMPLES if "hq-06" in s["file"])
        data, fake = self.upload(scan, perfect_answer(scan))
        self.assertEqual(len(fake.requests), 1)
        self.assertEqual(data["consumption"], "3558.00")

    def test_gas_bill_uploaded_to_an_electricity_bill_is_flagged(self):
        data, _ = self.upload(GAS, perfect_answer(GAS), unit="kWh")
        self.assertIn("billed in m3", " ".join(data["review_notes"]))

    def test_account_on_file_missing_from_document_is_flagged(self):
        data, _ = self.upload(GAS, perfect_answer(GAS), unit="m3", account="111222333")
        self.assertIn("account number wasn't found", " ".join(data["review_notes"]))

    def test_unusable_answer_leaves_the_entry_unparsed(self):
        data, _ = self.upload(GAS, "I cannot help with that.", unit="m3")
        self.assertEqual(data["status"], "unparsed")
        self.assertIsNone(data["bill_cost"])
