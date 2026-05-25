from __future__ import annotations

import django_filters as df
from django import forms

from apps.accounts.models import Client

from .models import DataEntry, Indicator, IndicatorValue, Project


class DataEntryFilter(df.FilterSet):
    reference = df.CharFilter(lookup_expr="icontains",
                              widget=forms.TextInput(attrs={"class": "form-control"}))
    title = df.CharFilter(lookup_expr="icontains",
                          widget=forms.TextInput(attrs={"class": "form-control",
                                                        "placeholder": "Buscar titulo..."}))
    category = df.CharFilter(lookup_expr="icontains",
                             widget=forms.TextInput(attrs={"class": "form-control"}))
    status = df.MultipleChoiceFilter(choices=DataEntry.Status.choices,
                                     widget=forms.SelectMultiple(attrs={"class": "form-select"}))
    client = df.ModelChoiceFilter(queryset=Client.objects.filter(is_active=True),
                                  widget=forms.Select(attrs={"class": "form-select"}))
    project = df.ModelChoiceFilter(queryset=Project.objects.filter(is_active=True),
                                   widget=forms.Select(attrs={"class": "form-select"}))
    event_date = df.DateFromToRangeFilter(
        widget=df.widgets.RangeWidget(attrs={"class": "form-control datepicker", "type": "date"}),
        label="Periodo"
    )
    owner = df.CharFilter(lookup_expr="icontains",
                          widget=forms.TextInput(attrs={"class": "form-control"}))

    class Meta:
        model = DataEntry
        fields = ["reference", "title", "category", "status", "client", "project",
                  "event_date", "owner"]


class IndicatorValueFilter(df.FilterSet):
    indicator = df.ModelChoiceFilter(queryset=Indicator.objects.all(),
                                     widget=forms.Select(attrs={"class": "form-select"}))
    category = df.ChoiceFilter(field_name="indicator__category",
                               choices=Indicator.Category.choices,
                               widget=forms.Select(attrs={"class": "form-select"}))
    client = df.ModelChoiceFilter(field_name="indicator__client",
                                  queryset=Client.objects.filter(is_active=True),
                                  widget=forms.Select(attrs={"class": "form-select"}))
    period = df.DateFromToRangeFilter(
        widget=df.widgets.RangeWidget(attrs={"class": "form-control datepicker", "type": "date"}),
        label="Periodo"
    )

    class Meta:
        model = IndicatorValue
        fields = ["indicator", "category", "client", "period"]
