from django.conf import settings
from django.db import models


class Building(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="buildings"
    )
    name = models.CharField(max_length=200)
    address = models.CharField(max_length=300)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Bill(models.Model):
    """One utility account of a building — e.g. its Hydro-Québec electricity bill.

    The billing periods themselves are its entries (typically 6 bimonthly or
    12 monthly entries per year).
    """

    class Unit(models.TextChoices):
        KWH = "kWh", "kWh"
        M3 = "m3", "m³"

    building = models.ForeignKey(Building, on_delete=models.CASCADE, related_name="bills")
    name = models.CharField(max_length=200)
    utility = models.CharField(max_length=50)
    consumption_unit = models.CharField(max_length=5, choices=Unit.choices, default=Unit.KWH)
    account_number = models.CharField(max_length=32, blank=True)
    customer_name = models.CharField(max_length=200, blank=True)
    rate_code = models.CharField(max_length=30, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.building} — {self.name}"


class BillEntry(models.Model):
    """One billing period of a bill, entered manually or extracted from documents.

    The period and amounts are optional: an uploaded entry nobody could read
    yet exists with only its documents attached.
    """

    class Source(models.TextChoices):
        MANUAL = "manual", "Manual entry"
        DETERMINISTIC = "deterministic", "Deterministic parser"
        AI = "ai", "AI-assisted extraction"

    class Status(models.TextChoices):
        UNPARSED = "unparsed", "No parser could read it"
        NEEDS_REVIEW = "needs_review", "Extracted, needs human review"
        PARSED = "parsed", "Extracted"
        CONFIRMED = "confirmed", "Confirmed by a human"

    bill = models.ForeignKey(Bill, on_delete=models.CASCADE, related_name="entries")
    source = models.CharField(max_length=20, choices=Source.choices, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UNPARSED)
    parser_name = models.CharField(max_length=100, blank=True)
    confidence = models.FloatField(null=True, blank=True)
    review_notes = models.JSONField(
        default=list, blank=True,
        help_text="Why an extracted entry needs review: failed checks, dropped fields, ...",
    )

    start_billing_period = models.DateField(null=True, blank=True)
    end_billing_period = models.DateField(
        null=True,
        blank=True,
        help_text="Exclusive: a period billed from January 1st to January 31st ends on February 1st.",
    )
    consumption = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="In the bill's consumption unit.",
    )
    billed_power = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="[kW] Demand-billed accounts only.",
    )
    bill_cost = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Cost of the period before taxes.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [models.F("start_billing_period").asc(nulls_last=True), "pk"]
        verbose_name_plural = "bill entries"

    def __str__(self):
        return f"{self.bill}: {self.start_billing_period} → {self.end_billing_period} ({self.status})"


class BillDocument(models.Model):
    """One uploaded file (a PDF, or one photo/scan of a page) behind a bill entry."""

    entry = models.ForeignKey(BillEntry, on_delete=models.CASCADE, related_name="documents")
    file = models.FileField(upload_to="bills/")
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size_bytes = models.PositiveIntegerField()
    raw_text = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return self.original_filename
