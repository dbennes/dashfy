from __future__ import annotations

import json

import pandas as pd
import plotly.express as px
from django.db.models import Count
import plotly.io as pio


def _figure(fig) -> dict:
    payload = json.loads(pio.to_json(fig, validate=False, pretty=False))
    return {"data": payload["data"], "layout": payload["layout"]}


def _empty(msg="Sem dados") -> dict:
    return {
        "data": [],
        "layout": {
            "annotations": [{"text": msg, "xref": "paper", "yref": "paper",
                             "x": 0.5, "y": 0.5, "showarrow": False,
                             "font": {"size": 14, "color": "#888"}}],
            "xaxis": {"visible": False}, "yaxis": {"visible": False}, "height": 280,
        }
    }


def chart_by_status(qs) -> dict:
    data = list(qs.values("status").annotate(n=Count("id")))
    if not data:
        return _empty()
    df = pd.DataFrame(data)
    fig = px.pie(df, names="status", values="n", hole=0.55)
    fig.update_traces(textposition="inside", textinfo="percent+label")
    return _figure(fig)


def chart_by_priority(qs) -> dict:
    data = list(qs.values("priority").annotate(n=Count("id")))
    if not data:
        return _empty()
    df = pd.DataFrame(data)
    order = ["low", "medium", "high", "critical"]
    df["priority"] = pd.Categorical(df["priority"], categories=order, ordered=True)
    df = df.sort_values("priority")
    fig = px.bar(df, x="priority", y="n", color="priority",
                 color_discrete_map={"low": "#0dcaf0", "medium": "#ffc107",
                                     "high": "#fd7e14", "critical": "#dc3545"})
    fig.update_layout(xaxis_title="Prioridade", yaxis_title="Tarefas", showlegend=False)
    return _figure(fig)


def chart_burndown(qs) -> dict:
    data = list(qs.values("due_date", "status"))
    if not data:
        return _empty()
    df = pd.DataFrame(data).dropna(subset=["due_date"])
    if df.empty:
        return _empty()
    df["due_date"] = pd.to_datetime(df["due_date"])
    by_day = df.groupby("due_date").size().reset_index(name="planned")
    by_day["acumulado"] = by_day["planned"].cumsum()
    fig = px.line(by_day, x="due_date", y="acumulado", markers=True,
                  title=None)
    fig.update_layout(xaxis_title="Prazo", yaxis_title="Acumulado")
    return _figure(fig)


def chart_assignee_load(qs) -> dict:
    data = list(qs.exclude(assignee__isnull=True)
                  .values("assignee__username")
                  .annotate(n=Count("id")).order_by("-n")[:10])
    if not data:
        return _empty()
    df = pd.DataFrame(data)
    fig = px.bar(df, x="n", y="assignee__username", orientation="h",
                 color="n", color_continuous_scale="Tealrose")
    fig.update_layout(xaxis_title="Tarefas", yaxis_title=None,
                      yaxis={"categoryorder": "total ascending"})
    return _figure(fig)
