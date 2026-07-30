# Deploy do DASHFY

Este repositorio e publico. Nao envie `.env`, `media/`, `logs`, backups ou
dumps PostgreSQL para o GitHub. Esses arquivos devem ir direto para o servidor
por SSH/SCP, SFTP ou outro canal privado.

## 1. Clonar no servidor

```bash
git clone https://github.com/dbennes/dashfy.git
cd dashfy
git lfs install
git lfs pull
```

## 2. Criar ambiente Python

Use Python 3.11 ou 3.12 em producao.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 3. Configurar variaveis privadas

```bash
cp .env.example .env
```

Edite `.env` no servidor:

```env
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=seu-dominio.com,www.seu-dominio.com,IP_DO_SERVIDOR
DJANGO_SECRET_KEY=gere-uma-chave-longa-e-unica

DB_NAME=DASHFY
DB_USER=postgres
DB_PASSWORD=senha-segura
DB_HOST=localhost
DB_PORT=5432

DATAFY_DB_NAME=DATAFY
DATAFY_DB_USER=postgres
DATAFY_DB_PASSWORD=senha-segura
DATAFY_DB_HOST=localhost
DATAFY_DB_PORT=5432
DATAFY_BASE_URL=http://127.0.0.1:8000

TASKFY_DB_NAME=taskfy
TASKFY_DB_USER=postgres
TASKFY_DB_PASSWORD=senha-segura
TASKFY_DB_HOST=localhost
TASKFY_DB_PORT=5432
TASKFY_BASE_URL=http://127.0.0.1:8080
```

O DASHFY usa PostgreSQL tanto para os dados gerenciados pelo Django quanto
para as fontes operacionais.

Em uma producao existente, mantenha `DB_*` apontando para o PostgreSQL
principal que ja contem os dados do DASHFY. Nao copie arquivos ou backups de
banco local para o servidor: eles nao fazem parte do deploy e nao sao lidos
pela aplicacao.

O alias `BUSINESS_DB_*` e opcional. Quando ele nao for informado, usa as
credenciais `DATAFY_DB_*`.

## 4. Preparar ou restaurar o PostgreSQL

Crie a base principal na primeira instalacao:

```bash
createdb -U postgres DASHFY
```

Para restaurar um backup existente, transfira o dump por canal privado e use
`pg_restore`:

```bash
pg_restore -U postgres -d DASHFY --clean --if-exists backup.dump
```

Backups devem ser gerados com `pg_dump`:

```bash
pg_dump -U postgres -Fc DASHFY > backup.dump
```

Se `media/` tiver uploads, copie o diretorio separadamente e ajuste as
permissoes do usuario que roda o Gunicorn. Mantenha `.env` com permissao 600.

## 5. Preparar Django

```bash
source .venv/bin/activate
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check --deploy
```

## 6. Rodar com Gunicorn

Teste manual:

```bash
gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 4
```

Exemplo de servico systemd em `/etc/systemd/system/dashfy.service`:

```ini
[Unit]
Description=DASHFY Django app
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/caminho/do/dashfy
EnvironmentFile=/caminho/do/dashfy/.env
ExecStart=/caminho/do/dashfy/.venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 4
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now dashfy
systemctl status dashfy
```

## 7. Nginx

Exemplo de bloco:

```nginx
server {
    listen 80;
    server_name seu-dominio.com www.seu-dominio.com;

    location /static/ {
        alias /caminho/do/dashfy/staticfiles/;
    }

    location /media/ {
        alias /caminho/do/dashfy/media/;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Ative HTTPS com Certbot depois que o dominio apontar para o servidor.
