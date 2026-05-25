# Deploy do DASHFY

Este repositorio e publico. Nao envie `.env`, `db.sqlite3`, `media/`, `logs/`,
backups ou dumps para o GitHub. Esses arquivos devem ir direto para o servidor
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

DB_ENGINE=django.db.backends.sqlite3
DB_NAME=db.sqlite3
BUSINESS_DB_ENGINE=django.db.backends.sqlite3
BUSINESS_DB_NAME=db.sqlite3
```

Se for usar PostgreSQL, ajuste `DB_ENGINE`, `DB_NAME`, `DB_USER`,
`DB_PASSWORD`, `DB_HOST` e `DB_PORT`.

## 4. Restaurar os dados atuais

Para manter o banco SQLite atual, copie `db.sqlite3` direto para a raiz do
projeto no servidor:

```bash
scp db.sqlite3 usuario@servidor:/caminho/do/dashfy/db.sqlite3
```

Se `media/` tiver uploads, copie tambem:

```bash
scp -r media usuario@servidor:/caminho/do/dashfy/media
```

Depois ajuste permissao/usuario conforme o usuario que roda o Gunicorn:

```bash
chown -R www-data:www-data db.sqlite3 media logs
chmod 600 db.sqlite3 .env
```

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
