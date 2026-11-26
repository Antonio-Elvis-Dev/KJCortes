#!/usr/bin/env bash
# Prepara uma VPS Ubuntu/Debian para rodar o KJCortes com Docker.
# Uso (na pasta do projeto): sudo bash scripts/instalar_vps.sh
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  echo "Instalando Docker..."
  curl -fsSL https://get.docker.com | sh
fi

cd "$(dirname "$0")/.."
[ -f config.yaml ] || cp config.example.yaml config.yaml
[ -f .env ] || cp .env.example .env
mkdir -p dados cache saida
# O contêiner roda com o usuário de UID 1000.
chown -R 1000:1000 dados cache saida

cat <<'MSG'

Pronto. Agora:
  1. Edite o .env (senha do painel, domínio, chaves) e o config.yaml.
  2. Suba o painel:
       sem domínio:  docker compose up -d --build
       com domínio:  docker compose --profile https up -d --build
       com GPU:      docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
  3. Veja os logs com: docker compose logs -f painel
MSG
