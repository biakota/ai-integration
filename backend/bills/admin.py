from django.contrib import admin

from .models import Bill, BillDocument, BillEntry, Building


class BillInline(admin.TabularInline):
    model = Bill
    extra = 0


class BillEntryInline(admin.TabularInline):
    model = BillEntry
    extra = 0
    fields = ["start_billing_period", "end_billing_period", "consumption", "billed_power", "bill_cost", "source", "status"]


class BillDocumentInline(admin.TabularInline):
    model = BillDocument
    extra = 0


@admin.register(Building)
class BuildingAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "address", "owner"]
    inlines = [BillInline]


@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "building", "utility", "consumption_unit"]
    list_filter = ["utility"]
    inlines = [BillEntryInline]


@admin.register(BillEntry)
class BillEntryAdmin(admin.ModelAdmin):
    list_display = ["id", "bill", "start_billing_period", "end_billing_period", "consumption", "bill_cost", "source", "status"]
    list_filter = ["source", "status"]
    inlines = [BillDocumentInline]
