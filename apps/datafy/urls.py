from django.urls import path

from . import views

app_name = "datafy"

urlpatterns = [
    path("", views.home, name="home"),
    path("registros/", views.entries_list, name="entries"),
    path("registros/<int:pk>/", views.entry_detail, name="entry_detail"),
    path("indicadores/", views.indicators, name="indicators"),
]
