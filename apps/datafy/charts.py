"""
Construtores de payloads Plotly (JSON serializavel) para o frontend.
Mantemos a logica de grafico isolada para reutilizar nos exports/PDF.
"""
from __future__ import annotations

import json

import pandas as pd
import plotly.express as px
import plotly.io as pio


def df_to_payload(fig) -> dict:
    """Converte uma figura Plotly para JSON serializavel."""
    return {
        "data": pio.to_json(fig, validate=False, pretty=False),
    }


def chart_entries_by_status(qs) -> dict:
    df = pd.DataFrame(list(qs.values("status").annotate(n=_count("id"))))
    if df.empty:
        return _empty("Nenhum registro para o filtro selecionado.")
    fig = px.pie(df, names="status", values="n", hole=0.55, title=None)
    fig.update_traces(textposition="inside", textinfo="percent+label")
    return _figure(fig)


def chart_entries_by_month(qs) -> dict:
    df = pd.DataFrame(list(qs.values("event_date", "status")))
    if df.empty:
        return _empty()
    df["month"] = pd.to_datetime(df["event_date"]).dt.to_period("M").dt.to_timestamp()
    grouped = df.groupby(["month", "status"]).size().reset_index(name="n")
    fig = px.bar(grouped, x="month", y="n", color="status", barmode="stack")
    fig.update_layout(xaxis_title="Mes", yaxis_title="Registros")
    return _figure(fig)


def chart_indicator_trend(values_qs) -> dict:
    df = pd.DataFrame(list(values_qs.values("period", "value", "indicator__name", "indicator__target")))
    if df.empty:
        return _empty()
    df["period"] = pd.to_datetime(df["period"])
    df["value"] = df["value"].astype(float)
    fig = px.line(df, x="period", y="value", color="indicator__name", markers=True)
    if df["indicator__target"].notna().any():
        target = float(df["indicator__target"].dropna().iloc[0])
        fig.add_hline(y=target, line_dash="dash", annotation_text="Meta",
                      annotation_position="top right")
    fig.update_layout(xaxis_title="Periodo", yaxis_title="Valor")
    return _figure(fig)


def chart_top_categories(qs, top_n: int = 8) -> dict:
    df = pd.DataFrame(list(qs.values("category").annotate(n=_count("id"))))
    if df.empty:
        return _empty()
    df = df.sort_values("n", ascending=False).head(top_n)
    fig = px.bar(df, x="n", y="category", orientation="h", color="n",
                 color_continuous_scale="Sunset")
    fig.update_layout(xaxis_title="Quantidade", yaxis_title=None,
                      yaxis={"categoryorder": "total ascending"})
    return _figure(fig)


# --------- helpers ----------
def _count(field):
    from django.db.models import Count
    return Count(field)


def _figure(fig) -> dict:
    payload = json.loads(pio.to_json(fig, validate=False, pretty=False))
    return {"data": payload["data"], "layout": payload["layout"]}


def _empty(message: str = "Sem dados") -> dict:
    return {
        "data": [],
        "layout": {
            "annotations": [{
                "text": message, "xref": "paper", "yref": "paper",
                "showarrow": False, "font": {"size": 14, "color": "#888"},
                "x": 0.5, "y": 0.5,
            }],
            "xaxis": {"visible": False},
            "yaxis": {"visible": False},
            "height": 280,
        },
    }
