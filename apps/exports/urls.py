from django.urls import path

from . import views

app_name = "exports"

urlpatterns = [
    path("historico/", views.history, name="history"),
]
