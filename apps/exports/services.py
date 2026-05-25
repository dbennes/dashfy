"""Servico generico de exportacao de QuerySet para CSV / XLSX / PDF / JSON."""
from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, time
from decimal import Decimal
from typing import Iterable

from django.db.models import QuerySet
from django.http import HttpResponse
from django.utils import timezone

from .models import ExportLog


def _serialize(value):
    if value is None:
        return ""
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _extract(obj, dotted: str):
    """Suporta lookup por '__' (foreign keys) -> obj.foo__bar."""
    parts = dotted.replace(".", "__").split("__")
    cur = obj
    for p in parts:
        if cur is None:
            return None
        cur = getattr(cur, p, None)
    if callable(cur):
        try:
            cur = cur()
        except Exception:
            return None
    return cur


def export_queryset_response(qs: QuerySet,
                             columns: list[tuple[str, str]],
                             filename_base: str,
                             fmt: str,
                             module: str = "",
                             user=None,
                             query_params: str = "") -> HttpResponse:
    """
    Exporta um QuerySet num formato pedido.
    `columns` = lista de (campo_no_modelo, rotulo_para_humanos).
    Suporta CSV, XLSX, PDF e JSON.
    """
    fmt = (fmt or "csv").lower()
    timestamp = timezone.now().strftime("%Y%m%d-%H%M%S")
    filename = f"{filename_base}_{timestamp}"
    rows = qs.count()

    if fmt == "csv":
        response = _export_csv(qs, columns, filename)
    elif fmt in {"xlsx", "excel"}:
        response = _export_xlsx(qs, columns, filename, filename_base)
    elif fmt == "pdf":
        response = _export_pdf(qs, columns, filename, filename_base)
    elif fmt == "json":
        response = _export_json(qs, columns, filename)
    else:
        raise ValueError(f"Formato nao suportado: {fmt}")

    ExportLog.objects.create(
        user=user, filename=f"{filename}.{fmt}", file_format=fmt,
        module=module, rows=rows, query_params=query_params[:1000],
    )
    return response


def _export_csv(qs, columns, filename):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
    writer = csv.writer(response, delimiter=";")
    writer.writerow([label for _, label in columns])
    for obj in qs.iterator(chunk_size=2000):
        writer.writerow([_serialize(_extract(obj, key)) for key, _ in columns])
    return response


def _export_xlsx(qs, columns, filename, sheet_name):
    import xlsxwriter
    output = io.BytesIO()
    wb = xlsxwriter.Workbook(output, {"in_memory": True})
    ws = wb.add_worksheet((sheet_name or "Export")[:30])

    header_fmt = wb.add_format({"bold": True, "bg_color": "#4F46E5",
                                "font_color": "#ffffff", "border": 1})
    row_fmt = wb.add_format({"border": 1})

    for ci, (_, label) in enumerate(columns):
        ws.write(0, ci, label, header_fmt)
        ws.set_column(ci, ci, max(12, min(40, len(label) + 4)))

    for ri, obj in enumerate(qs.iterator(chunk_size=2000), start=1):
        for ci, (key, _) in enumerate(columns):
            ws.write(ri, ci, _serialize(_extract(obj, key)), row_fmt)
    ws.freeze_panes(1, 0)
    wb.close()

    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}.xlsx"'
    return response


def _export_pdf(qs, columns, filename, title):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                    TableStyle)

    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=landscape(A4),
                            leftMargin=1*cm, rightMargin=1*cm,
                            topMargin=1*cm, bottomMargin=1*cm)
    styles = getSampleStyleSheet()
    story = [Paragraph(f"<b>{title}</b>", styles["Heading2"]),
             Paragraph(f"Gerado em {timezone.now():%d/%m/%Y %H:%M}", styles["Normal"]),
             Spacer(1, 8)]
    data = [[label for _, label in columns]]
    limit = 1500
    for i, obj in enumerate(qs.iterator(chunk_size=2000)):
        if i >= limit:
            break
        data.append([str(_serialize(_extract(obj, k)) or "") for k, _ in columns])
    if len(data) == 1:
        data.append(["(sem dados)"] + [""] * (len(columns) - 1))

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4F46E5")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#ffffff")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6fb")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(table)
    doc.build(story)

    response = HttpResponse(output.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}.pdf"'
    return response


def _export_json(qs, columns, filename):
    data = []
    for obj in qs.iterator(chunk_size=2000):
        row = {label: _serialize(_extract(obj, key)) for key, label in columns}
        data.append(row)
    response = HttpResponse(json.dumps(data, ensure_ascii=False, default=str, indent=2),
                            content_type="application/json")
    response["Content-Disposition"] = f'attachment; filename="{filename}.json"'
    return response
