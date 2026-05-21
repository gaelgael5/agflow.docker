#!/usr/bin/env bash
# ============================================================
# cloudflare_ingress_upsert.sh
#
# Crée ou met à jour une règle d'ingress Cloudflare via
# l'API du service `cloudflare-manager`
# (cf. https://github.com/gaelgael5/cloudflare-manager).
#
# Mode opératoire :
#   1. GET /ingress/<hostname> pour savoir si la règle existe
#   2. Si elle existe (HTTP 200)  → PUT /ingress/<hostname>  (replace)
#   3. Sinon                       → POST /ingress           (create)
#
# Idempotent : peut être ré-exécuté autant de fois que voulu sans
# casser l'état (le dernier état désiré gagne).
#
# Paramètres (substitués par agflow.docker via {NAME} → input_values
# au moment de l'exécution) :
#   {CF_MANAGER_URL}      URL du service cloudflare-manager
#                         ex: http://192.168.10.112:8000
#   {CF_MANAGER_API_KEY}  Bearer token du cloudflare-manager (clair après
#                         résolution — voir RÉSOLUTION DES SECRETS ci-dessous)
#   {HOSTNAME}            hostname public à exposer
#                         ex: outline.yoops.org
#   {SERVICE}             URL interne cible (schéma + IP + port)
#                         ex: http://192.168.10.50:3000
#
# ------------------------------------------------------------
# RÉSOLUTION DES SECRETS (chaîne agflow → .env → script)
# ------------------------------------------------------------
# Le runner de script (project_deployments._run_group_script) n'appelle PAS
# directement le SDK Harpocrate. Il fait deux passes de texte :
#
#   1. _resolve_input_value(raw, env_text) :
#      Substitue ${VAR} dans link.input_values contre le `.env` du déploiement.
#      Si une clé n'est pas dans le .env, la chaîne ${VAR} reste littérale
#      (le script reçoit alors `${VAR}` comme valeur — Bearer invalide → 401).
#
#   2. _substitute_script_placeholders(script_content, resolved_inputs) :
#      Remplace les {NAME} du script par les valeurs résolues.
#
# Pour que `${CLOUDFLARE_MANAGER_API_KEY}` (configuré dans les input_values
# du group_script) soit résolu, la clé `CLOUDFLARE_MANAGER_API_KEY` doit
# exister dans le `.env` du déploiement. Le `.env` est généré au Generate
# par project_deployments_service à partir des recettes du projet :
#
#   - Soit une recette déclare le secret dans `secrets_required` (avec
#     generate:null pour saisie manuelle), et la valeur est piochée depuis
#     les user_secrets / platform_secrets (qui eux passent par Harpocrate).
#   - Soit la valeur est saisie en clair dans les input_values du script
#     (déconseillé — moins sécurisé que le passage par Harpocrate en amont).
#
# Concrètement, pour ce script :
#   input_values:
#     CF_MANAGER_API_KEY: ${CLOUDFLARE_MANAGER_API_KEY}   # référence .env
#   ↓
#   Le .env du déploiement contient : CLOUDFLARE_MANAGER_API_KEY=xxx
#   ↓
#   Le runner substitue → le script reçoit la valeur en clair dans {CF_MANAGER_API_KEY}
#
# Sortie :
#   - stdout/stderr classiques pour les logs
#   - DERNIÈRE ligne stdout = JSON parsable par agflow
#     ({"status":"ok","action":"created|updated","hostname":"..."})
#     Le mécanisme _parse_last_json côté backend peut alors
#     éventuellement injecter ces valeurs dans le .env du déploiement.
#
# ------------------------------------------------------------
# EXEMPLE 1 — Usage normal (via agflow, recommandé)
# ------------------------------------------------------------
# 1. Crée ce script dans la page Scripts d'agflow.
# 2. Déclare ses input_variables :
#       CF_MANAGER_URL       (texte, ex: http://192.168.10.112:8000)
#       CF_MANAGER_API_KEY   (secret, ex: ${CLOUDFLARE_MANAGER_API_KEY})
#       HOSTNAME             (texte, ex: outline.yoops.org)
#       SERVICE              (texte, ex: http://192.168.10.50:3000)
# 3. Sur le groupe qui héberge la ressource, attache ce script avec :
#       Cible   = "Machine de déploiement"  (résolu sur groups.machine_id)
#       Timing  = "after"                   (après que les containers sont up)
#       Inputs  = { CF_MANAGER_URL: "...", CF_MANAGER_API_KEY: "${CLOUDFLARE_MANAGER_API_KEY}",
#                   HOSTNAME: "outline.yoops.org", SERVICE: "http://..." }
# 4. Au push du déploiement, agflow substitue les {NAME} dans le contenu
#    du script puis l'upload et l'exécute sur la machine de déploiement.
#
# ------------------------------------------------------------
# EXEMPLE 2 — Test en standalone (sans agflow)
# ------------------------------------------------------------
# Utile pour vérifier que le manager Cloudflare répond avant de brancher
# tout l'enchaînement. On substitue les placeholders à la volée avec sed :
#
#   sed -e 's|{CF_MANAGER_URL}|http://192.168.10.112:8000|g' \
#       -e 's|{CF_MANAGER_API_KEY}|votre-bearer-token|g' \
#       -e 's|{HOSTNAME}|outline.yoops.org|g' \
#       -e 's|{SERVICE}|http://192.168.10.50:3000|g' \
#       cloudflare_ingress_upsert.sh | bash
#
# Sortie attendue (la dernière ligne) :
#   {"status":"ok","action":"created","hostname":"outline.yoops.org","service":"http://192.168.10.50:3000"}
#
# Pour une mise à jour (l'hôte existait déjà) :
#   {"status":"ok","action":"updated","hostname":"outline.yoops.org","service":"http://192.168.10.50:3000"}
#
# Codes de sortie :
#   0  succès
#   1  appel API en erreur (status HTTP autre que 200/404)
#   2  paramètres manquants (placeholder non substitué)
# ============================================================
set -euo pipefail

