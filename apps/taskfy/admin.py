from django.contrib import admin

from .models import Board, Task, TaskComment


@admin.register(Board)
class BoardAdmin(admin.ModelAdmin):
    list_display = ("name", "client", "is_active", "updated_at")
    list_filter = ("client", "is_active")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "client", "board", "status", "priority",
                    "assignee", "due_date", "progress")
    list_filter = ("status", "priority", "client", "board")
    search_fields = ("code", "title")
    date_hierarchy = "due_date"
    autocomplete_fields = ("assignee", "reporter", "project")


@admin.register(TaskComment)
class TaskCommentAdmin(admin.ModelAdmin):
    list_display = ("task", "author", "created_at")
    search_fields = ("body",)
