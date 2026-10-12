import calendar
import math
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from bills.models import Bill, BillEntry, Building

User = get_user_model()

# Obviously fictional buildings, people and accounts. Each bill gets one year of confirmed,
# manually-entered entries: 6 bimonthly periods for electricity, 12 monthly
# periods for gas.
SEED = {
    "alice": [
        {
            "name": "Résidence Exemple",
            "address": "100, rue Volt, Laprise QC L1A 3H6",
            "bills": [
                dict(name="Électricité", utility="hydro_quebec", consumption_unit="kWh",
                     account_number="299000000101", customer_name="Alice Test", rate_code="D",
                     start=date(2024, 5, 10), months=2, periods=6, base=2600, swing=1500, unit_price="0.0850", daily="0.4615"),
                dict(name="Gaz naturel", utility="gaz_boreal", consumption_unit="m3",
                     account_number="0000000101", customer_name="Alice Test", rate_code="Tarif D1",
                     start=date(2024, 5, 3), months=1, periods=12, base=220, swing=190, unit_price="0.5716", daily="0.4520"),
            ],
        },
        {
            "name": "Plex Démo",
            "address": "200, avenue Ampère, Laprise QC L1A 3H9",
            "bills": [
                dict(name="Électricité", utility="hydro_quebec", consumption_unit="kWh",
                     account_number="299000000102", customer_name="Alice Test", rate_code="D",
                     start=date(2024, 6, 2), months=2, periods=6, base=3900, swing=2600, unit_price="0.0850", daily="0.4615"),
            ],
        },
    ],
    "bob": [
        {
            "name": "Chalet Fictif",
            "address": "300, chemin du Compteur, Saint-Exemple QC J0J 1T0",
            "bills": [
                dict(name="Électricité", utility="hydro_quebec", consumption_unit="kWh",
                     account_number="299000000201", customer_name="Bob Test", rate_code="D",
                     start=date(2024, 4, 30), months=2, periods=6, base=4800, swing=3400, unit_price="0.0850", daily="0.4615"),
            ],
        },
    ],
}


def add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year, month = d.year + month // 12, month % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def seasonal(base: int, swing: int, mid: date) -> Decimal:
    # Peaks mid-January, bottoms mid-July.
    phase = 2 * math.pi * (mid - date(mid.year, 1, 15)).days / 365
    return Decimal(round(base + swing * math.cos(phase)))


class Command(BaseCommand):
    help = "Seeds the database with users, buildings, bills and a year of bill entries."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("Clearing existing data...")
        Building.objects.all().delete()
        User.objects.exclude(is_superuser=True).delete()

        users_spec = [
            {"username": "admin", "is_staff": True,  "is_superuser": True},
            {"username": "alice", "is_staff": False, "is_superuser": False},
            {"username": "bob",   "is_staff": False, "is_superuser": False},
        ]
        for spec in users_spec:
            user, _ = User.objects.get_or_create(username=spec["username"])
            user.is_staff = spec["is_staff"]
            user.is_superuser = spec["is_superuser"]
            user.set_password("takehome")
            user.save()
            for building_spec in SEED.get(user.username, []):
                building = Building.objects.create(
                    owner=user, name=building_spec["name"], address=building_spec["address"]
                )
                for bill_spec in building_spec["bills"]:
                    self._make_bill(building, dict(bill_spec))
            self.stdout.write(f"  user: {user.username} (id={user.id}, admin={user.is_staff})")

        self.stdout.write(self.style.SUCCESS(
            f"Done. {User.objects.count()} users, {Building.objects.count()} buildings, "
            f"{Bill.objects.count()} bills, {BillEntry.objects.count()} entries."
        ))

    def _make_bill(self, building, spec):
        start, months, periods = spec.pop("start"), spec.pop("months"), spec.pop("periods")
        base, swing = spec.pop("base"), spec.pop("swing")
        unit_price, daily = Decimal(spec.pop("unit_price")), Decimal(spec.pop("daily"))
        bill = Bill.objects.create(building=building, **spec)
        for _ in range(periods):
            end = add_months(start, months)
            days = (end - start).days
            consumption = seasonal(base, swing, start + timedelta(days=days // 2))
            BillEntry.objects.create(
                bill=bill,
                source=BillEntry.Source.MANUAL,
                status=BillEntry.Status.CONFIRMED,
                start_billing_period=start,
                end_billing_period=end,
                consumption=consumption,
                bill_cost=(consumption * unit_price + days * daily).quantize(Decimal("0.01")),
            )
            start = end
