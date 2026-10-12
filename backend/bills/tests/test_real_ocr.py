"""Same privacy proof as test_privacy, on the real OCR engine's output.

Opt-in (slow: loads the OCR models, a few seconds per page):

    RUN_OCR_TESTS=1 python manage.py test bills.tests.test_real_ocr
"""

import os
import unittest

from django.test import SimpleTestCase
from PIL import Image

from bills.extraction.ocr import ocr_lines, pdf_page_images
from bills.privacy.redact import redact_lines, unsafe_tokens

from .samples import ground_truth, sample_paths
from .test_privacy import leaks


@unittest.skipUnless(os.environ.get("RUN_OCR_TESTS"), "set RUN_OCR_TESTS=1 to run the real OCR")
class RealOcrPrivacyTests(SimpleTestCase):
    def test_no_leak_on_real_ocr_output(self):
        for sample in ground_truth():
            if sample["has_text_layer"]:
                continue
            with self.subTest(sample["file"]):
                lines = []
                for path in sample_paths(sample):
                    if path.suffix == ".pdf":
                        for image in pdf_page_images(path):
                            lines += ocr_lines(image)
                    else:
                        with Image.open(path) as image:
                            lines += ocr_lines(image)
                self.assertTrue(leaks("\n".join(lines), sample["personal_information"]))
                text = redact_lines(lines).text
                self.assertEqual(leaks(text, sample["personal_information"]), [])
                self.assertEqual(unsafe_tokens(text), [])
