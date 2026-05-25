from __future__ import annotations

import django_filters as df
from django import forms

from apps.accounts.models import Client
from apps.datafy.models import Project

from .models import Board, Task


class TaskFilter(df.FilterSet):
    code = df.CharFilter(lookup_expr="icontains",
                         widget=forms.TextInput(attrs={"class": "form-control"}))
    title = df.CharFilter(lookup_expr="icontains",
                          widget=forms.TextInput(attrs={"class": "form-control",
                                                        "placeholder": "Buscar titulo..."}))
    status = df.MultipleChoiceFilter(choices=Task.Status.choices,
                                     widget=forms.SelectMultiple(attrs={"class": "form-select"}))
    priority = df.MultipleChoiceFilter(choices=Task.Priority.choices,
                                       widget=forms.SelectMultiple(attrs={"class": "form-select"}))
    client = df.ModelChoiceFilter(queryset=Client.objects.filter(is_active=True),
                                  widget=forms.Select(attrs={"class": "form-select"}))
    board = df.ModelChoiceFilter(queryset=Board.objects.filter(is_active=True),
                                 widget=forms.Select(attrs={"class": "form-select"}))
    project = df.ModelChoiceFilter(queryset=Project.objects.filter(is_active=True),
                                   widget=forms.Select(attrs={"class": "form-select"}))
    due_date = df.DateFromToRangeFilter(
        widget=df.widgets.RangeWidget(attrs={"class": "form-control datepicker", "type": "date"}),
        label="Prazo"
    )

    class Meta:
        model = Task
        fields = ["code", "title", "status", "priority", "client", "board", "project", "due_date"]
