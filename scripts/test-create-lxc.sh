#!/bin/bash
###############################################################################
# test-create-lxc.sh
#
# Script de test automatisé : création LXC + Docker + clone sources GitHub
# + déploiement via le script de deploy défini par projet. À exécuter sur
# l'HÔTE PROXMOX, pas dans le LXC.
#
# Usage :
#   ./test-create-lxc.sh <fichier-config>
#   CLEANUP=1 ./test-create-lxc.sh <fichier-config>
#
# Exemple :
#   ./test-create-lxc.sh .env.test.docker
#
# Le fichier de config est résolu dans cet ordre :
#   1. chemin absolu (commence par /)
#   2. /opt/scripts/<nom>  (emplacement standard, peuplé par run-test.sh)
#   3. répertoire courant
#
# Variables requises dans le fichier de config (format `KEY="value"`) :
#   - GIT_REPO       ex: gaelgael5/agflow.docker
#   - GIT_BRANCH     ex: dev
#   - APP_DIR        ex: /opt/agflow.docker
#   - DEPLOY_SCRIPT  ex: ./dev-deploy.sh
#   - CTID_MIN       ex: 900
#   - CTID_MAX       ex: 999
#   - SCRIPTS_DIR    ex: /opt/scripts
#
# Pré-requis sur l'hôte Proxmox :
#   - <SCRIPTS_DIR>/.env.git  (TOKEN=ghp_... PAT GitHub avec scope `repo`)
#   - python3 (pour parser le JSON de create-lxc.sh)
#   - curl
###############################################################################
set -uo pipefail

