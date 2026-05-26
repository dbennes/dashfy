from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home_view, name="home"),
    path("search/", views.search_view, name="search"),
    path("p6-curves/import/", views.import_p6_curves_view, name="import_p6_curves"),
    path("engineering-status/import/", views.import_engineering_status_view, name="import_engineering_status"),
    path("engineering-status/export/", views.export_engineering_status_view, name="export_engineering_status"),
    path("datafy-supply/refresh/", views.refresh_datafy_supply_view, name="refresh_datafy_supply"),
    path("datafy-supply/material-rows/", views.material_rows_page_view, name="material_rows_page"),
    path("datafy-supply/material-items-3d/", views.material_items_3d_view, name="material_items_3d"),
    path("model-node/<int:node_id>.glb", views.model_node_glb, name="model_node_glb"),
]
