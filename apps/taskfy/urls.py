from django.urls import path

from . import views

app_name = "taskfy"

urlpatterns = [
    path("", views.home, name="home"),
    path("tarefas/", views.task_list, name="task_list"),
    path("tarefas/<int:pk>/", views.task_detail, name="task_detail"),
    path("kanban/", views.kanban, name="kanban"),
]
