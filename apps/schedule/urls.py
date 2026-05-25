from django.urls import path

from . import views

app_name = "schedule"

urlpatterns = [
    path("", views.home, name="home"),
    path("calendario/", views.calendar, name="calendar"),
    path("calendario/eventos.json", views.calendar_events, name="calendar_events"),
    path("eventos/", views.event_list, name="event_list"),
    path("eventos/<int:pk>/", views.event_detail, name="event_detail"),
]
