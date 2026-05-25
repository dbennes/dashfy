from __future__ import annotations

import django_filters as df
from django import forms

from apps.accounts.models import Client

from .models import Document


class DocumentFilter(df.FilterSet):
    code = df.CharFilter(lookup_expr="icontains",
                         widget=forms.TextInput(attrs={"class": "form-control"}))
    title = df.CharFilter(lookup_expr="icontains",
                          widget=forms.TextInput(attrs={"class": "form-control",
                                                        "placeholder": "Titulo..."}))
    category = df.CharFilter(lookup_expr="icontains",
                             widget=forms.TextInput(attrs={"class": "form-control"}))
    document_type = df.CharFilter(lookup_expr="icontains",
                                  widget=forms.TextInput(attrs={"class": "form-control"}))
    status = df.MultipleChoiceFilter(choices=Document.Status.choices,
                                     widget=forms.SelectMultiple(attrs={"class": "form-select"}))
    client = df.ModelChoiceFilter(queryset=Client.objects.filter(is_active=True),
                                  widget=forms.Select(attrs={"class": "form-select"}))
    issued_at = df.DateFromToRangeFilter(
        widget=df.widgets.RangeWidget(attrs={"class": "form-control datepicker", "type": "date"}),
        label="Emissao"
    )

    class Meta:
        model = Document
        fields = ["code", "title", "category", "document_type", "status", "client", "issued_at"]
