"""Proof that no personal information reaches a model.

The rule: no personal information may be sent to a third-party service. In
this app the only outbound call is the model request, built by
bills.parsing.model and sent through bills.privacy.guard. These tests check
both layers separately, then the whole upload path end to end, against the
personal information ground_truth.json lists for every sample.
"""

import re
import shutil
import tempfile
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from bills.ai.client import FakeLLMClient, ImagePart, LLMRequest, TextPart, get_llm_client
from bills.privacy.guard import PersonalInfoEgressError, PrivacyGuardedClient
from bills.privacy.redact import redact_lines, unsafe_tokens
from bills.privacy.vocabulary import VOCABULARY, fold
from bills.models import Bill, Building

from .ocr_fixture import recorded_lines, recorded_ocr
from .samples import ground_truth, pdf_input, sample_paths


def leaks(text: str, personal_information: list[str]) -> list[str]:
    """Personal values found in text, compared loosely: case, accents, digit grouping.

    A value leaks if it appears whole, if its digits appear (≥ 6 digits), or if
    any of its distinctive words does (≥ 3 letters, not a vocabulary word, so
    that 'Compteur' in 'chemin du Compteur' doesn't count when the bill prints
    'Numéro de compteur').
    """
    folded, digits = fold(text), re.sub(r"\D", "", text)
    words = set(re.findall(r"\w+", folded))
    found = []
    for value in personal_information:
        value_digits = re.sub(r"\D", "", value)
        if fold(value) in folded or (len(value_digits) >= 6 and value_digits in digits):
            found.append(value)
            continue
        for word in re.findall(r"[^\W\d_]+", fold(value)):
            if len(word) >= 3 and word not in VOCABULARY and word in words:
                found.append(f"{value} ({word})")
    return found


def sample_lines(sample: dict) -> list[str]:
    if sample["has_text_layer"]:
        return pdf_input(sample["file"]).text.splitlines()
    return recorded_lines(sample["file"])


class RedactionTests(SimpleTestCase):
    def test_no_sample_leaks_after_redaction(self):
        for sample in ground_truth():
            with self.subTest(sample["file"]):
                lines = sample_lines(sample)
                self.assertGreater(len(lines), 10)
                # Sanity: the personal information is really in the input...
                self.assertTrue(leaks("\n".join(lines), sample["personal_information"]))
                # ...and none of it in the output.
                text = redact_lines(lines).text
                self.assertEqual(leaks(text, sample["personal_information"]), [])

    def test_redacted_text_passes_the_guard_and_raw_text_does_not(self):
        for sample in ground_truth():
            with self.subTest(sample["file"]):
                lines = sample_lines(sample)
                self.assertEqual(unsafe_tokens(redact_lines(lines).text), [])
                self.assertNotEqual(unsafe_tokens("\n".join(lines)), [])

    def test_redaction_keeps_what_extraction_needs(self):
        text = redact_lines(pdf_input("other-utilities/gaz-boreal-01.pdf").text.splitlines()).text
        for needed in ["2025-02-03 au 2025-03-04 (29 jours)", "412", "Sous-total 248,61 $", "TPS (5 %)", "Tarif D1"]:
            self.assertIn(needed, text)

    def test_known_personal_information_is_masked_even_as_vocabulary(self):
        # A customer whose name is made of ordinary words, and an account number
        # with unusual grouping: only knowing them lets us mask them.
        lines = ["Gestion Hiver inc.", "Compte 12-3456-78", "Consommation 412 m3"]
        text = redact_lines(lines, ["Gestion Hiver inc.", "12345678"]).text
        self.assertNotIn("Hiver", text)
        self.assertNotIn("3456", text)
        self.assertIn("412 m3", text)

    def test_quantities_from_other_layouts_survive(self):
        # Found trying layouts the redaction wasn't built on (PG&E, Toronto Hydro).
        text = redact_lines(["Total Usage 388.000000 kWh", "On-Peak 120 kWh @ 15.8¢ $18.96"]).text
        self.assertIn("388.000000 kWh", text)
        self.assertIn("15.8¢", text)

    def test_unknown_shapes_are_masked(self):
        text = redact_lines([
            "Jane Doe jane.doe@example.com 514 555-0199",
            "1234 Elm Street, Apt 5 Springfield IL 62704",
            "Meter AB-12345678 SIN 046 454 286",
        ]).text
        for value in ["Jane", "Doe", "example", "0199", "Elm", "Springfield", "62704", "12345678", "286"]:
            self.assertNotIn(value, text)


