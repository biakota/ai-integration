from rest_framework import serializers

from .models import Bill, BillDocument, BillEntry, Building

PENDING_STATUSES = {BillEntry.Status.UNPARSED, BillEntry.Status.NEEDS_REVIEW}


class BillDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = BillDocument
        fields = ["id", "file", "original_filename", "content_type", "size_bytes", "uploaded_at"]


class BillEntrySerializer(serializers.ModelSerializer):
    documents = BillDocumentSerializer(many=True, read_only=True)

    class Meta:
        model = BillEntry
        fields = [
            "id", "bill", "source", "status", "parser_name", "confidence", "review_notes",
            "start_billing_period", "end_billing_period",
            "consumption", "billed_power", "bill_cost",
            "documents", "created_at", "updated_at",
        ]
        read_only_fields = [
            "bill", "source", "status", "parser_name", "confidence", "review_notes",
            "created_at", "updated_at",
        ]


class BillEntryWriteSerializer(BillEntrySerializer):
    """Manual entry, and a human confirming/correcting an extracted entry."""

    class Meta(BillEntrySerializer.Meta):
        extra_kwargs = {
            name: {"required": True, "allow_null": False}
            for name in ["start_billing_period", "end_billing_period", "consumption", "bill_cost"]
        }

    def validate(self, attrs):
        start, end = attrs.get("start_billing_period"), attrs.get("end_billing_period")
        if start and end and end <= start:
            raise serializers.ValidationError(
                {"end_billing_period": "Must be after start_billing_period (end is exclusive)."}
            )
        return attrs


class BillSerializer(serializers.ModelSerializer):
    entries = BillEntrySerializer(many=True, read_only=True)

    class Meta:
        model = Bill
        fields = [
            "id", "building", "name", "utility", "consumption_unit",
            "account_number", "customer_name", "rate_code", "entries",
        ]
        read_only_fields = ["building"]


class BillSummarySerializer(serializers.ModelSerializer):
    entry_count = serializers.SerializerMethodField()
    pending_count = serializers.SerializerMethodField()

    class Meta:
        model = Bill
        fields = ["id", "name", "utility", "consumption_unit", "entry_count", "pending_count"]

    def get_entry_count(self, obj) -> int:
        return len(obj.entries.all())

    def get_pending_count(self, obj) -> int:
        return sum(1 for e in obj.entries.all() if e.status in PENDING_STATUSES)


class BuildingListSerializer(serializers.ModelSerializer):
    bills = BillSummarySerializer(many=True, read_only=True)

    class Meta:
        model = Building
        fields = ["id", "name", "address", "bills"]


class BuildingDetailSerializer(serializers.ModelSerializer):
    bills = BillSerializer(many=True, read_only=True)

    class Meta:
        model = Building
        fields = ["id", "name", "address", "bills"]


class BillContextSerializer(serializers.ModelSerializer):
    building_id = serializers.IntegerField(source="building.id", read_only=True)
    building_name = serializers.CharField(source="building.name", read_only=True)

    class Meta:
        model = Bill
        fields = ["id", "name", "utility", "consumption_unit", "building_id", "building_name"]


class BillEntryDetailSerializer(BillEntrySerializer):
    """An entry with enough context about its bill and building for the review page."""

    bill = BillContextSerializer(read_only=True)


MAX_FILES = 10
MAX_FILE_SIZE = 15 * 1024 * 1024

# Detected from the file's first bytes; the client-sent content type isn't trusted.
SIGNATURES = {
    b"%PDF-": "application/pdf",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
}


def detect_content_type(upload):
    head = upload.read(8)
    upload.seek(0)
    for signature, content_type in SIGNATURES.items():
        if head.startswith(signature):
            return content_type
    return None


class BillUploadSerializer(serializers.Serializer):
    files = serializers.ListField(
        child=serializers.FileField(),
        allow_empty=False,
        max_length=MAX_FILES,
        help_text=f"One PDF, or one image per page (PNG / JPEG). Max {MAX_FILES} files, "
                  f"{MAX_FILE_SIZE // (1024 * 1024)} MB each.",
    )

    def validate_files(self, files):
        for f in files:
            if f.size > MAX_FILE_SIZE:
                raise serializers.ValidationError(f"{f.name}: larger than {MAX_FILE_SIZE // (1024 * 1024)} MB.")
            f.detected_content_type = detect_content_type(f)
            if f.detected_content_type is None:
                raise serializers.ValidationError(f"{f.name}: only PDF, PNG and JPEG files are accepted.")
        if len(files) > 1 and any(f.detected_content_type == "application/pdf" for f in files):
            raise serializers.ValidationError("Upload a single PDF, or one image per page.")
        return files
