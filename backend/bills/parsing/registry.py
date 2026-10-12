import logging

from .base import BillParser, DocumentInput, ParsedEntry
from .hydroquebec import HydroQuebecPdfParser
from .model import ModelParser

# Tried in order; the first parser that returns a result wins.
PARSERS: list[BillParser] = [
    HydroQuebecPdfParser(),
    ModelParser(),  # last: everything the deterministic parsers declined
]


logger = logging.getLogger(__name__)


def parse(documents: list[DocumentInput]) -> ParsedEntry | None:
    for parser in PARSERS:
        try:
            result = parser.parse(documents)
        except Exception:
            # A crashing parser must not block the next one, nor the upload.
            # Exception type and stack only: never the document text.
            logger.exception("Parser %s failed", parser.name)
            continue
        if result is not None:
            return result
    return None
