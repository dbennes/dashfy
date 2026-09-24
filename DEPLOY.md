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

O rastreamento de embarcacoes usa importacao de relatorios por padrao. Nao
precisa de chave AISStream nem de processo `listen_ais`. Aplique as migrations
no PostgreSQL do DASHFY para armazenar navios e historico importado.
A coleta automatica e opcional: consulte [o guia AIS](docs/vessel-tracking.md).

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

## Atualizacao Vessel tracking (setembro/2026)

Na pasta existente do DASHFY no servidor, com o ambiente virtual ativado:

```bash
git pull --ff-only
git lfs pull --include="static/models/vessel-hq.glb"
pip install -r requirements.txt
python manage.py migrate --database default
python manage.py showmigrations vessels --database default
python manage.py collectstatic --noinput
python manage.py check
```

As quatro migrations de `vessels` devem aparecer com `[X]`. Elas criam o
historico AIS e acrescentam origem do provedor, estado da viagem e data da
declaracao de destino. Nao execute `makemigrations` no servidor.

O GLB distribuido e `static/models/vessel-hq.glb` (~4 MB), padrao do sistema.
Se o `.env` do servidor ja tiver `AIS_VESSEL_MODEL_URL`, ajuste para
`/static/models/vessel-hq.glb`. Um valor vazio desativa o modelo externo.

Reinicie o servico web existente apos as migrations e o collectstatic.
No Linux, se o servico tiver o nome do exemplo deste documento:

```bash
sudo systemctl restart dashfy
sudo systemctl status dashfy --no-pager
```

Somente se optar pela coleta automatica, defina `AIS_COLLECTION_MODE=stream`,
configure a chave `AISSTREAM_API_KEY`
privadamente no servidor e instale `deploy/dashfy-ais.service`, ajustando
usuario e caminhos. O servidor web sozinho nao inicia a coleta.
Os dados locais (navios cadastrados e posicoes importadas) nao viajam com
o codigo: mantenha os dados existentes no servidor ou importe um relatorio
AIS pelo fluxo autenticado. Nao substitua o banco de producao pelo local.

### Windows: manutencao e importacao

No modo padrao (`AIS_COLLECTION_MODE=import`), nao inicie `listen_ais` e nao
instale um servico de coleta. Cada importacao salva as observacoes e atualiza
o historico. Sem novo relatorio, a ultima posicao permanece a mesma.

`migrate`, `showmigrations`, `makemigrations`, `collectstatic` e `check` usam
logs no terminal, sem abrir o arquivo `logs/dashfy.log` do servico web. Isso
evita que a permissao desse arquivo bloqueie a manutencao por outro usuario.
O servico web continua com sua configuracao de logs existente.

### Desempenho do dashboard (24 setembro 2026)

As consultas de fabricacao, pacotes estruturais e progresso AVEON reutilizam
resultados por 45 segundos em cada processo web. Requisicoes simultaneas no
mesmo processo compartilham a primeira leitura. Falhas nao sao armazenadas;
permissoes, comentarios e dados pessoais nao entram nesse cache. O cache e
separado por data de corte e dia atual. `DASHFY_SOURCE_CACHE_SECONDS=0` no
`.env` desativa essa reutilizacao para diagnostico. Alteracoes feitas no
DATAFY podem levar ate 45 segundos para aparecer numa nova consulta ao DASHFY.
ROS e Rundown importados continuam lidos na requisicao, fora desse cache.

A arvore 3D so e carregada quando o painel fica visivel ou o usuario a solicita.
A rotacao automatica e os controles de navegacao continuam disponiveis.

O storage de producao passa a ser `config.static_storage.DashboardStaticStorage`.
Ele preserva manifestos, hashes e arquivos originais, usando Brotli nivel 4 e
gzip nivel 6 para evitar a compressao maxima muito lenta dos GLBs. Os arquivos
comprimidos podem ficar um pouco maiores. Caso o servidor tenha sobrescrito
`STATICFILES_STORAGE` localmente, confira se usa essa classe apos o pull.

Esta atualizacao nao cria migrations nem exige novas dependencias:

```powershell
git pull --ff-only
python manage.py collectstatic --noinput
python manage.py check
```

Reinicie o processo/servico web existente. A primeira leitura apos reinicio ou
expiracao ainda consulta as fontes; o cache local nao e compartilhado entre
processos. Valide no servidor a abertura inicial e a navegacao com varios
usuarios, pois os tempos locais nao representam a rede e o banco de producao.
