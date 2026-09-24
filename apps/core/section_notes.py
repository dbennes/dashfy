"""Section observations, audited status changes and a single-sheet minutes export."""
from datetime import date
from functools import wraps
from io import BytesIO
import json
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.db import DatabaseError, transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_GET
import xlsxwriter

from .models import SectionNote, SectionNoteEvent

SECTIONS = {"s00": "Planejamento", "s01": "Engenharia", "s02": "Suprimentos",
            "s03": "Fabricação", "s04": "Logística", "s05": "Modelo 3D"}
STATUSES = dict(SectionNote._meta.get_field("status").choices)
PROJECT = "BN-EPC1"


def scope(user):
    return SectionNote.objects.filter(project=PROJECT, client_id=user.client_id)


def reply(data, status=200):
    response = JsonResponse(data, status=status)
    response["Cache-Control"] = "no-store"
    return response


def api_errors(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except (ValueError, TypeError, KeyError) as exc:
            return reply({"error": str(exc) or "Dados inválidos."}, 400)
        except DatabaseError:
            return reply({"error": "Os registros estão indisponíveis. Tente novamente em instantes."}, 503)
    return wrapper


def payload(request):
    if len(request.body) > 32000:
        raise ValueError("O registro excede o tamanho permitido.")
    data = json.loads(request.body)
    if not isinstance(data, dict):
        raise ValueError("Dados inválidos.")
    return data


def serialize(note):
    return {"id": note.pk, "section": note.section, "author": note.author_name,
            "author_id": note.author_id, "date": note.note_date.isoformat(),
            "created_at": note.created_at.isoformat(), "body": note.body,
            "due_date": note.due_date.isoformat() if note.due_date else None,
            "information_only": note.information_only, "status": note.status,
            "version": note.version, "context": note.context,
            "events": [{"at": event.created_at.isoformat(), "actor": event.actor_name,
                        "from": event.previous_status, "to": event.status}
                       for event in note.events.all()]}


@login_required
@require_http_methods(["GET", "POST"])
@api_errors
def notes(request):
    if request.method == "GET":
        section = request.GET.get("section")
        if not section:
            summaries = {key: {"label": label, "total": 0, "pending": 0, "people": []} for key, label in SECTIONS.items()}
            seen = {key: set() for key in SECTIONS}
            for row in scope(request.user).values("section", "author_id", "author_name", "status", "information_only"):
                if row["section"] not in summaries:
                    continue
                item = summaries[row["section"]]
                item["total"] += 1
                item["pending"] += row["status"] == "pending" and not row["information_only"]
                identity = row["author_id"] or row["author_name"]
                if identity not in seen[row["section"]]:
                    seen[row["section"]].add(identity)
                    item["people"].append({"id": row["author_id"], "name": row["author_name"]})
            return reply({"sections": summaries, "today": timezone.localdate().isoformat(), "user": str(request.user)})
        if section not in SECTIONS:
            raise ValueError("Seção inválida.")
        page = max(1, int(request.GET.get("page", "1")))
        records = scope(request.user).filter(section=section).prefetch_related("events")
        status = request.GET.get("status", "all")
        if status != "all":
            if status not in STATUSES:
                raise ValueError("Status inválido.")
            records = records.filter(status=status)
        total = records.count()
        return reply({"notes": [serialize(n) for n in records[(page-1)*20:page*20]],
                      "total": total, "page": page, "has_next": page*20 < total})

    data = payload(request)
    section = data.get("section")
    body = data.get("body", "")
    info = data.get("information_only", False)
    if section not in SECTIONS or not isinstance(body, str) or not 1 <= len(body.strip()) <= 4000:
        raise ValueError("Escolha uma seção e escreva uma nota de até 4.000 caracteres.")
    if not isinstance(info, bool):
        raise ValueError("Indique se o registro é somente informação.")
    note_date = date.fromisoformat(data.get("date", ""))
    due = date.fromisoformat(data["due_date"]) if data.get("due_date") else None
    if note_date > timezone.localdate():
        raise ValueError("A data do registro não pode estar no futuro.")
    if not info and due is None:
        raise ValueError("Informe a previsão de conclusão ou marque somente informação.")
    if due and due < note_date:
        raise ValueError("A previsão não pode ser anterior à data do registro.")
    context = data.get("context", {})
    if not isinstance(context, dict):
        raise ValueError("Contexto inválido.")
    context = {key: str(context[key])[:160] for key in
               ("date_from", "date_to", "discipline", "campaign", "contract_week") if context.get(key)}
    if not isinstance(data.get("request_id"), str):
        raise ValueError("Abra um novo registro para continuar.")
    with transaction.atomic():
        note, created = SectionNote.objects.get_or_create(request_id=UUID(data.get("request_id", "")), defaults={
            "project": PROJECT, "client_id": request.user.client_id, "section": section,
            "author_id": request.user.pk, "author_name": str(request.user)[:300],
            "note_date": note_date, "body": body.strip(), "due_date": None if info else due,
            "information_only": info, "context": context})
        if not created and (note.project != PROJECT or note.author_id != request.user.pk or note.client_id != request.user.client_id
                            or note.section != section or note.body != body.strip()):
            return reply({"error": "Identificador já utilizado. Abra um novo registro."}, 409)
        if created:
            SectionNoteEvent.objects.create(note_id=note.pk, actor_id=request.user.pk,
                                           actor_name=note.author_name, status="pending")
    return reply({"note": serialize(note)}, 201 if created else 200)


@login_required
@require_http_methods(["POST"])
@api_errors
def change_status(request, pk):
    data = payload(request)
    target = data.get("status")
    if target not in STATUSES:
        raise ValueError("Status inválido.")
    with transaction.atomic():
        note = scope(request.user).select_for_update().filter(pk=pk).first()
        if note is None:
            return reply({"error": "Registro não encontrado."}, 404)
        if data.get("version") != note.version:
            return reply({"error": "Este registro foi atualizado por outra pessoa. Atualize o histórico antes de alterar."}, 409)
        if note.status != target:
            SectionNoteEvent.objects.create(note_id=note.pk, actor_id=request.user.pk,
                actor_name=str(request.user)[:300], previous_status=note.status, status=target)
            note.status = target
            note.version += 1
            note.save(update_fields=["status", "version", "updated_at"])
    return reply({"note": serialize(note)})


@login_required
@require_GET
def export_minutes(request):
    output = BytesIO()
    book = xlsxwriter.Workbook(output, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False})
    sheet = book.add_worksheet("Ata de acompanhamento")
    title = book.add_format({"bold": True, "font_size": 16, "font_color": "#FFFFFF", "bg_color": "#14171C"})
    subtitle = book.add_format({"font_color": "#475569", "font_size": 10})
    styles = {}
    for cancelled in (False, True):
        styles[cancelled] = book.add_format({"text_wrap": True, "valign": "top", "font_size": 10,
            "font_color": "#7C8592" if cancelled else "#172033", "font_strikeout": cancelled})
    sheet.merge_range("A1:N1", "DASHFY | BN-EPC1 | ATA DE ACOMPANHAMENTO", title)
    sheet.merge_range("A2:N2", "Comentários e alterações de status de todas as seções · uma linha por evento", subtitle)
    now = timezone.localtime()
    sheet.merge_range("A3:N3", f"Emitida em {now:%d/%m/%Y %H:%M %Z} · {request.user}", subtitle)
    headers = ["Registro", "Seção", "Data da nota", "Criado em", "Autor", "Nota", "Tipo", "Previsão",
               "Status atual", "Evento em", "Alterado por", "Status anterior", "Status registrado", "Contexto"]
    records = SectionNoteEvent.objects.filter(note__in=scope(request.user)).select_related("note").order_by("created_at", "pk")
    row = 5
    for event in records.iterator(chunk_size=500):
        note = event.note
        values = [note.pk, SECTIONS.get(note.section, note.section), note.note_date.isoformat(),
                  timezone.localtime(note.created_at).strftime("%d/%m/%Y %H:%M:%S %Z"), note.author_name, note.body,
                  "Informação" if note.information_only else "Acompanhamento", note.due_date.isoformat() if note.due_date else "—",
                  STATUSES[note.status], timezone.localtime(event.created_at).strftime("%d/%m/%Y %H:%M:%S %Z"),
                  event.actor_name, STATUSES.get(event.previous_status, "Criação"), STATUSES[event.status],
                  "; ".join(f"{k}: {v}" for k, v in note.context.items())]
        sheet.write_row(row, 0, values, styles[note.status == "cancelled"])
        sheet.set_row(row, 60)
        row += 1
    if row > 5:
        sheet.add_table(4, 0, row-1, 13, {"name": "AtaAcompanhamento", "style": "Table Style Medium 2",
            "columns": [{"header": h} for h in headers]})
    else:
        sheet.write_row(4, 0, headers)
        sheet.write(5, 0, "Nenhum comentário registrado.")
    sheet.set_column("A:A", 10)
    sheet.set_column("B:E", 23)
    sheet.set_column("F:F", 65)
    sheet.set_column("G:N", 24)
    sheet.freeze_panes(5, 2)
    sheet.set_landscape()
    sheet.set_paper(9)
    sheet.fit_to_pages(1, 0)
    sheet.repeat_rows(0, 4)
    sheet.set_footer("&CDASHFY · Ata de acompanhamento | Página &P de &N")
    book.close()
    response = HttpResponse(output.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="DASHFY_Ata.xlsx"'
    response["Cache-Control"] = "no-store"
    return response