# ══════════════════════════════════════════════════════════════════════════════
# CHARGEMENT DU FICHIER DE CONFIG (paramètre obligatoire)
# ══════════════════════════════════════════════════════════════════════════════
if [ $# -lt 1 ]; then
    echo "✗ Usage : $0 <fichier-config>" >&2
    echo "  Exemple : $0 .env.test.docker" >&2
    exit 1
fi

CONFIG_ARG="$1"

# Résolution du path du fichier de config :
#   - absolu (commence par /)        → utilisé tel quel
#   - relatif et présent dans /opt/scripts/ → /opt/scripts/<arg>
#   - relatif et présent dans pwd    → pwd/<arg>
#   - sinon                          → erreur
if [ "${CONFIG_ARG:0:1}" = "/" ]; then
    CONFIG_FILE="${CONFIG_ARG}"
elif [ -f "/opt/scripts/${CONFIG_ARG}" ]; then
    CONFIG_FILE="/opt/scripts/${CONFIG_ARG}"
elif [ -f "${CONFIG_ARG}" ]; then
    CONFIG_FILE="${PWD}/${CONFIG_ARG}"
else
    echo "✗ Fichier de config introuvable : '${CONFIG_ARG}'" >&2
    echo "  Cherché : /opt/scripts/${CONFIG_ARG} et ${PWD}/${CONFIG_ARG}" >&2
    exit 1
fi

if [ ! -f "${CONFIG_FILE}" ]; then
    echo "✗ Fichier de config inexistant : ${CONFIG_FILE}" >&2
    exit 1
fi

# Le fichier peut avoir été produit/édité sous Windows (CRLF). Sourcer
# directement attache alors un `\r` à chaque valeur, ce qui corrompt
# silencieusement URLs et chemins (curl récupère `https://…/repo\r` →
# requête malformée → `000`). On source une version débarrassée des `\r`.
_CONFIG_CLEAN="$(mktemp)"
tr -d '\r' < "${CONFIG_FILE}" > "${_CONFIG_CLEAN}"
# shellcheck source=/dev/null
. "${_CONFIG_CLEAN}"
rm -f "${_CONFIG_CLEAN}"

# Validation : toutes les variables requises doivent être définies et non vides
_missing=()
for _var in GIT_REPO GIT_BRANCH APP_DIR DEPLOY_SCRIPT CTID_MIN CTID_MAX SCRIPTS_DIR; do
    if [ -z "${!_var:-}" ]; then
        _missing+=("${_var}")
    fi
done
if [ ${#_missing[@]} -gt 0 ]; then
    echo "✗ Variables manquantes ou vides dans ${CONFIG_FILE} :" >&2
    for v in "${_missing[@]}"; do
        echo "    - ${v}" >&2
    done
    exit 1
fi

echo "[CONFIG] Fichier chargé : ${CONFIG_FILE}"
echo "         GIT_REPO=${GIT_REPO}  GIT_BRANCH=${GIT_BRANCH}"
echo "         APP_DIR=${APP_DIR}  DEPLOY_SCRIPT=${DEPLOY_SCRIPT}"
echo "         CTID range=${CTID_MIN}–${CTID_MAX}  SCRIPTS_DIR=${SCRIPTS_DIR}"
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# VARIABLES D'ENVIRONNEMENT (surchargeables au lancement)
# ══════════════════════════════════════════════════════════════════════════════
CLEANUP="${CLEANUP:-0}"

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTES (ne pas modifier)
# ══════════════════════════════════════════════════════════════════════════════
LIST_SCRIPT="${SCRIPTS_DIR}/list-instances.sh"
CREATE_SCRIPT="${SCRIPTS_DIR}/create-lxc.sh"
ENV_GIT="${SCRIPTS_DIR}/.env.git"

LIST_URL="https://raw.githubusercontent.com/Configurations/Proxmox/refs/heads/main/LXC/list-instances.sh"
CREATE_URL="https://raw.githubusercontent.com/Configurations/Proxmox/refs/heads/main/LXC/create-lxc.sh"

# Dériver le nom du projet depuis GIT_REPO (partie après le '/').
# Pour agflow.docker, ça donne "agflow.docker" — le `.` est OK pour le
# nom de LXC (test-agflow.docker-900) mais pas pour des contextes shell
# où ce serait un identifiant ; on l'utilise uniquement comme label.
PROJECT_NAME="${GIT_REPO##*/}"

# État global
TESTS_PASS=0
TESTS_FAIL=0
CREATED_CTID=""
CREATED_NAME=""
CT_IP=""

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════
log() {
    echo "[$(date +%H:%M:%S)] $*"
}

log_pass() {
    echo "  [PASS] $*"
    TESTS_PASS=$((TESTS_PASS + 1))
}

log_fail() {
    echo "  [FAIL] $*"
    TESTS_FAIL=$((TESTS_FAIL + 1))
}

fatal() {
    echo ""
    echo "[$(date +%H:%M:%S)] ERREUR FATALE : $*"
    echo ""
    if [ -n "${CREATED_CTID}" ]; then
        log "Nettoyage d'urgence du container ${CREATED_CTID}..."
        pct stop "${CREATED_CTID}" 2>/dev/null || true
        sleep 2
        pct destroy "${CREATED_CTID}" --purge 2>/dev/null || true
    fi
    exit 1
}

# Parser une valeur dans le JSON de create-lxc.sh via chemin pointé.
# Usage : json_get <json_string> <chemin.pointé>
json_get() {
    local json="$1"
    local key="$2"
    python3 -c "
import json, sys
data = json.loads(sys.argv[1])
keys = sys.argv[2].split('.')
val = data
for k in keys:
    if isinstance(val, dict):
        val = val.get(k)
    else:
        val = None
        break
print('' if val is None else str(val))
" "${json}" "${key}" 2>/dev/null || echo ""
}

# ══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 0 : Bootstrap — vérifier/télécharger les scripts
# ══════════════════════════════════════════════════════════════════════════════
log "=== ÉTAPE 0 : Bootstrap des scripts ==="

mkdir -p "${SCRIPTS_DIR}"

for entry in "${LIST_SCRIPT}:::${LIST_URL}" "${CREATE_SCRIPT}:::${CREATE_URL}"; do
    script_path="${entry%%:::*}"
    script_url="${entry##*:::}"
    script_name="$(basename "${script_path}")"

    if [ -f "${script_path}" ] && [ -x "${script_path}" ]; then
        log "  ${script_name} : présent et exécutable"
    elif [ -f "${script_path}" ]; then
        log "  ${script_name} : présent mais non exécutable -> chmod +x"
        chmod +x "${script_path}"
    else
        log "  ${script_name} : absent -> téléchargement..."
        if curl -fsSL "${script_url}" -o "${script_path}"; then
            chmod +x "${script_path}"
            log "  ${script_name} : téléchargé et rendu exécutable"
        else
            fatal "Impossible de télécharger ${script_name} depuis ${script_url}"
        fi
    fi
done

# ══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 1 : Vérification du token GitHub
# ══════════════════════════════════════════════════════════════════════════════
log ""
log "=== ÉTAPE 1 : Vérification de l'authentification GitHub ==="

if [ ! -f "${ENV_GIT}" ]; then
    echo ""
    echo "  ARRÊT : le fichier ${ENV_GIT} est absent."
    echo ""
    echo "  Ce fichier contient le token GitHub nécessaire pour cloner"
    echo "  les repos privés. Pour le créer :"
    echo ""
    echo "  1. Générer un Personal Access Token (PAT) sur GitHub :"
    echo "     https://github.com/settings/tokens"
    echo "     -> Generate new token (classic)"
    echo "     -> Scope : repo"
    echo "     -> Copier le token (commence par ghp_)"
    echo ""
    echo "  2. Créer le fichier :"
    echo "     echo 'TOKEN=ghp_VOTRE_TOKEN' > ${ENV_GIT}"
    echo "     chmod 600 ${ENV_GIT}"
    echo ""
    exit 1
fi

# Lire le token
TOKEN=$(grep '^TOKEN=' "${ENV_GIT}" | head -1 | cut -d= -f2- | tr -d '[:space:]')

if [ -z "${TOKEN}" ] || [ "${TOKEN}" = "ghp_" ]; then
    echo ""
    echo "  ARRÊT : TOKEN vide ou non renseigné dans ${ENV_GIT}."
    echo ""
    echo "  Éditer le fichier et remplacer la valeur TOKEN= :"
    echo "     nano ${ENV_GIT}"
    echo ""
    echo "  Format attendu : TOKEN=ghp_VOTRE_TOKEN"
    echo ""
    exit 1
fi

log "  Token trouvé dans ${ENV_GIT} (${#TOKEN} caractères)"

# Tester le token contre l'API GitHub
log "  Test de connectivité GitHub..."
GH_LOGIN=$(curl -sf -H "Authorization: token ${TOKEN}" \
    https://api.github.com/user 2>/dev/null \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('login',''))" \
    2>/dev/null || echo "")

if [ -z "${GH_LOGIN}" ]; then
    echo ""
    echo "  ARRÊT : le token GitHub est invalide ou expiré."
    echo ""
    echo "  Vérification manuelle :"
    echo "    source ${ENV_GIT}"
    echo "    curl -s -H \"Authorization: token \${TOKEN}\" https://api.github.com/user | grep login"
    echo ""
    echo "  Si le token est expiré, en générer un nouveau sur :"
    echo "    https://github.com/settings/tokens"
    echo ""
    exit 1
fi

log "  Authentification GitHub OK — connecté en tant que : ${GH_LOGIN}"

# Vérifier l'accès au repo cible
log "  Vérification de l'accès au repo ${GIT_REPO}..."
GH_REPO_STATUS=$(curl -sf -o /dev/null -w "%{http_code}" \
    -H "Authorization: token ${TOKEN}" \
    "https://api.github.com/repos/${GIT_REPO}" 2>/dev/null || echo "000")

if [ "${GH_REPO_STATUS}" != "200" ]; then
    echo ""
    echo "  ARRÊT : impossible d'accéder au repo ${GIT_REPO} (HTTP ${GH_REPO_STATUS})."
    echo ""
    echo "  Causes possibles :"
    echo "    - Le repo n'existe pas ou le nom est incorrect"
    echo "    - Le token n'a pas le scope 'repo'"
    echo "    - Le compte ${GH_LOGIN} n'a pas accès à ce repo"
    echo ""
    exit 1
fi

log "  Accès au repo ${GIT_REPO} : OK"

# ══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 2 : Trouver un CTID disponible (plage configurée)
# ══════════════════════════════════════════════════════════════════════════════
log ""
log "=== ÉTAPE 2 : Recherche d'un CTID disponible (${CTID_MIN}–${CTID_MAX}) ==="

INSTANCES_JSON=$("${LIST_SCRIPT}" 2>/dev/null) || fatal "list-instances.sh a échoué"

log "  Instances actuelles : ${INSTANCES_JSON}"

USED_IDS=$(python3 -c "
import json, sys
data = json.loads(sys.argv[1])
for d in data:
    print(d['id'])
" "${INSTANCES_JSON}" 2>/dev/null) || fatal "Impossible de parser le JSON de list-instances.sh"

CTID=""
for id in $(seq "${CTID_MIN}" "${CTID_MAX}"); do
    if ! echo "${USED_IDS}" | grep -qx "${id}"; then
        CTID="${id}"
        break
    fi
done

[ -z "${CTID}" ] && fatal "Aucun CTID disponible dans la plage ${CTID_MIN}–${CTID_MAX}"

log "  CTID retenu : ${CTID}"

# ══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 3 : Générer le nom de machine
# ══════════════════════════════════════════════════════════════════════════════
log ""
log "=== ÉTAPE 3 : Génération du nom de machine ==="

CREATED_NAME="test-${PROJECT_NAME}-${CTID}"
CREATED_CTID="${CTID}"

log "  Nom  : ${CREATED_NAME}"
log "  CTID : ${CREATED_CTID}"

# ══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 4 : Création du container de test
# ══════════════════════════════════════════════════════════════════════════════
log ""
log "=== ÉTAPE 4 : Création du container (--docker) ==="
log "  Commande : ${CREATE_SCRIPT} ${CREATED_CTID} ${CREATED_NAME} --docker"
log "  (cette étape peut prendre 2–5 minutes)"
echo ""

CREATE_OUTPUT=$("${CREATE_SCRIPT}" "${CREATED_CTID}" "${CREATED_NAME}" --docker 2>&1) || {
    RC=$?
    echo "${CREATE_OUTPUT}"
    echo ""
    if [ "${RC}" -eq 2 ]; then
        log "  Code retour 2 : Docker installé mais non opérationnel (partial)"
    else
        fatal "create-lxc.sh a échoué avec le code ${RC}"
    fi
}

echo "${CREATE_OUTPUT}"
echo ""

# Extraire la ligne JSON finale
RESULT_JSON=$(echo "${CREATE_OUTPUT}" | grep '^{' | tail -1)

[ -z "${RESULT_JSON}" ] && fatal "Aucune ligne JSON trouvée dans la sortie de create-lxc.sh"

log "  JSON capturé : OK (${#RESULT_JSON} caractères)"
CT_IP=$(json_get "${RESULT_JSON}" "machine.systeme.ip")

# ══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 5 : Pousser .env.git dans le LXC + clone des sources
# ══════════════════════════════════════════════════════════════════════════════
log ""
log "=== ÉTAPE 5 : Déploiement des sources GitHub ==="

# Pousser le .env.git dans le LXC
log "  Push de ${ENV_GIT} dans le LXC ${CREATED_CTID}..."
pct push "${CREATED_CTID}" "${ENV_GIT}" /root/.env.git \
    || fatal "Impossible de pousser .env.git dans le LXC"
pct exec "${CREATED_CTID}" -- chmod 600 /root/.env.git
log "  .env.git posé dans /root/.env.git"

# Construire l'URL HTTPS avec token
GIT_URL="https://${TOKEN}@github.com/${GIT_REPO}.git"
GIT_URL_SAFE="https://***@github.com/${GIT_REPO}.git"

log "  Clone de ${GIT_URL_SAFE} (branche ${GIT_BRANCH}) dans ${APP_DIR}..."

pct exec "${CREATED_CTID}" -- bash -c "
set -e

if [ -d '${APP_DIR}' ]; then
    echo '  -> Répertoire existant détecté -> suppression...'
    rm -rf '${APP_DIR}'
fi

mkdir -p \"\$(dirname '${APP_DIR}')\"
cd \"\$(dirname '${APP_DIR}')\"
git clone --branch '${GIT_BRANCH}' '${GIT_URL}' \"\$(basename '${APP_DIR}')\"
echo '  -> Clone terminé'
" || fatal "git clone a échoué dans le LXC ${CREATED_CTID}"

log "  Sources clonées dans ${APP_DIR}"

# ══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 6 : Lancement du script de déploiement
# ══════════════════════════════════════════════════════════════════════════════
log ""
log "=== ÉTAPE 6 : Déploiement applicatif (${DEPLOY_SCRIPT}) ==="

pct exec "${CREATED_CTID}" -- bash -c "
set -e
cd '${APP_DIR}'
SCRIPT_NAME='${DEPLOY_SCRIPT#./}'
if [ ! -f \"\${SCRIPT_NAME}\" ]; then
    echo 'ERREUR : ${DEPLOY_SCRIPT} introuvable dans ${APP_DIR}'
    ls -la
    exit 1
fi
chmod +x \"\${SCRIPT_NAME}\"
${DEPLOY_SCRIPT}
" || fatal "${DEPLOY_SCRIPT} a échoué dans le LXC ${CREATED_CTID}"

log "  Déploiement terminé"

# ══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 7 : Validation
# ══════════════════════════════════════════════════════════════════════════════
log ""
log "=== ÉTAPE 7 : Validation ==="

# Test 1 : status == "ok"
STATUS=$(json_get "${RESULT_JSON}" "status")
if [ "${STATUS}" = "ok" ]; then
    log_pass "status == \"ok\""
else
    log_fail "status == \"${STATUS}\" (attendu : \"ok\")"
fi

# Test 2 : IP non vide
if [ -n "${CT_IP}" ]; then
    log_pass "IP réseau obtenue : ${CT_IP}"
else
    log_fail "machine.systeme.ip est vide (DHCP non obtenu ?)"
fi

# Test 3 : docker_ok == 1
DOCKER_OK=$(json_get "${RESULT_JSON}" "docker.docker_ok")
if [ "${DOCKER_OK}" = "1" ]; then
    DOCKER_VER=$(json_get "${RESULT_JSON}" "docker.docker_version")
    log_pass "Docker opérationnel : ${DOCKER_VER}"
else
    log_fail "docker.docker_ok == \"${DOCKER_OK}\" (attendu : 1)"
fi

# Test 4 : hello_world_ok == true
HELLO_OK=$(json_get "${RESULT_JSON}" "docker.hello_world_ok")
if [ "${HELLO_OK}" = "True" ] || [ "${HELLO_OK}" = "true" ]; then
    log_pass "docker run hello-world : succès"
else
    log_fail "docker.hello_world_ok == \"${HELLO_OK}\" (attendu : true)"
fi

# Test 5 : répertoire sources présent dans le LXC
if pct exec "${CREATED_CTID}" -- test -d "${APP_DIR}"; then
    log_pass "Sources présentes dans ${APP_DIR}"
else
    log_fail "Répertoire ${APP_DIR} absent dans le LXC"
fi

# Test 6 : repo Git initialisé
if pct exec "${CREATED_CTID}" -- test -d "${APP_DIR}/.git"; then
    log_pass "Repo Git initialisé (.git présent)"
else
    log_fail "Répertoire .git absent — clone incomplet ?"
fi

# Test 7 : smoke /health via Caddy (port 80). Le port 8000 du backend n'est
# pas exposé hors du LXC — Caddy proxifie depuis :80. On boucle jusqu'à 60s
# (12 × 5s) car le boot du backend (pool DB + migrations + resolver) prend
# typiquement 5-20s même quand Docker déclare le container "healthy" tôt.
if [ -n "${CT_IP}" ]; then
    HEALTH_URL="http://${CT_IP}/health"
    HEALTH_OK=0
    for _try in $(seq 1 12); do
        if curl -sf -m 3 "${HEALTH_URL}" >/dev/null 2>&1; then
            HEALTH_OK=1
            break
        fi
        sleep 5
    done
    if [ "${HEALTH_OK}" = "1" ]; then
        log_pass "Backend répond sur ${HEALTH_URL}"
    else
        log_fail "Backend ne répond pas sur ${HEALTH_URL} après 60s"
    fi
fi

# Test 8 : exécution de la suite pytest dans le container backend.
# Image `agflow-backend:latest` buildée via `dev-deploy.sh` cible le stage
# `dev` du Dockerfile (qui inclut pytest + pytest-asyncio + /app/tests).
# Le container reçoit DATABASE_URL via env_file=.env, donc le setdefault
# de conftest.py n'écrase rien et les tests pointent vers le postgres
# local du LXC. Output complet affiché pour traçabilité ; --tb=short -q
# pour limiter le volume.
echo ""
echo "→ [Test 8] Exécution de pytest dans le container backend (peut prendre 1-2 min)..."
PYTEST_CMD="cd ${APP_DIR} && docker compose -f docker-compose.dev.yml exec -T backend pytest --tb=short -q"
if pct exec "${CREATED_CTID}" -- bash -c "${PYTEST_CMD}"; then
    log_pass "Suite pytest backend (exit 0)"
else
    _PYTEST_RC=$?
    log_fail "Suite pytest backend (exit ${_PYTEST_RC})"
fi

# ══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 7.9 : Validation E2E workflow hook
# ══════════════════════════════════════════════════════════════════════════════
log ""
log "=== ÉTAPE 7.9 : Validation E2E workflow hook ==="

WORKFLOW_HMAC_SECRET="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

# Test 9 : health check mock-receiver
if pct exec "${CREATED_CTID}" -- bash -c \
    "cd '${APP_DIR}' && docker compose -f docker-compose.dev.yml exec -T backend curl -sf 'http://mock-receiver:8001/health'" \
    > /dev/null 2>&1; then
    log_pass "mock-receiver health OK"
else
    log_fail "mock-receiver health check (service absent ou unhealthy)"
fi

# Reset état mock entre runs (idempotent — on tolère l'échec si absent)
pct exec "${CREATED_CTID}" -- bash -c \
    "cd '${APP_DIR}' && docker compose -f docker-compose.dev.yml exec -T backend curl -sX DELETE 'http://mock-receiver:8001/hooks'" \
    > /dev/null 2>&1 || true

# Récupérer le mot de passe admin depuis le .env du LXC
ADMIN_PASS_PLAIN=$(pct exec "${CREATED_CTID}" -- bash -c \
    "awk -F'=' '\$1==\"ADMIN_PASSWORD\"{sub(/^[^=]*=/,\"\");print;exit}' '${APP_DIR}/.env' | tr -d '\r'" \
    2>/dev/null || echo "")

# Test 10 : login admin et récupération du JWT
ADMIN_JWT=""
if [ -n "${ADMIN_PASS_PLAIN}" ]; then
    ADMIN_JWT=$(pct exec "${CREATED_CTID}" -- curl -sS -X POST "http://localhost/api/admin/auth/login" \
        -H 'Content-Type: application/json' \
        -d "{\"email\":\"admin@agflow.example.com\",\"password\":\"${ADMIN_PASS_PLAIN}\"}" \
        2>/dev/null \
        | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" \
        2>/dev/null || echo "")
fi

if [ -n "${ADMIN_JWT}" ]; then
    log_pass "admin login OK (JWT obtenu)"
else
    log_fail "admin login (ADMIN_PASSWORD vide ou endpoint indisponible)"
fi

if [ -n "${ADMIN_JWT}" ]; then
    # Test 11 : créer la hmac_key e2e-test
    HMAC_BODY="{\"key_id\":\"e2e-test\",\"secret_hex\":\"${WORKFLOW_HMAC_SECRET}\",\"description\":\"E2E\"}"
    HMAC_RESP=$(pct exec "${CREATED_CTID}" -- curl -sS -X POST "http://localhost/api/admin/hmac-keys" \
        -H "Authorization: Bearer ${ADMIN_JWT}" \
        -H 'Content-Type: application/json' \
        -d "${HMAC_BODY}" 2>/dev/null || echo "")

    if echo "${HMAC_RESP}" | grep -q "e2e-test"; then
        log_pass "POST /hmac-keys e2e-test créée"
    else
        log_fail "POST /hmac-keys : ${HMAC_RESP}"
    fi

    # Insérer directement une row outbound_hooks pour simuler un hook pending
    HOOK_ID=$(pct exec "${CREATED_CTID}" -- uuidgen 2>/dev/null \
        || echo "00000000-0000-4000-8000-000000000e2e")
    INSERT_SQL="INSERT INTO outbound_hooks (hook_id, task_id, callback_url, hmac_key_id, payload, status, attempt_number, next_retry_at) VALUES ('${HOOK_ID}', NULL, 'http://mock-receiver:8001/api/v1/hooks/docker/task-completed', 'e2e-test', '{\"status\":\"completed\",\"summary\":\"e2e test\"}'::jsonb, 'pending', 0, now())"
    pct exec "${CREATED_CTID}" -- bash -c \
        "docker exec agflow-postgres psql -U agflow -d agflow -c \"${INSERT_SQL}\"" \
        > /dev/null 2>&1 || true

    # Attendre le hook_dispatcher (cycle 2s + marge 4s)
    sleep 6

    # Test 12 : mock-receiver a reçu exactement 1 hook signé
    HOOKS_JSON=$(pct exec "${CREATED_CTID}" -- bash -c \
        "cd '${APP_DIR}' && docker compose -f docker-compose.dev.yml exec -T backend curl -sS 'http://mock-receiver:8001/hooks'" \
        2>/dev/null || echo "{}")
    HOOK_COUNT=$(echo "${HOOKS_JSON}" \
        | python3 -c "import sys,json; print(json.load(sys.stdin).get('count', 0))" \
        2>/dev/null || echo "0")

    if [ "${HOOK_COUNT}" = "1" ]; then
        log_pass "mock-receiver a reçu 1 hook signé HMAC validé"
    else
        log_fail "mock-receiver count=${HOOK_COUNT} (attendu 1)"
    fi

    # Vérifier que la row outbound_hooks est marquée delivered
    HOOK_STATUS=$(pct exec "${CREATED_CTID}" -- bash -c \
        "docker exec agflow-postgres psql -U agflow -d agflow -tAc \"SELECT status FROM outbound_hooks WHERE hook_id = '${HOOK_ID}'\"" \
        2>/dev/null | tr -d '[:space:]')

    if [ "${HOOK_STATUS}" = "delivered" ]; then
        log_pass "outbound_hooks row marquée delivered"
    else
        log_fail "outbound_hooks status=${HOOK_STATUS} (attendu delivered)"
    fi
else
    # JWT non obtenu : les 3 tests suivants échouent automatiquement
    log_fail "POST /hmac-keys (JWT absent — dépendance test 10)"
    log_fail "mock-receiver hook reçu (JWT absent — dépendance test 10)"
    log_fail "outbound_hooks delivered (JWT absent — dépendance test 10)"
fi

# ══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 8 : Nettoyage (optionnel)
# ══════════════════════════════════════════════════════════════════════════════
log ""
log "=== ÉTAPE 8 : Nettoyage ==="

if [ "${CLEANUP}" = "1" ]; then
    log "  CLEANUP=1 -> arrêt et suppression du container ${CREATED_CTID}..."
    pct stop "${CREATED_CTID}" 2>/dev/null || true
    sleep 3
    pct destroy "${CREATED_CTID}" --purge 2>/dev/null \
        || pct destroy "${CREATED_CTID}" 2>/dev/null \
        || log "  ATTENTION : pct destroy a échoué — suppression manuelle nécessaire"
    log "  Container ${CREATED_CTID} supprimé"
else
    log "  CLEANUP non défini -> container conservé pour inspection"
    log "  Accès  : pct enter ${CREATED_CTID}"
    [ -n "${CT_IP}" ] && \
        log "  SSH    : ssh -i /root/.ssh/lxc-keys/id_ed25519_lxc${CREATED_CTID} root@${CT_IP}"
    log "  Sources: ${APP_DIR}"
    log "  Pour supprimer : pct stop ${CREATED_CTID} && pct destroy ${CREATED_CTID} --purge"
fi

# ══════════════════════════════════════════════════════════════════════════════
# RAPPORT FINAL
# ══════════════════════════════════════════════════════════════════════════════
TESTS_TOTAL=$((TESTS_PASS + TESTS_FAIL))

echo ""
echo "========================================="
echo "  RÉSULTAT DES TESTS"
echo "========================================="
printf "  %-12s : %s\n" "Projet"     "${PROJECT_NAME}"
printf "  %-12s : %s\n" "CTID"       "${CREATED_CTID}"
printf "  %-12s : %s\n" "Nom"        "${CREATED_NAME}"
printf "  %-12s : %s\n" "IP"         "${CT_IP:-non obtenue}"
printf "  %-12s : %s\n" "Branche"    "${GIT_BRANCH}"
printf "  %-12s : %s\n" "Sources"    "${APP_DIR}"
echo "  -----------------------------------------"
printf "  %-12s : %s/%s\n" "Tests OK"   "${TESTS_PASS}" "${TESTS_TOTAL}"
printf "  %-12s : %s/%s\n" "Tests FAIL" "${TESTS_FAIL}" "${TESTS_TOTAL}"
echo ""

if [ "${TESTS_FAIL}" -eq 0 ]; then
    printf "  %-12s : OK SUCCES\n" "Statut"
    echo "========================================="
    exit 0
elif [ "${TESTS_PASS}" -gt 0 ]; then
    printf "  %-12s : ECHEC PARTIEL (%s/%s OK)\n" "Statut" "${TESTS_PASS}" "${TESTS_TOTAL}"
    echo "========================================="
    exit 1
else
    printf "  %-12s : ECHEC\n" "Statut"
    echo "========================================="
    exit 1
fi
