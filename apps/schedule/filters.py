from __future__ import annotations

import django_filters as df
from django import forms

from apps.accounts.models import Client

from .models import Schedule, ScheduleEvent


class ScheduleEventFilter(df.FilterSet):
    title = df.CharFilter(lookup_expr="icontains",
                          widget=forms.TextInput(attrs={"class": "form-control"}))
    event_type = df.MultipleChoiceFilter(choices=ScheduleEvent.Type.choices,
                                         widget=forms.SelectMultiple(attrs={"class": "form-select"}))
    status = df.MultipleChoiceFilter(choices=ScheduleEvent.Status.choices,
                                     widget=forms.SelectMultiple(attrs={"class": "form-select"}))
    schedule = df.ModelChoiceFilter(queryset=Schedule.objects.filter(is_active=True),
                                    widget=forms.Select(attrs={"class": "form-select"}))
    client = df.ModelChoiceFilter(field_name="schedule__client",
                                  queryset=Client.objects.filter(is_active=True),
                                  widget=forms.Select(attrs={"class": "form-select"}))
    start_at = df.DateFromToRangeFilter(
        widget=df.widgets.RangeWidget(attrs={"class": "form-control datepicker", "type": "date"}),
        label="Periodo"
    )

    class Meta:
        model = ScheduleEvent
        fields = ["title", "event_type", "status", "schedule", "client", "start_at"]
