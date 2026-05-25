# =========================================================
# Shell BI - script de setup para Windows PowerShell
# Uso:
#   .\setup.ps1            (instala dependencias + migra)
# =========================================================
$ErrorActionPreference = "Stop"

Write-Host "==> Criando virtualenv..." -ForegroundColor Cyan
if (-not (Test-Path ".venv")) {
  python -m venv .venv
}

Write-Host "==> Ativando virtualenv..." -ForegroundColor Cyan
. .\.venv\Scripts\Activate.ps1

Write-Host "==> Atualizando pip..." -ForegroundColor Cyan
python -m pip install --upgrade pip

Write-Host "==> Instalando dependencias..." -ForegroundColor Cyan
pip install -r requirements.txt

if (-not (Test-Path ".env")) {
  Write-Host "==> Criando .env a partir de .env.example..." -ForegroundColor Cyan
  Copy-Item ".env.example" ".env"
  Write-Host "Edite .env com suas credenciais reais do PostgreSQL antes de continuar." -ForegroundColor Yellow
}

Write-Host "==> Aplicando migrations..." -ForegroundColor Cyan
python manage.py makemigrations
python manage.py migrate

Write-Host ""
Write-Host "Setup concluido!" -ForegroundColor Green
Write-Host "Rode 'python manage.py runserver' e acesse http://localhost:8000"
Write-Host "Configure um usuario real via Django admin ou createsuperuser."
