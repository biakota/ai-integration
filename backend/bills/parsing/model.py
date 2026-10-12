"""Model-based extraction, for everything the deterministic parsers decline.

    documents ──► text, locally ──► pseudonymised ──► guarded client ──► model
                  (PDF text layer,   (privacy.redact)  (privacy.guard)
                   or local OCR)                                          │
    ParsedEntry ◄── checks needing the full text, locally ◄── validate ◄──┘
                    (account number on file)                (ai.validate)

The model is prompted in the bill's language, French or English, detected
locally from the full text (ai.language); the prompts themselves are static.

What never leaves: images, the raw text, and any personal field. The model
is not asked for the customer name or the account number at all: we don't
need it to model a building, and the account is checked locally.
"""

from __future__ import annotations

import logging
import re
from urllib.error import URLError

from django.conf import settings
from PIL import Image

from bills.ai import ground_truth
from bills.ai.client import LLMRequest, TextPart, get_llm_client
from bills.ai.language import detect_language
from bills.ai.prompt import SCHEMA, system_prompt
from bills.ai.validate import PARSER_NAME, InvalidModelOutput, validate
from bills.extraction.ocr import ocr_lines, pdf_page_images
from bills.privacy.guard import PersonalInfoEgressError
from bills.privacy.redact import redact_lines

from .base import DocumentInput, ParsedEntry

logger = logging.getLogger(__name__)

MIN_LINES = 5  # less than this: blank page, or not a bill


def document_lines(documents: list[DocumentInput]) -> list[str]:
    """All text lines of the documents, read locally. Personal info included."""
    lines: list[str] = []
    for document in documents:
        if document.text.strip():
            pages = [page.splitlines() for page in document.text.split("\f")]
        elif document.content_type == "application/pdf":
            pages = [ocr_lines(image) for image in pdf_page_images(document.path)]
        else:
            with Image.open(document.path) as image:
                pages = [ocr_lines(image)]
        for page in pages:
            if lines:
                lines.append("--- page ---")
            lines.extend(page)
    return lines


class ModelParser:
    name = PARSER_NAME

    def parse(self, documents: list[DocumentInput]) -> ParsedEntry | None:
        lines = document_lines(documents)
        if len([line for line in lines if line.strip()]) < MIN_LINES:
            return None
        known = documents[0].known_personal_info
        redacted = redact_lines(lines, known)
        # On the full text, locally: redaction removes most of the words that
        # tell the two languages apart.
        language = detect_language("\n".join(lines))
        logger.debug("Bill language: %s", language)
        request = LLMRequest(
            system=system_prompt(language), parts=[TextPart(redacted.text)], response_schema=SCHEMA,
        )
        try:
            print("Sending request to model:", request)
            answer = get_llm_client().complete(request, known_personal_info=known)
            result = validate(answer, redacted.text)
        except PersonalInfoEgressError:
            return None  # logged by the guard; a human enters this one
        except InvalidModelOutput as e:
            logger.warning("Model answer rejected: %s", e)
            return None
        except (URLError, TimeoutError, ConnectionError) as e:
            logger.warning("Model unavailable: %s", type(e).__name__)
            return None
        if result is None:
            return None
        if settings.AI_PROVIDER == "ground_truth":
            # Say so on the entry: these values were looked up, not extracted.
            result.parser_name = ground_truth.PARSER_NAME
            result.warnings.append(ground_truth.NOTE)

        # Local check, on the full text: is this the bill's account?
        on_file = re.sub(r"\D", "", documents[0].account_number_on_file)
        if on_file and on_file not in re.sub(r"\D", "", "\n".join(lines)):
            result.warnings.append("This bill's account number wasn't found on the document: right bill?")
        return result
