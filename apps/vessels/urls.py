from django.urls import path

from . import views


app_name = "vessels"

urlpatterns = [
    path("api/vessels/", views.VesselListView.as_view(), name="api_vessels"),
    path("api/vessels/export/", views.VesselExportView.as_view(), name="api_export"),
    path("api/vessels/import/", views.VesselImportView.as_view(), name="api_import"),
    path("api/vessels/<int:pk>/", views.VesselDetailView.as_view(), name="api_vessel"),
    path("api/vessels/<int:pk>/positions/", views.VesselPositionsView.as_view(), name="api_positions"),
    path("api/vessels/<int:pk>/positions/export/", views.VesselTrackExportView.as_view(), name="api_positions_export"),
    path("api/vessels/<int:pk>/latest/", views.VesselLatestView.as_view(), name="api_latest"),
    path("api/containers/", views.VesselContainersView.as_view(), name="api_containers"),
    path("api/shipments/<int:pk>/items/", views.VesselShipmentItemsView.as_view(), name="api_shipment_items"),
    path("api/status/", views.VesselStatusView.as_view(), name="api_status"),
]
