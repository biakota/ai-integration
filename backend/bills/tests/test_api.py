import shutil
import tempfile
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from bills.models import Bill, BillDocument, BillEntry, Building

User = get_user_model()

TMP_MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TMP_MEDIA, AI_PROVIDER="fake")
class BillsApiTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP_MEDIA, ignore_errors=True)

    def setUp(self):
        self.alice = User.objects.create(username="alice")
        self.client = APIClient()
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {Token.objects.create(user=self.alice).key}"
        )
        self.building = Building.objects.create(
            owner=self.alice, name="Résidence Exemple", address="100, rue Volt, Laprise QC"
        )
        self.bill = Bill.objects.create(
            building=self.building, name="Électricité", utility="hydro_quebec", consumption_unit="kWh"
        )

    def upload(self, *paths):
        files = [
            SimpleUploadedFile(p.name, p.read_bytes())
            for p in (settings.SAMPLES_DIR / path for path in paths)
        ]
        return self.client.post(
            f"/api/bills/{self.bill.pk}/upload/", {"files": files}, format="multipart"
        )

    def test_building_list_shows_own_buildings_only(self):
        bob = User.objects.create(username="bob")
        Building.objects.create(owner=bob, name="Chalet Fictif", address="300, chemin du Compteur")
        response = self.client.get("/api/buildings/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([b["name"] for b in response.data], ["Résidence Exemple"])

    def test_building_list_shows_all_buildings_to_staff(self):
        bob = User.objects.create(username="bob")
        Building.objects.create(owner=bob, name="Chalet Fictif", address="300, chemin du Compteur")
        admin = User.objects.create(username="admin", is_staff=True)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {Token.objects.create(user=admin).key}")
        response = self.client.get("/api/buildings/")
        self.assertEqual(len(response.data), 2)

    def test_create_building_is_owned_by_current_user(self):
        response = self.client.post(
            "/api/buildings/", {"name": "Duplex Test", "address": "400, rue du Test"}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["bills"], [])
        self.assertEqual(Building.objects.get(pk=response.data["id"]).owner, self.alice)

    def test_building_detail_nests_bills_and_entries(self):
        BillEntry.objects.create(
            bill=self.bill, source=BillEntry.Source.MANUAL, status=BillEntry.Status.CONFIRMED,
            start_billing_period=date(2025, 1, 10), end_billing_period=date(2025, 3, 11),
            consumption=Decimal("4210"), bill_cost=Decimal("446.12"),
        )
        response = self.client.get(f"/api/buildings/{self.building.pk}/")
        self.assertEqual(response.status_code, 200)
        [bill] = response.data["bills"]
        self.assertEqual(bill["utility"], "hydro_quebec")
        self.assertEqual(len(bill["entries"]), 1)
        self.assertEqual(bill["entries"][0]["consumption"], "4210.00")

    def test_manual_entry_is_confirmed(self):
        response = self.client.post(f"/api/bills/{self.bill.pk}/entries/", {
            "start_billing_period": "2025-01-10",
            "end_billing_period": "2025-03-11",
            "consumption": "4210",
            "bill_cost": "446.12",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        entry = BillEntry.objects.get()
        self.assertEqual(entry.bill, self.bill)
        self.assertEqual(entry.source, BillEntry.Source.MANUAL)
        self.assertEqual(entry.status, BillEntry.Status.CONFIRMED)
        self.assertEqual(entry.bill_cost, Decimal("446.12"))

    def test_manual_entry_rejects_inverted_period(self):
        response = self.client.post(f"/api/bills/{self.bill.pk}/entries/", {
            "start_billing_period": "2025-03-11",
            "end_billing_period": "2025-01-10",
            "consumption": "4210",
            "bill_cost": "446.12",
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("end_billing_period", response.data)

    def test_upload_without_parser_is_unparsed(self):
        # Originally used an Hydro-Québec PDF, which ticket 1 now reads; an
        # unrelated PDF keeps the intent (nothing can read it -> unparsed).
        response = self.upload("other-utilities/gaz-boreal-01.pdf")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["status"], BillEntry.Status.UNPARSED)
        self.assertEqual(len(response.data["documents"]), 1)

    def test_upload_rejects_unsupported_file_type(self):
        # Content type claimed by the client is ignored; the bytes are checked.
        upload = SimpleUploadedFile("bill.pdf", b"not really a pdf", content_type="application/pdf")
        response = self.client.post(
            f"/api/bills/{self.bill.pk}/upload/", {"files": [upload]}, format="multipart"
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(BillEntry.objects.exists())

    def test_upload_rejects_pdf_mixed_with_other_files(self):
        response = self.upload(
            "hydro-quebec/pdf/hq-01-rate-d-standard.pdf",
            "hydro-quebec/images/hq-01-rate-d-standard-p1.png",
        )
        self.assertEqual(response.status_code, 400)

    def test_delete_bill_removes_its_entries_only(self):
        BillEntry.objects.create(bill=self.bill)
        other = Bill.objects.create(building=self.building, name="Gaz", utility="gaz_boreal")
        response = self.client.delete(f"/api/bills/{self.bill.pk}/")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(list(Bill.objects.all()), [other])
        self.assertFalse(BillEntry.objects.exists())
        self.assertTrue(Building.objects.filter(pk=self.building.pk).exists())

    def test_delete_building_removes_its_bills(self):
        BillEntry.objects.create(bill=self.bill)
        response = self.client.delete(f"/api/buildings/{self.building.pk}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Building.objects.exists())
        self.assertFalse(Bill.objects.exists())
        self.assertFalse(BillEntry.objects.exists())

    def test_delete_removes_uploaded_files(self):
        self.upload("other-utilities/gaz-boreal-01.pdf")
        document = BillDocument.objects.get()
        storage, name = document.file.storage, document.file.name
        self.assertTrue(storage.exists(name))
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.delete(f"/api/buildings/{self.building.pk}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(BillDocument.objects.exists())
        self.assertFalse(storage.exists(name))

    def test_delete_entry_removes_only_that_entry_and_its_files(self):
        kept = BillEntry.objects.create(bill=self.bill)
        uploaded = self.upload("other-utilities/gaz-boreal-01.pdf").data["id"]
        document = BillDocument.objects.get()
        storage, name = document.file.storage, document.file.name
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.delete(f"/api/entries/{uploaded}/")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(list(BillEntry.objects.all()), [kept])
        self.assertFalse(storage.exists(name))
        self.assertTrue(Bill.objects.filter(pk=self.bill.pk).exists())

    def test_cannot_delete_someone_elses_entry(self):
        entry = BillEntry.objects.create(bill=self.bill)
        bob = User.objects.create(username="bob")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {Token.objects.create(user=bob).key}")
        self.assertEqual(self.client.delete(f"/api/entries/{entry.pk}/").status_code, 404)
        self.assertTrue(BillEntry.objects.filter(pk=entry.pk).exists())

    def test_cannot_delete_someone_elses_building_or_bill(self):
        bob = User.objects.create(username="bob")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {Token.objects.create(user=bob).key}")
        self.assertEqual(self.client.delete(f"/api/buildings/{self.building.pk}/").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/bills/{self.bill.pk}/").status_code, 404)
        self.assertTrue(Bill.objects.filter(pk=self.bill.pk).exists())

    def test_staff_can_delete_any_building_or_bill(self):
        admin = User.objects.create(username="admin", is_staff=True)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {Token.objects.create(user=admin).key}")
        self.assertEqual(self.client.delete(f"/api/bills/{self.bill.pk}/").status_code, 204)
        self.assertEqual(self.client.delete(f"/api/buildings/{self.building.pk}/").status_code, 204)

    def test_login_returns_token(self):
        self.alice.set_password("takehome")
        self.alice.save()
        response = APIClient().post(
            "/api/auth/login/", {"username": "alice", "password": "takehome"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("token", response.data)
