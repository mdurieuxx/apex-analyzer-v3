#!/usr/bin/env bash
set -euo pipefail

NAS_HOST="192.168.69.170"
NAS_SSH_PORT="22"
NAS_PORTAINER="http://192.168.69.170:9001"
NAS_USER="admin"
NAS_PASS="${NAS_PASS:-krusty69}"
DATA_DIR="/volume1/docker/apex-analyzer-v3/data"
APP_PORT="6970"
BACKEND_IMAGE="karting-app-backend:latest"
FRONTEND_IMAGE="karting-app-frontend:latest"
STACK_NAME="karting-app"
ENDPOINT=3

BACKEND_TAR="/tmp/karting-app-backend-amd64.tar.gz"
FRONTEND_TAR="/tmp/karting-app-frontend-amd64.tar.gz"

require() { command -v "$1" &>/dev/null || { echo "Requis : $1"; exit 1; }; }
require curl
require python3

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> Build backend linux/amd64..."
docker buildx build \
  --platform linux/amd64 \
  --tag "${BACKEND_IMAGE}" \
  --load \
  "${SCRIPT_DIR}/backend"

echo "==> Build frontend linux/amd64..."
docker buildx build \
  --platform linux/amd64 \
  --tag "${FRONTEND_IMAGE}" \
  --load \
  "${SCRIPT_DIR}/frontend"

echo "==> Export images..."
docker save "${BACKEND_IMAGE}" | gzip > "${BACKEND_TAR}"
echo "    Backend  : $(du -sh "${BACKEND_TAR}" | cut -f1)"
docker save "${FRONTEND_IMAGE}" | gzip > "${FRONTEND_TAR}"
echo "    Frontend : $(du -sh "${FRONTEND_TAR}" | cut -f1)"

echo "==> Auth Portainer..."
TOKEN=$(curl -sf -X POST "${NAS_PORTAINER}/api/auth" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"${NAS_USER}\",\"password\":\"${NAS_PASS}\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['jwt'])")
echo "    JWT ok"

echo "==> Chargement image backend..."
curl -sf -X POST "${NAS_PORTAINER}/api/endpoints/${ENDPOINT}/docker/images/load?quiet=1" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/x-gzip" \
  --data-binary @"${BACKEND_TAR}" \
  | python3 -c "import sys; [print(l) for l in sys.stdin if 'Loaded' in l]"

echo "==> Chargement image frontend..."
curl -sf -X POST "${NAS_PORTAINER}/api/endpoints/${ENDPOINT}/docker/images/load?quiet=1" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/x-gzip" \
  --data-binary @"${FRONTEND_TAR}" \
  | python3 -c "import sys; [print(l) for l in sys.stdin if 'Loaded' in l]"

echo "==> Création du dossier données..."
docker run --rm -v "${DATA_DIR}:${DATA_DIR}" busybox mkdir -p "${DATA_DIR}" 2>/dev/null || true

echo "==> Suppression stack existante..."
STACK_ID=$(curl -sf "${NAS_PORTAINER}/api/stacks" \
  -H "Authorization: Bearer ${TOKEN}" \
  | python3 -c "import sys,json; s=[x['Id'] for x in json.load(sys.stdin) if x['Name']=='${STACK_NAME}']; print(s[0] if s else '')")
if [ -n "${STACK_ID}" ]; then
  curl -sf -X DELETE "${NAS_PORTAINER}/api/stacks/${STACK_ID}?endpointId=${ENDPOINT}" \
    -H "Authorization: Bearer ${TOKEN}" | python3 -c "import sys; sys.stdin.read()" || true
  echo "    Stack ${STACK_ID} supprimée"
fi

echo "==> Déploiement stack ${STACK_NAME}..."
COMPOSE="version: '3.8'
services:
  backend:
    image: ${BACKEND_IMAGE}
    container_name: karting-app-api
    environment:
      - DB_PATH=/data/karting.db
      - PROXY_WS_URL=wss://apex-proxy-2.durdur.eu/ws
      - PROXY_HTTP_URL=https://apex-proxy-2.durdur.eu
    extra_hosts:
      - host.docker.internal:host-gateway
    volumes:
      - ${DATA_DIR}:/data
    restart: unless-stopped
  frontend:
    image: ${FRONTEND_IMAGE}
    container_name: karting-app-ui
    ports:
      - '${APP_PORT}:80'
    depends_on:
      - backend
    restart: unless-stopped
"

STACK_RESULT=$(curl -sf -X POST \
  "${NAS_PORTAINER}/api/stacks/create/standalone/string?endpointId=${ENDPOINT}" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"${STACK_NAME}\",\"stackFileContent\":$(echo "${COMPOSE}" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))'),\"endpointId\":${ENDPOINT}}")
echo "$STACK_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"    Stack ID: {d.get('Id','?')}\")" 2>/dev/null || echo "    Stack créée"

sleep 5

echo "==> Statut des conteneurs..."
for CONTAINER in karting-app-api karting-app-ui; do
  curl -sf "${NAS_PORTAINER}/api/endpoints/${ENDPOINT}/docker/containers/${CONTAINER}/json" \
    -H "Authorization: Bearer ${TOKEN}" \
    | python3 -c "
import sys,json
d=json.load(sys.stdin)
s=d['State']
print(f\"  {d['Name'].strip('/')} → {s['Status']} (running: {s['Running']})\")
" || echo "  ${CONTAINER} → introuvable"
done

rm -f "${BACKEND_TAR}" "${FRONTEND_TAR}"
echo ""
echo "App déployée → http://${NAS_HOST}:${APP_PORT}"
echo "Base de données → ${DATA_DIR}/karting.db"
