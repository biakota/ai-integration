import logging
from pathlib import Path

from django.core.files.storage import default_storage
from django.db import transaction

from .models import Bill, BillDocument, BillEntry, Building
from .parsing.base import DocumentInput, ParsedEntry
from .parsing.registry import parse
from .parsing.text import extract_pdf_text
from .parsing.values import digits_only

logger = logging.getLogger(__name__)

ENTRY_FIELDS = [
    "parser_name", "confidence",
    "start_billing_period", "end_billing_period", "consumption", "billed_power", "bill_cost",
]
# Copied onto the bill only when it doesn't have them yet.
BILL_FIELDS = ["account_number", "customer_name", "rate_code"]


def process_upload(entry: BillEntry) -> BillEntry:
    """Run the parsers over a freshly uploaded entry's documents."""
    known = known_personal_info(entry)
    inputs = []
    for document in entry.documents.all():
        path = Path(document.file.path)
        text = ""
        if document.content_type == "application/pdf":
            text = extract_pdf_text(path)
            print(f"Extracted:: {text} chars from PDF {path}")
        document.raw_text = text
        document.save(update_fields=["raw_text"])
        # Size only: the text is the whole bill, personal information included,
        # and logs end up in places (log shippers, error trackers) we don't control.
        logger.debug("Extracted %d chars from document %s (entry %s)", len(text), document.pk, entry.pk)
        inputs.append(DocumentInput(
            path=path,
            content_type=document.content_type,
            filename=document.original_filename,
            text=text,
            known_personal_info=known,
            account_number_on_file=entry.bill.account_number,
        ))

    result = parse(inputs)
    if result is None:
        logger.info("No parser matched entry %s", entry.pk)
        entry.status = BillEntry.Status.UNPARSED
    else:
        notes = list(result.warnings) + check_against_bill(entry, result)
        for name in ENTRY_FIELDS:
            setattr(entry, name, getattr(result, name))
        entry.source = result.source
        entry.review_notes = notes
        entry.status = (
            BillEntry.Status.NEEDS_REVIEW if result.needs_review or notes else BillEntry.Status.PARSED
        )
        bill = entry.bill
        for name in BILL_FIELDS:
            if not getattr(bill, name) and getattr(result, name):
                setattr(bill, name, getattr(result, name))
        bill.save()
        # ParsedEntry's repr leaves out the personal fields.
        logger.info("Entry %s parsed by %s: %s", entry.pk, result.parser_name, result)
    entry.save()
    return entry


DOCUMENT_LOOKUPS = {Building: "entry__bill__building", Bill: "entry__bill", BillEntry: "entry"}


def delete_with_documents(obj: Building | Bill | BillEntry) -> None:
    """Delete a building, a bill or an entry, everything under it, and the uploaded files.

    The rows cascade; the files don't, and they are the whole bill, personal
    information included: they must not outlive the entry they belong to.
    """
    lookup = DOCUMENT_LOOKUPS[type(obj)]
    names = list(BillDocument.objects.filter(**{lookup: obj}).values_list("file", flat=True))
    with transaction.atomic():
        obj.delete()
        # Only once the rows are really gone: a rollback must not leave
        # documents pointing at missing files.
        transaction.on_commit(lambda: [default_storage.delete(name) for name in names if name])


def known_personal_info(entry: BillEntry) -> list[str]:
    """Personal information we already hold about this entry's bill."""
    bill, building = entry.bill, entry.bill.building
    owner = building.owner
    values = [
        bill.customer_name, bill.account_number, building.address,
        owner.get_full_name(), owner.email,
    ]
    return [v for v in values if v]


def check_against_bill(entry: BillEntry, result: ParsedEntry) -> list[str]:
    """Checks that need the bill the document was uploaded to, whatever the parser."""
    bill, notes = entry.bill, []
    if bill.account_number and result.account_number and (
        digits_only(bill.account_number) != digits_only(result.account_number)
    ):
        notes.append("This document's account number doesn't match the bill's: uploaded to the wrong bill?")
    if result.consumption_unit and result.consumption_unit != bill.consumption_unit:
        notes.append(
            f"Document is billed in {result.consumption_unit}, this bill in {bill.consumption_unit}."
        )
    start, end = result.start_billing_period, result.end_billing_period
    if start and end:
        overlapping = bill.entries.exclude(pk=entry.pk).filter(
            start_billing_period__lt=end, end_billing_period__gt=start
        )
        if overlapping.exists():
            notes.append("Overlaps an existing entry of this bill: duplicate upload?")
    return notes
