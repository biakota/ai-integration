import logging

from django.db import transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Bill, BillDocument, BillEntry, Building
from .serializers import (
    BillEntryDetailSerializer,
    BillEntrySerializer,
    BillEntryWriteSerializer,
    BillSerializer,
    BillUploadSerializer,
    BuildingDetailSerializer,
    BuildingListSerializer,
)
from .services import delete_with_documents, process_upload

logger = logging.getLogger(__name__)


class BuildingListView(generics.ListCreateAPIView):
    """GET: the current user's buildings (all of them for staff), with a summary of
    their bills. POST: create a building owned by the current user."""

    serializer_class = BuildingListSerializer

    def get_queryset(self):
        buildings = Building.objects.prefetch_related("bills__entries")
        if self.request.user.is_staff:
            return buildings
        return buildings.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class BuildingDetailView(generics.RetrieveDestroyAPIView):
    """GET: a building with all its bills and their entries. DELETE: remove it,
    with its bills, their entries and the uploaded documents (owner or staff only)."""

    serializer_class = BuildingDetailSerializer

    def get_queryset(self):
        buildings = Building.objects.prefetch_related("bills__entries__documents")
        # Deleting is restricted to the owner; anyone else gets a 404.
        if self.request.method == "DELETE" and not self.request.user.is_staff:
            return buildings.filter(owner=self.request.user)
        return buildings

    def perform_destroy(self, instance):
        logger.info("Building %s deleted by %s", instance.pk, self.request.user)
        delete_with_documents(instance)


class BillDetailView(generics.DestroyAPIView):
    """Remove a bill, with its entries and the uploaded documents (owner or staff only)."""

    def get_queryset(self):
        if self.request.user.is_staff:
            return Bill.objects.all()
        return Bill.objects.filter(building__owner=self.request.user)

    def perform_destroy(self, instance):
        logger.info("Bill %s deleted by %s", instance.pk, self.request.user)
        delete_with_documents(instance)


class BillCreateView(generics.CreateAPIView):
    """Add a bill (a utility account) to a building."""

    serializer_class = BillSerializer

    def perform_create(self, serializer):
        serializer.save(building=get_object_or_404(Building, pk=self.kwargs["pk"]))


class BillEntryCreateView(generics.CreateAPIView):
    """Enter a billing period manually."""

    serializer_class = BillEntryWriteSerializer

    def perform_create(self, serializer):
        serializer.save(
            bill=get_object_or_404(Bill, pk=self.kwargs["pk"]),
            source=BillEntry.Source.MANUAL,
            status=BillEntry.Status.CONFIRMED,
        )


class BillEntryDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET: one entry with its documents. PUT/PATCH: correct and confirm it.
    DELETE: remove it, with its uploaded documents (owner or staff only)."""

    def get_queryset(self):
        entries = BillEntry.objects.select_related("bill__building").prefetch_related("documents")
        # Deleting is restricted to the owner; anyone else gets a 404.
        if self.request.method == "DELETE" and not self.request.user.is_staff:
            return entries.filter(bill__building__owner=self.request.user)
        return entries

    def perform_destroy(self, instance):
        logger.info("Entry %s deleted by %s", instance.pk, self.request.user)
        delete_with_documents(instance)

    def get_serializer_class(self):
        return BillEntryDetailSerializer if self.request.method == "GET" else BillEntryWriteSerializer

    def perform_update(self, serializer):
        serializer.save(status=BillEntry.Status.CONFIRMED)


class BillUploadView(APIView):
    """Upload one bill (one PDF, or one image per page) and try to read it into a new entry."""

    parser_classes = [MultiPartParser]

    @extend_schema(request=BillUploadSerializer, responses={201: BillEntrySerializer})
    def post(self, request, pk):
        bill = get_object_or_404(Bill, pk=pk)
        serializer = BillUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        files = serializer.validated_data["files"]
        logger.info(
            "Upload by %s to bill %s: %s", request.user, bill.pk, ", ".join(f.name for f in files)
        )

        with transaction.atomic():
            entry = BillEntry.objects.create(bill=bill)
            for f in files:
                BillDocument.objects.create(
                    entry=entry,
                    file=f,
                    original_filename=f.name,
                    content_type=f.detected_content_type,
                    size_bytes=f.size,
                )
        entry = process_upload(entry)
        return Response(
            BillEntrySerializer(entry, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )
