"""Servicos de alto nivel para sincronizar dados ECLIC com o banco local."""
from __future__ import annotations

import logging
import time

from django.utils import timezone

from apps.accounts.models import Client

from .api_client import EclicAPIError, EclicClient
from .models import Document, SyncLog

logger = logging.getLogger("shellbi.eclic")


def _map_payload_to_document(item: dict, client: Client) -> dict:
    """Mapeia o payload externo para os campos do modelo Document."""
    return {
        "client": client,
        "external_id": str(item.get("Id") or item.get("id") or item.get("external_id") or ""),
        "code": item.get("Code") or item.get("code") or item.get("numero") or "",
        "title": item.get("Title") or item.get("title") or item.get("titulo") or item.get("name") or "",
        "description": item.get("description") or item.get("descricao") or "",
        "category": item.get("Discipline") or item.get("category") or item.get("categoria") or "",
        "document_type": item.get("Extension") or item.get("type") or item.get("tipo") or "",
        "revision": str(item.get("Revision") or item.get("revision") or item.get("revisao") or ""),
        "status": _map_status(item.get("DocumentStatus") or item.get("status")),
        "url": item.get("url") or item.get("link") or "",
        "file_size": item.get("file_size") or item.get("tamanho"),
        "issued_at": item.get("issued_at") or item.get("data_emissao"),
        "raw_payload": item,
        "last_synced_at": timezone.now(),
    }


def _map_status(value):
    if not value:
        return Document.Status.DRAFT
    v = str(value).lower().strip()
    mapping = {
        "rascunho": "draft", "draft": "draft",
        "review": "review", "em revisao": "review",
        "aprovado": "approved", "approved": "approved",
        "rejeitado": "rejected", "rejected": "rejected",
        "obsoleto": "obsolete", "obsolete": "obsolete",
    }
    return mapping.get(v, "draft")


def sync_documents_for_client(client: Client, triggered_by: str = "manual") -> SyncLog:
    """Sincroniza documentos ECLIC para um cliente especifico."""
    started = time.time()
    created = updated = errored = 0
    error_msg = ""
    result = SyncLog.Result.SUCCESS

    try:
        api = EclicClient()
        for item in api.list_documents():
            try:
                payload = _map_payload_to_document(item, client)
                if not payload["external_id"]:
                    errored += 1
                    continue
                doc, was_created = Document.objects.update_or_create(
                    client=client,
                    external_id=payload["external_id"],
                    defaults={k: v for k, v in payload.items()
                              if k not in {"client", "external_id"}},
                )
                if was_created:
                    created += 1
                else:
                    updated += 1
            except Exception as exc:
                logger.exception("Erro processando documento ECLIC")
                errored += 1
                error_msg = (error_msg + f"\n{exc}")[-2000:]
        if errored:
            result = SyncLog.Result.PARTIAL
    except EclicAPIError as exc:
        result = SyncLog.Result.FAILED
        error_msg = str(exc)
        logger.error("Falha geral sync ECLIC: %s", exc)

    log = SyncLog.objects.create(
        client=client, triggered_by=triggered_by, result=result,
        documents_created=created, documents_updated=updated,
        documents_errored=errored,
        duration_seconds=round(time.time() - started, 2),
        error_message=error_msg,
    )
    return log
