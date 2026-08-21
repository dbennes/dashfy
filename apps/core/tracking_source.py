"""Trackfy (Taskfy) — dashboard de envios de container para a S04.

Le SOMENTE (select) as tabelas ``trackfy_conteiner`` / ``trackfy_shipment`` /
``trackfy_shipmentitem`` no PostgreSQL do Taskfy (``_taskfy_conn`` de
real_sources), replicando as metricas da tela Trackfy · Dashboard do projeto
``taskfy_3`` (``trackfy/view_main.py::trackfy_main``): frota de containers,
fluxo de envios, aging dos abertos, qualidade de recebimento por item e
lead time — apresentadas no design do cockpit.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

STATUS_LABELS = {
    "draft": "Draft",
    "sent": "Sent",
    "received": "Received",
    "cancelled": "Cancelled",
}

LOCATION_LABELS = {
    "onne": "ONNE",
    "aveon": "AVEON",
    "onboard_fpso": "On board FPSO",
    "onboard_flotel": "On board Flotel",
    "": "—",
}

CONDITION_LABELS = {
    "good": "Good condition",
    "damaged_minor": "Minor damages",
    "damaged_major": "Major damages",
    "": "—",
}


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _fmt_dt(value: Any) -> str:
    if isinstance(value, datetime):
        return timezone.localtime(value).strftime("%d/%m/%Y %H:%M") if timezone.is_aware(value) else value.strftime("%d/%m/%Y %H:%M")
    return "—"


def _month_key(value: datetime) -> str:
    return value.strftime("%Y-%m")


def _month_label(key: str) -> str:
    year, month = key.split("-")
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{names[int(month) - 1]}/{year[2:]}"


def _rows(cur, query: str, params: tuple = ()) -> list[dict]:
    cur.execute(query, params)
    return [dict(row) for row in cur.fetchall()]


def _scalar(cur, query: str, params: tuple = ()) -> Any:
    cur.execute(query, params)
    row = cur.fetchone()
    if row is None:
        return 0
    return list(dict(row).values())[0]


def tracking_dashboard() -> dict:
    """Payload da S04: KPIs, graficos e a tabela de envios do Trackfy."""
    from .real_sources import _taskfy_conn

    now = timezone.now()
    d7 = now - timedelta(days=7)
    d14 = now - timedelta(days=14)

    with _taskfy_conn() as conn:
        cur = conn.cursor()

        # ---------------- containers ----------------
        total_containers = int(_scalar(cur, "select count(*) from trackfy_conteiner"))
        containers_in_transit = int(_scalar(
            cur, "select count(*) from trackfy_conteiner where status ilike %s", ("In transit",)
        ))
        containers_available = int(_scalar(
            cur,
            "select count(*) from trackfy_conteiner where status ilike %s or status ilike %s",
            ("Available%", "On board%"),
        ))
        container_status_rows = _rows(
            cur,
            """
            select coalesce(nullif(trim(status), ''), 'No status') as label, count(*) as value
              from trackfy_conteiner
             group by 1
             order by value desc
            """,
        )

        # ---------------- shipments ----------------
        ship_by_status = {
            row["status"]: int(row["n"])
            for row in _rows(cur, "select status, count(*) as n from trackfy_shipment group by status")
        }
        total_shipments = sum(ship_by_status.values())
        shipments_sent = ship_by_status.get("sent", 0)
        shipments_received = ship_by_status.get("received", 0)
        shipments_open = ship_by_status.get("draft", 0) + ship_by_status.get("sent", 0)

        shipments_7d = int(_scalar(
            cur, "select count(*) from trackfy_shipment where created_at >= %s", (d7,)
        ))
        shipments_prev7d = int(_scalar(
            cur,
            "select count(*) from trackfy_shipment where created_at >= %s and created_at < %s",
            (d14, d7),
        ))
        trend_7d_pct = round(((shipments_7d - shipments_prev7d) / shipments_prev7d) * 100, 1) if shipments_prev7d else 0.0
        shipments_sent_7d = int(_scalar(
            cur, "select count(*) from trackfy_shipment where date_sent >= %s", (d7,)
        ))
        shipments_received_7d = int(_scalar(
            cur,
            "select count(*) from trackfy_shipment where status = 'received' and date_received >= %s",
            (d7,),
        ))

        # aging dos abertos (draft + sent), como na tela do Trackfy
        aging = _rows(
            cur,
            """
            select count(*) filter (where created_at >= %s) as lt7,
                   count(*) filter (where created_at < %s and created_at >= %s) as bt7_14,
                   count(*) filter (where created_at < %s) as gte15,
                   coalesce(avg(extract(epoch from (%s - created_at))), 0) as avg_secs
              from trackfy_shipment
             where status in ('draft', 'sent')
            """,
            (d7, d7, d14, d14, now),
        )[0]
        avg_open_age_days = round(float(aging["avg_secs"] or 0) / 86400.0, 1)

        # lead time medio (enviado -> recebido)
        avg_lead_days = float(_scalar(
            cur,
            """
            select coalesce(avg(extract(epoch from (date_received - date_sent))), 0) / 86400.0
              from trackfy_shipment
             where status = 'received'
               and date_sent is not null and date_received is not null
               and date_received > date_sent
            """,
        ))
        avg_lead_days = round(avg_lead_days, 2)

        # ---------------- itens ----------------
        item_stats = {"pending": 0, "ok": 0, "missing": 0, "damaged": 0}
        for row in _rows(
            cur,
            "select lower(coalesce(nullif(receive_status, ''), 'pending')) as k, count(*) as n from trackfy_shipmentitem group by 1",
        ):
            if row["k"] in item_stats:
                item_stats[row["k"]] = int(row["n"])
        items_total = sum(item_stats.values())

        def rate(part: int) -> float:
            return round((part / items_total) * 100, 1) if items_total else 0.0

        quality_index = max(0.0, min(100.0, round(100.0 - rate(item_stats["missing"]) - rate(item_stats["damaged"]), 1))) if items_total else 0.0

        issues_total = item_stats["missing"] + item_stats["damaged"]
        issues_7d = int(_scalar(
            cur,
            """
            select count(*)
              from trackfy_shipmentitem i
              join trackfy_shipment s on s.id = i.shipment_id
             where i.receive_status in ('missing', 'damaged') and s.created_at >= %s
            """,
            (d7,),
        ))
        recent_issues = _rows(
            cur,
            """
            select i.receive_status, i.material_code, i.material_description,
                   i.quantity, i.received_quantity, i.unit,
                   s.report_number, s.id as shipment_id, c.container_number
              from trackfy_shipmentitem i
              join trackfy_shipment s on s.id = i.shipment_id
              join trackfy_conteiner c on c.id = s.container_id
             where i.receive_status in ('missing', 'damaged')
             order by s.created_at desc
             limit 8
            """,
        )

        # ---------------- graficos ----------------
        monthly_sent = {
            str(row["k"]): int(row["n"])
            for row in _rows(
                cur,
                "select to_char(date_sent, 'YYYY-MM') as k, count(*) as n from trackfy_shipment where date_sent is not null group by 1",
            )
        }
        monthly_received = {
            str(row["k"]): int(row["n"])
            for row in _rows(
                cur,
                "select to_char(date_received, 'YYYY-MM') as k, count(*) as n from trackfy_shipment where date_received is not null group by 1",
            )
        }
        months = sorted(set(monthly_sent) | set(monthly_received))[-8:]

        # ---------------- envios ABERTOS (foco gerencial: o que cobrar) ----
        open_rows = _rows(
            cur,
            """
            select s.id, s.report_number, s.status, s.origin, s.destination,
                   s.date_sent, s.created_at,
                   c.container_number, c.owner,
                   (select count(*) from trackfy_shipmentitem i where i.shipment_id = s.id) as items_count
              from trackfy_shipment s
              join trackfy_conteiner c on c.id = s.container_id
             where s.status in ('draft', 'sent')
             order by s.created_at asc
            """,
        )

        # ---------------- recebidos recentes com lead time ----------------
        received_rows = _rows(
            cur,
            """
            select s.id, s.report_number, s.origin, s.destination,
                   s.date_sent, s.date_received, s.receive_location,
                   c.container_number, c.owner,
                   (select count(*) from trackfy_shipmentitem i where i.shipment_id = s.id) as items_count,
                   (select count(*) from trackfy_shipmentitem i
                     where i.shipment_id = s.id and i.receive_status in ('missing', 'damaged')) as issues_count
              from trackfy_shipment s
              join trackfy_conteiner c on c.id = s.container_id
             where s.status = 'received'
             order by s.date_received desc nulls last
             limit 10
            """,
        )

    open_shipments = []
    for row in open_rows:
        reference = row.get("date_sent") or row.get("created_at")
        days_open = int((now - reference).total_seconds() // 86400) if isinstance(reference, datetime) else 0
        status = str(row.get("status") or "")
        open_shipments.append({
            "id": row["id"],
            "report": row.get("report_number") or "—",
            "container": row.get("container_number") or "—",
            "owner": row.get("owner") or "—",
            "origin": row.get("origin") or "—",
            "destination": row.get("destination") or "—",
            "sent": _fmt_dt(row.get("date_sent")),
            "days_open": days_open,
            "items": int(row.get("items_count") or 0),
            "status": status,
            "status_label": STATUS_LABELS.get(status, status.title() or "—"),
        })

    recent_received = []
    for row in received_rows:
        sent_at, received_at = row.get("date_sent"), row.get("date_received")
        lead_days = None
        if isinstance(sent_at, datetime) and isinstance(received_at, datetime) and received_at > sent_at:
            lead_days = round((received_at - sent_at).total_seconds() / 86400, 1)
        recent_received.append({
            "id": row["id"],
            "report": row.get("report_number") or "—",
            "container": row.get("container_number") or "—",
            "origin": row.get("origin") or "—",
            "destination": row.get("destination") or "—",
            "received": _fmt_dt(received_at),
            "lead_days": lead_days,
            "items": int(row.get("items_count") or 0),
            "issues": int(row.get("issues_count") or 0),
        })

    issues = []
    for row in recent_issues:
        issues.append({
            "shipment_id": row.get("shipment_id"),
            "report": row.get("report_number") or "—",
            "container": row.get("container_number") or "—",
            "code": row.get("material_code") or "—",
            "description": row.get("material_description") or "—",
            "qty": float(row.get("quantity") or 0),
            "received_qty": float(row.get("received_quantity")) if row.get("received_quantity") is not None else None,
            "unit": row.get("unit") or "",
            "kind": str(row.get("receive_status") or ""),
        })

    charts = {
        "monthly": {
            "labels": [_month_label(key) for key in months],
            "sent": [monthly_sent.get(key, 0) for key in months],
            "received": [monthly_received.get(key, 0) for key in months],
        },
        "items": {
            "labels": ["OK", "Pending", "Missing", "Damaged"],
            "values": [item_stats["ok"], item_stats["pending"], item_stats["missing"], item_stats["damaged"]],
        },
        "containers": {
            "labels": [str(row["label"]) for row in container_status_rows],
            "values": [int(row["value"]) for row in container_status_rows],
        },
    }

    return {
        "available": True,
        "kpis": {
            "total_containers": total_containers,
            "containers_in_transit": containers_in_transit,
            "containers_available": containers_available,
            "containers_other": max(0, total_containers - containers_in_transit - containers_available),
            "utilization_pct": round((containers_in_transit / total_containers) * 100, 1) if total_containers else 0.0,
            "availability_pct": round((containers_available / total_containers) * 100, 1) if total_containers else 0.0,
            "total_shipments": total_shipments,
            "shipments_sent": shipments_sent,
            "shipments_received": shipments_received,
            "shipments_open": shipments_open,
            "shipments_7d": shipments_7d,
            "trend_7d_pct": trend_7d_pct,
            "shipments_sent_7d": shipments_sent_7d,
            "shipments_received_7d": shipments_received_7d,
            "aging_lt7": int(aging["lt7"] or 0),
            "aging_7_14": int(aging["bt7_14"] or 0),
            "aging_gte15": int(aging["gte15"] or 0),
            "avg_open_age_days": avg_open_age_days,
            "avg_lead_days": avg_lead_days,
            "items_total": items_total,
            "items_ok": item_stats["ok"],
            "items_pending": item_stats["pending"],
            "items_missing": item_stats["missing"],
            "items_damaged": item_stats["damaged"],
            "ok_rate": rate(item_stats["ok"]),
            "pending_rate": rate(item_stats["pending"]),
            "missing_rate": rate(item_stats["missing"]),
            "damaged_rate": rate(item_stats["damaged"]),
            "quality_index": quality_index,
            "issues_total": issues_total,
            "issues_7d": issues_7d,
        },
        "open_shipments": open_shipments,
        "recent_received": recent_received,
        "recent_issues": issues,
        "charts": charts,
        "charts_json": json.dumps(charts, ensure_ascii=False),
    }


def tracking_dashboard_safe() -> dict:
    """Nunca derruba o cockpit: em falha devolve payload vazio com o erro."""
    try:
        return tracking_dashboard()
    except Exception as exc:  # pragma: no cover - depende do Postgres externo
        empty_charts = {
            "monthly": {"labels": [], "sent": [], "received": []},
            "items": {"labels": [], "values": []},
            "containers": {"labels": [], "values": []},
        }
        return {
            "available": False,
            "error": str(exc),
            "kpis": {},
            "open_shipments": [],
            "recent_received": [],
            "recent_issues": [],
            "charts": empty_charts,
            "charts_json": json.dumps(empty_charts),
        }
