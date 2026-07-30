# DASHFY

Cockpit gerencial construido em **Django 5 + Plotly + PostgreSQL**. O dashboard
principal consome bases reais do **SPDM/DATAFY** e do **Taskfy**, consolidando
engenharia, materiais, suprimentos, JobCards, campo e logistica.

## Modulos

| Modulo    | O que faz                                                                  |
|-----------|-----------------------------------------------------------------------------|
| Accounts  | Autenticacao, usuarios, clientes (multi-tenant), permissoes por modulo, auditoria de login |
| Core      | Layout responsivo, dashboard home, navbar/sidebar, branding configuravel    |
| Datafy    | Leitura da base real SPDM/DATAFY: documentos, materiais, POs, estoque e ECLIC |
| Taskfy    | Leitura da base real Taskfy: JobCards, status, atrasos, DFRs e remessas       |
| Schedule  | Modulo legado mantido fora da navegacao principal ate ser ligado a fonte real |
| ECLIC     | Visao consolidada via SPDM/DATAFY no cockpit gerencial                       |
| Exports   | Servico generico CSV/XLSX/PDF/JSON + historico de exportacoes               |
| Filters   | Salvamento de filtros e dashboards favoritos por usuario                    |

## Stack

- Python 3.11+
- Django 5.0
- PostgreSQL 13+
- Plotly + Pandas
- Bootstrap 5 + Bootstrap Icons
- Select2, Flatpickr, DataTables, FullCalendar (via CDN)
- Whitenoise (static files), gunicorn (deploy)

## Setup rapido

```bash
# 1. clonar e entrar no projeto
cd dashfy

# 2. criar virtualenv
python -m venv .venv
.venv\Scripts\activate     # Windows
# source .venv/bin/activate   # Linux/macOS

# 3. instalar dependencias
pip install -r requirements.txt

# 4. configurar .env (copie do .env.example)
copy .env.example .env       # Windows
# cp .env.example .env       # Linux/macOS

# 5. criar banco PostgreSQL (uma vez)
# createdb -U postgres DASHFY

# 6. migrar
python manage.py migrate

# 7. rodar
python manage.py runserver
```

Acesse http://localhost:8000

## Configuracao .env

Variaveis principais:

```env
# Django
DJANGO_SECRET_KEY=...
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

# PostgreSQL principal (BI: usuarios, permissoes, configs)
DB_NAME=DASHFY
DB_USER=postgres
DB_PASSWORD=...
DB_HOST=localhost
DB_PORT=5432

# PostgreSQL DATAFY operacional
DATAFY_DB_NAME=DATAFY
DATAFY_DB_USER=postgres
DATAFY_DB_PASSWORD=...
DATAFY_DB_HOST=localhost
DATAFY_DB_PORT=5432
DATAFY_BASE_URL=http://127.0.0.1:8000

# Fonte real Taskfy
TASKFY_DB_NAME=taskfy
TASKFY_DB_USER=...
TASKFY_DB_PASSWORD=...
TASKFY_DB_HOST=localhost
TASKFY_DB_PORT=5432
TASKFY_BASE_URL=http://127.0.0.1:8080
```

Usuarios, permissoes, imports e snapshots do cockpit ficam no PostgreSQL
principal definido por `DB_*`. O runtime nao utiliza arquivo de banco local.

## Permissoes / multi-tenant

- `User.role` define perfis: admin / analyst / viewer / client
- `User.client` vincula o usuario a um cliente; views aplicam **row-level
  filtering** automaticamente (`filter_queryset_by_client`)
- `ModulePermission` controla view/export/edit por modulo por usuario
- O middleware [LoginRequiredMiddleware](apps/accounts/middleware.py) forca login
  em todas as URLs exceto `LOGIN_EXEMPT_URLS`

## Exportacao

Toda lista do BI tem botao **Exportar** com 4 formatos:
- CSV (delimitador `;`)
- XLSX (com formatacao + freeze panes)
- PDF (paisagem, tabela paginada, branding Shell)
- JSON (estruturado)

Cada export gera registro em `ExportLog` (visivel em `/exports/historico/`).

## ECLIC API

O cliente HTTP esta em [apps/eclic/api_client.py](apps/eclic/api_client.py). Ajuste:
- `_auth_headers()` se a API usa um header diferente
- `list_documents()` se a paginacao for diferente (cursor, link header, etc.)
- `_map_payload_to_document()` em [services.py](apps/eclic/services.py) para
  mapear os campos retornados pela API ECLIC

Para volumes maiores, mover o `sync_documents_for_client` para uma task Celery
(Redis ja vem configurado no `.env`).

## Deploy producao

```bash
# Static files
python manage.py collectstatic --noinput

# Gunicorn
gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 4

# Nginx (proxy reverso + static)
# location /static/ { alias /app/staticfiles/; }
# location /media/  { alias /app/media/; }
# location /        { proxy_pass http://localhost:8000; }
```

Lembre-se de:
- `DJANGO_DEBUG=False`
- `DJANGO_SECRET_KEY` longo e aleatorio
- `DJANGO_ALLOWED_HOSTS` com seu dominio
- Servir HTTPS (settings ja ativa HSTS/SECURE quando `DEBUG=False`)

## Estrutura

```
dashfy/
  config/          settings/urls/wsgi
  apps/
    accounts/      User, Client, permissoes, login audit
    core/          home, busca, branding, db router, seed
    datafy/        models, filtros, charts, views, templates
    taskfy/        idem + kanban
    schedule/      cronogramas + calendario FullCalendar
    eclic/         API client + sync + viewer
    exports/       servico CSV/XLSX/PDF/JSON + historico
    filters/       views salvas (favoritos)
  templates/       base + partials + por modulo
  static/          CSS/JS/imagens
  media/           uploads (avatars, logos)
  logs/            rotating file logs
```
