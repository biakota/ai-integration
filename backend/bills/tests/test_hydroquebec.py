import dataclasses
import shutil
import tempfile

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from bills.models import Bill, BillEntry, Building
from bills.parsing.base import DocumentInput
from bills.parsing.hydroquebec import HydroQuebecPdfParser

from .samples import expected_values, ground_truth, pdf_input

HQ_TEXT_PDFS = [
    s for s in ground_truth()
    if s["file"].startswith("hydro-quebec/pdf/") and s["has_text_layer"]
]
FIELDS = [
    "utility", "account_number", "customer_name", "rate_code", "consumption_unit",
    "start_billing_period", "end_billing_period", "consumption", "billed_power", "bill_cost",
]


class HydroQuebecParserTests(SimpleTestCase):
    parser = HydroQuebecPdfParser()

    def test_reads_every_text_pdf_sample_like_ground_truth(self):
        self.assertEqual(len(HQ_TEXT_PDFS), 5)
        for sample in HQ_TEXT_PDFS:
            with self.subTest(sample["file"]):
                result = self.parser.parse([pdf_input(sample["file"])])
                self.assertIsNotNone(result)
                expected = expected_values(sample)
                self.assertEqual({f: getattr(result, f) for f in FIELDS}, {f: expected[f] for f in FIELDS})
                self.assertEqual(result.source, "deterministic")
                self.assertFalse(result.needs_review, result.warnings)
                self.assertEqual(result.warnings, [])

    def test_declines_scanned_pdf_without_text_layer(self):
        self.assertIsNone(self.parser.parse([pdf_input("hydro-quebec/pdf/hq-06-scanned-no-text-layer.pdf")]))

    def test_declines_other_utilities(self):
        self.assertIsNone(self.parser.parse([pdf_input("other-utilities/gaz-boreal-01.pdf")]))

    def test_declines_images(self):
        path = settings.SAMPLES_DIR / "hydro-quebec/images/hq-01-rate-d-standard-p1.png"
        self.assertIsNone(self.parser.parse([DocumentInput(path, "image/png", path.name, "")]))

    def _tampered(self, old, new, file="hydro-quebec/pdf/hq-01-rate-d-standard.pdf"):
        document = pdf_input(file)
        self.assertIn(old, document.text)
        return self.parser.parse([dataclasses.replace(document, text=document.text.replace(old, new, 1))])

    def test_inconsistent_subtotal_goes_to_review(self):
        result = self._tampered("Total partiel 232,27 $", "Total partiel 232,72 $")
        self.assertTrue(result.needs_review)
        self.assertIn("Cost lines don't add up to the subtotal.", result.warnings)

    def test_inconsistent_day_count_goes_to_review(self):
        result = self._tampered("au 09-06-2025 (60 jours)\nDETAILS OF COSTS", "au 09-06-2025 (61 jours)\nDETAILS OF COSTS")
        self.assertTrue(result.needs_review)
        self.assertTrue(any("not 61 days" in w for w in result.warnings), result.warnings)

    def test_unknown_rate_goes_to_review(self):
        result = self._tampered("TARIF DOMESTIQUE D", "TARIF DOMESTIQUE DT")
        self.assertEqual(result.rate_code, "DT")
        self.assertTrue(result.needs_review)

    def test_missing_required_field_declines(self):
        self.assertIsNone(self._tampered("Total partiel", "Sous-total"))

    def test_personal_fields_are_not_in_repr(self):
        # services.py logs the ParsedEntry; it must not write a name to the logs.
        result = self.parser.parse([pdf_input(HQ_TEXT_PDFS[0]["file"])])
        self.assertNotIn(result.customer_name, repr(result))
        self.assertNotIn(result.account_number, repr(result))


TMP_MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class HydroQuebecUploadTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP_MEDIA, ignore_errors=True)

    def setUp(self):
        user = get_user_model().objects.create(username="alice")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {Token.objects.create(user=user).key}")
        building = Building.objects.create(owner=user, name="Test", address="1, rue Test")
        self.bill = Bill.objects.create(building=building, name="Élec", utility="hydro_quebec")

    def upload(self, relative):
        path = settings.SAMPLES_DIR / relative
        return self.client.post(
            f"/api/bills/{self.bill.pk}/upload/",
            {"files": [SimpleUploadedFile(path.name, path.read_bytes())]}, format="multipart",
        )

    def test_upload_fills_entry_and_bill(self):
        sample = HQ_TEXT_PDFS[3]  # rate DP, with billed power
        response = self.upload(sample["file"])
        self.assertEqual(response.status_code, 201, response.data)
        expected = sample["expected"]
        self.assertEqual(response.data["source"], "deterministic")
        self.assertEqual(response.data["status"], "parsed")
        self.assertEqual(response.data["start_billing_period"], expected["entry"]["start_billing_period"])
        self.assertEqual(response.data["end_billing_period"], expected["entry"]["end_billing_period"])
        self.assertEqual(response.data["bill_cost"], "1380.95")
        self.assertEqual(response.data["billed_power"], "62.00")
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.account_number, expected["bill"]["account_number"])
        self.assertEqual(self.bill.rate_code, "DP")

    def test_upload_to_another_account_goes_to_review(self):
        self.bill.account_number = "299000000999"
        self.bill.save()
        response = self.upload(HQ_TEXT_PDFS[0]["file"])
        self.assertEqual(response.data["status"], "needs_review")
        self.assertIn("wrong bill", " ".join(response.data["review_notes"]))
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.account_number, "299000000999")  # not overwritten

    def test_same_bill_uploaded_twice_goes_to_review(self):
        self.assertEqual(self.upload(HQ_TEXT_PDFS[0]["file"]).data["status"], "parsed")
        second = self.upload(HQ_TEXT_PDFS[0]["file"])
        self.assertEqual(second.data["status"], "needs_review")
        self.assertIn("duplicate", " ".join(second.data["review_notes"]))
        self.assertEqual(BillEntry.objects.count(), 2)
