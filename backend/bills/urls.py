from django.urls import path

from . import views

urlpatterns = [
    path("buildings/", views.BuildingListView.as_view(), name="buildings-list"),
    path("buildings/<int:pk>/", views.BuildingDetailView.as_view(), name="buildings-detail"),
    path("buildings/<int:pk>/bills/", views.BillCreateView.as_view(), name="bills-create"),
    path("bills/<int:pk>/", views.BillDetailView.as_view(), name="bills-detail"),
    path("bills/<int:pk>/entries/", views.BillEntryCreateView.as_view(), name="entries-create"),
    path("bills/<int:pk>/upload/", views.BillUploadView.as_view(), name="bills-upload"),
    path("entries/<int:pk>/", views.BillEntryDetailView.as_view(), name="entries-detail"),
]
