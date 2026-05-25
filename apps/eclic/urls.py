from django.urls import path

from . import views

app_name = "eclic"

urlpatterns = [
    path("", views.home, name="home"),
    path("documentos/", views.document_list, name="document_list"),
    path("documentos/<int:pk>/", views.document_detail, name="document_detail"),
    path("sync/", views.sync_now, name="sync_now"),
    path("sync/historico/", views.sync_history, name="sync_history"),
]
