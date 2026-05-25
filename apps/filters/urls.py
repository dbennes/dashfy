from django.urls import path

from . import views

app_name = "filters"

urlpatterns = [
    path("", views.saved_views, name="saved_views"),
    path("save/", views.save_view, name="save_view"),
    path("<int:pk>/delete/", views.delete_view, name="delete_view"),
]
