"""
Cliente HTTP para a API ECLIC.

Configurado via settings:
  ECLIC_API_BASE_URL
  ECLIC_API_KEY  (header X-Api-Key)
  ECLIC_API_USER + ECLIC_API_PASSWORD  (Basic Auth)
  ECLIC_API_TIMEOUT

Edite `_auth_headers` e `list_documents` para casar com o contrato real
da sua API. Esse esqueleto cobre os casos mais comuns (token header,
basic auth, paginacao por `?page=`/`next` cursor).
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any, Iterator

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger("shellbi.eclic")
TOKEN_TTL = timedelta(minutes=55)


class EclicAPIError(Exception):
    pass


class EclicClient:
    def __init__(self,
                 base_url: str | None = None,
                 api_key: str | None = None,
                 user: str | None = None,
                 password: str | None = None,
                 timeout: int | None = None,
                 client_id: int | None = None,
                 project_id: int | None = None):
        fallback = _spdm_eclic_settings_fallback()
        self.base_url = (base_url or settings.ECLIC_API_BASE_URL or fallback.get("base_url") or "").rstrip("/")
        self.api_key = api_key or settings.ECLIC_API_KEY
        self.user = user or settings.ECLIC_API_USER or fallback.get("username") or ""
        self.password = password or settings.ECLIC_API_PASSWORD or fallback.get("password") or ""
        self.timeout = timeout or settings.ECLIC_API_TIMEOUT
        self.client_id = client_id or settings.ECLIC_API_CLIENT_ID or fallback.get("client_id") or 0
        self.project_id = project_id or settings.ECLIC_API_PROJECT_ID or fallback.get("project_id") or 0
        self._token = ""
        self._token_expires_at = None
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json",
                                     "User-Agent": "ShellBI/1.0"})

    def _api_url(self, endpoint: str) -> str:
        if not self.base_url:
            raise EclicAPIError("ECLIC_API_BASE_URL nao configurada (.env)")
        base = self.base_url.rstrip("/")
        endpoint = endpoint.lstrip("/")
        if base.endswith("/api/api"):
            return f"{base}/{endpoint}"
        return f"{base}/api/api/{endpoint}"

    def authenticate(self) -> str:
        if self.api_key:
            self._token = self.api_key
            self._token_expires_at = timezone.now() + TOKEN_TTL
            return self._token
        if not self.user or not self.password:
            raise EclicAPIError("ECLIC_API_USER/ECLIC_API_PASSWORD nao configurados")
        try:
            response = self.session.post(
                self._api_url("users/authenticate"),
                json={"userName": self.user, "password": self.password},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            logger.exception("Erro ECLIC authenticate")
            raise EclicAPIError(f"Falha de conexao: {exc}") from exc
        if response.status_code >= 400:
            raise EclicAPIError(f"authenticate HTTP {response.status_code}: {response.text[:300]}")
        token = ""
        try:
            payload = response.json()
            if isinstance(payload, str):
                token = payload
            elif isinstance(payload, dict):
                token = payload.get("token") or payload.get("Authorization") or payload.get("authorization") or ""
        except ValueError:
            token = response.text.strip().strip('"')
        if not token:
            raise EclicAPIError("ECLIC authenticate retornou token vazio")
        self._token = token
        self._token_expires_at = timezone.now() + TOKEN_TTL
        return token

    def get_token(self) -> str:
        if not self._token or not self._token_expires_at or timezone.now() >= self._token_expires_at:
            return self.authenticate()
        return self._token

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.get_token()}"}

    # ----- low level -----
    def _request(self, method: str, path: str, **kwargs) -> Any:
        url = self._api_url(path)
        headers = {**self._auth_headers(), **kwargs.pop("headers", {})}
        try:
            r = self.session.request(method, url, headers=headers,
                                     timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            logger.exception("Erro ECLIC %s %s", method, url)
            raise EclicAPIError(f"Falha de conexao: {exc}") from exc
        if r.status_code == 401:
            self._token = ""
            headers["Authorization"] = f"Bearer {self.get_token()}"
            r = self.session.request(method, url, headers=headers, timeout=self.timeout, **kwargs)
        if r.status_code >= 400:
            raise EclicAPIError(f"HTTP {r.status_code}: {r.text[:300]}")
        if not r.content:
            return None
        try:
            return r.json()
        except ValueError:
            return r.text

    # ----- public methods -----
    def ping(self) -> bool:
        try:
            self.authenticate()
            return True
        except EclicAPIError:
            return False

    def list_documents(self, page_size: int = 100,
                       extra_params: dict | None = None) -> Iterator[dict]:
        """Itera documentos do contrato real E-CLIC (`documents/getdocumentos`)."""
        if not self.client_id or not self.project_id:
            raise EclicAPIError("ECLIC_API_CLIENT_ID/ECLIC_API_PROJECT_ID nao configurados")
        payload = self._request(
            "POST",
            "documents/getdocumentos",
            json={"cliente": int(self.client_id), "projeto": int(self.project_id)},
        )
        items = payload.get("results") if isinstance(payload, dict) else payload
        for item in items or []:
            yield item

    def get_document(self, external_id: str) -> dict:
        for item in self.list_documents():
            if str(item.get("Id") or item.get("id") or "") == str(external_id):
                return item
        raise EclicAPIError(f"Documento ECLIC nao encontrado: {external_id}")

    def download_document(self, external_id: str) -> bytes:
        url = f"{self.base_url}/documents/{external_id}/download"
        r = self.session.get(url, headers=self._auth_headers(), auth=self._auth(),
                             timeout=self.timeout, stream=True)
        if r.status_code != 200:
            raise EclicAPIError(f"Download falhou: HTTP {r.status_code}")
        return r.content


def _spdm_eclic_settings_fallback() -> dict[str, Any]:
    """Reuse SPDM local E-CLIC connection settings when Dashfy env is blank."""
    db_path = Path(getattr(settings, "SPDM_DB_PATH", "") or "")
    if not db_path.exists():
        return {}
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                """
                select eclic_base_url, eclic_username, eclic_password,
                       eclic_default_client_id, eclic_default_project_id
                from core_appsettings
                where singleton_id = 1
                """
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return {}
    if not row:
        return {}
    return {
        "base_url": row["eclic_base_url"] or "",
        "username": row["eclic_username"] or "",
        "password": row["eclic_password"] or "",
        "client_id": int(row["eclic_default_client_id"] or 0),
        "project_id": int(row["eclic_default_project_id"] or 0),
    }
