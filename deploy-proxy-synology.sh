#!/usr/bin/env bash
set -euo pipefail

NAS_HOST="192.168.69.170"
NAS_SSH_PORT="22"
NAS_PORTAINER="http://192.168.69.170:9001"
NAS_USER="admin"
NAS_PASS="krusty69"
DATA_DIR="/volume1/docker/apex-analyzer-v3/recordings"
PROXY_PORT="6969"
IMAGE_NAME="apex-proxy:latest"
STACK_NAME="apex-proxy"
CONTAINER_NAME="karting-proxy"
TAR_FILE="/tmp/apex-proxy-amd64.tar.gz"
ENDPOINT=3  # ID endpoint Portainer (GET /api/endpoints pour vérifier)

require() { command -v "$1" &>/dev/null || { echo "Requis : $1"; exit 1; }; }
require curl
require python3

APP_VERSION=$(git -C "$(dirname "$0")" describe --tags --abbrev=0 2>/dev/null || echo "dev")
echo "==> Build image linux/amd64 (version ${APP_VERSION})..."
docker buildx build \
  --platform linux/amd64 \
  --tag "${IMAGE_NAME}" \
  --build-arg APP_VERSION="${APP_VERSION}" \
  --load \
  "$(dirname "$0")/proxy"

echo "==> Export image → ${TAR_FILE}..."
docker save "${IMAGE_NAME}" | gzip > "${TAR_FILE}"
echo "    Taille : $(du -sh "${TAR_FILE}" | cut -f1)"

echo "==> Auth Portainer..."
TOKEN=$(curl -sf -X POST "${NAS_PORTAINER}/api/auth" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"${NAS_USER}\",\"password\":\"${NAS_PASS}\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['jwt'])")
echo "    JWT ok"

echo "==> Chargement de l'image via Portainer..."
curl -sf -X POST "${NAS_PORTAINER}/api/endpoints/${ENDPOINT}/docker/images/load?quiet=1" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/x-gzip" \
  --data-binary @"${TAR_FILE}" \
  | python3 -c "import sys; [print(l) for l in sys.stdin if 'Loaded' in l]"

echo "==> Création du dossier données..."
/usr/bin/expect -f - <<EXPECT || true
  set timeout 15
  spawn ssh -p ${NAS_SSH_PORT} -o StrictHostKeyChecking=no ${NAS_USER}@${NAS_HOST} "mkdir -p ${DATA_DIR}"
  expect {password:} { send "${NAS_PASS}\r"; exp_continue }
  expect eof
EXPECT

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
  proxy:
    image: ${IMAGE_NAME}
    container_name: ${CONTAINER_NAME}
    restart: unless-stopped
    ports:
      - '${PROXY_PORT}:9000'
    volumes:
      - ${DATA_DIR}:/data/recordings
"

STACK_RESULT=$(curl -sf -X POST \
  "${NAS_PORTAINER}/api/stacks/create/standalone/string?endpointId=${ENDPOINT}" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"${STACK_NAME}\",\"stackFileContent\":$(echo "${COMPOSE}" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))'),\"endpointId\":${ENDPOINT}}")
echo "$STACK_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"    Stack ID: {d.get('Id','?')}\")" 2>/dev/null || echo "    Stack créée"

sleep 3

echo "==> Statut du conteneur..."
curl -sf "${NAS_PORTAINER}/api/endpoints/${ENDPOINT}/docker/containers/${CONTAINER_NAME}/json" \
  -H "Authorization: Bearer ${TOKEN}" \
  | python3 -c "
import sys,json
d=json.load(sys.stdin)
s=d['State']
print(f\"  {d['Name'].strip('/')} → {s['Status']} (running: {s['Running']})\")
"

rm -f "${TAR_FILE}"
echo ""
echo "Proxy déployé → http://${NAS_HOST}:${PROXY_PORT}"
echo "WS             → ws://${NAS_HOST}:${PROXY_PORT}/ws"
echo "Interface      → http://${NAS_HOST}:${PROXY_PORT}/"
echo "Enregistrements → ${DATA_DIR}"