CF_MANAGER_URL="{CF_MANAGER_URL}"
CF_MANAGER_API_KEY="{CF_MANAGER_API_KEY}"
HOSTNAME_TARGET="{HOSTNAME}"
SERVICE_TARGET="{SERVICE}"

# --- Validation basique des paramètres ---
missing=()
[ -z "${CF_MANAGER_URL}" ] || [ "${CF_MANAGER_URL}" = "{CF_MANAGER_URL}" ] && missing+=("CF_MANAGER_URL")
[ -z "${CF_MANAGER_API_KEY}" ] || [ "${CF_MANAGER_API_KEY}" = "{CF_MANAGER_API_KEY}" ] && missing+=("CF_MANAGER_API_KEY")
[ -z "${HOSTNAME_TARGET}" ] || [ "${HOSTNAME_TARGET}" = "{HOSTNAME}" ] && missing+=("HOSTNAME")
[ -z "${SERVICE_TARGET}" ] || [ "${SERVICE_TARGET}" = "{SERVICE}" ] && missing+=("SERVICE")
if [ "${#missing[@]}" -gt 0 ]; then
  echo "ERREUR : paramètres manquants : ${missing[*]}" >&2
  echo '{"status":"error","reason":"missing_params"}'
  exit 2
fi

CF_MANAGER_URL="${CF_MANAGER_URL%/}"  # retire un slash final éventuel

echo "→ Cible      : ${HOSTNAME_TARGET}"
echo "→ Service    : ${SERVICE_TARGET}"
echo "→ Manager    : ${CF_MANAGER_URL}"

# --- 1. La règle existe-t-elle déjà ? ---
http_get_status=$(
  curl -sS -o /tmp/cf_get_$$.body -w "%{http_code}" \
    -H "Authorization: Bearer ${CF_MANAGER_API_KEY}" \
    "${CF_MANAGER_URL}/ingress/${HOSTNAME_TARGET}" \
    || echo "000"
)
rm -f /tmp/cf_get_$$.body

# --- 2. Construire le payload ---
payload=$(printf '{"hostname":"%s","service":"%s"}' \
  "${HOSTNAME_TARGET}" "${SERVICE_TARGET}")

# --- 3. PUT (update) si la règle existe, POST (create) sinon ---
if [ "${http_get_status}" = "200" ]; then
  action="updated"
  echo "→ Règle existante détectée, mise à jour…"
  response=$(curl -fsS -X PUT \
    -H "Authorization: Bearer ${CF_MANAGER_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "${payload}" \
    "${CF_MANAGER_URL}/ingress/${HOSTNAME_TARGET}")
elif [ "${http_get_status}" = "404" ]; then
  action="created"
  echo "→ Règle absente, création…"
  response=$(curl -fsS -X POST \
    -H "Authorization: Bearer ${CF_MANAGER_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "${payload}" \
    "${CF_MANAGER_URL}/ingress")
else
  echo "ERREUR : réponse inattendue du manager (HTTP ${http_get_status})" >&2
  printf '{"status":"error","reason":"unexpected_http_status","http_status":"%s"}\n' "${http_get_status}"
  exit 1
fi

echo "← Réponse manager : ${response}"
echo "✓ Route ${HOSTNAME_TARGET} → ${SERVICE_TARGET} (${action})"

# Dernière ligne = JSON parsable par agflow.
printf '{"status":"ok","action":"%s","hostname":"%s","service":"%s"}\n' \
  "${action}" "${HOSTNAME_TARGET}" "${SERVICE_TARGET}"