class GuardTests(SimpleTestCase):
    def guarded(self):
        fake = FakeLLMClient()
        return PrivacyGuardedClient(fake), fake

    def test_get_llm_client_is_always_guarded(self):
        self.assertIsInstance(get_llm_client(), PrivacyGuardedClient)

    def test_blocks_images(self):
        client, fake = self.guarded()
        with self.assertRaises(PersonalInfoEgressError):
            client.complete(LLMRequest(system="s", parts=[ImagePart(b"\x89PNG", "image/png")]))
        self.assertEqual(fake.requests, [])

    def test_blocks_unredacted_text(self):
        client, fake = self.guarded()
        raw = pdf_input("hydro-quebec/pdf/hq-01-rate-d-standard.pdf").text
        with self.assertRaises(PersonalInfoEgressError):
            client.complete(LLMRequest(system="s", parts=[TextPart(raw)]))
        self.assertEqual(fake.requests, [])

    def test_blocks_known_personal_information(self):
        client, fake = self.guarded()
        with self.assertRaises(PersonalInfoEgressError):
            client.complete(
                LLMRequest(system="s", parts=[TextPart("Total 12,00 $ Gestion Hiver")]),
                known_personal_info=["Gestion Hiver"],
            )
        self.assertEqual(fake.requests, [])

    def test_lets_redacted_text_through(self):
        client, fake = self.guarded()
        text = redact_lines(pdf_input("other-utilities/gaz-boreal-01.pdf").text.splitlines()).text
        client.complete(LLMRequest(system="s", parts=[TextPart(text)]))
        self.assertEqual(len(fake.requests), 1)


TMP_MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TMP_MEDIA, AI_PROVIDER="fake")
class UploadEgressTests(TestCase):
    """Every sample uploaded through the API: what would have left the server?"""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP_MEDIA, ignore_errors=True)

    def setUp(self):
        user = get_user_model().objects.create(
            username="alice", first_name="Alice", last_name="Proprio", email="alice@example.com"
        )
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {Token.objects.create(user=user).key}")
        building = Building.objects.create(owner=user, name="Test", address="77, rue Exemple, Laprise QC")
        self.bill = Bill.objects.create(building=building, name="Bill", utility="other")
        # The only client the pipeline can get: a fake behind the real guard.
        self.fake = FakeLLMClient()
        patcher = mock.patch("bills.ai.client._build_client", return_value=self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def upload(self, sample):
        files = [SimpleUploadedFile(p.name, p.read_bytes()) for p in sample_paths(sample)]
        with recorded_ocr():
            response = self.client.post(f"/api/bills/{self.bill.pk}/upload/", {"files": files}, format="multipart")
        self.assertEqual(response.status_code, 201, response.data)
        return response

    def test_no_personal_information_in_any_model_request(self):
        for sample in ground_truth():
            with self.subTest(sample["file"]):
                self.fake.requests.clear()
                self.upload(sample)
                deterministic = sample["file"].startswith("hydro-quebec/pdf/") and sample["has_text_layer"]
                # Hydro-Québec PDFs never reach a model; everything else does, once.
                self.assertEqual(len(self.fake.requests), 0 if deterministic else 1)
                for request in self.fake.requests:
                    self.assertTrue(all(isinstance(p, TextPart) for p in request.parts))
                    sent = request.system + "\n".join(p.text for p in request.parts)
                    known = sample["personal_information"] + ["Alice Proprio", "alice@example.com", "77, rue Exemple"]
                    self.assertEqual(leaks(sent, known), [])

    def test_bill_personal_fields_are_masked_too(self):
        sample = next(s for s in ground_truth() if s["file"] == "other-utilities/gaz-boreal-01.pdf")
        self.bill.customer_name = "Sophie Exemple-Gaz"
        self.bill.account_number = "00000000011"
        self.bill.save()
        self.upload(sample)
        [request] = self.fake.requests
        self.assertNotIn("Sophie", request.parts[0].text)
