# Test A03 — Création d'un projet et de ses ressources (opérateur)

> **📋 Cartouche — Scénario opérateur A03**
>
> **Scénario fonctionnel** : `../A03-project-setup.md`
> **Objectif** : créer un projet → produit `PROJECT_UUID` pour le test 04
> **Durée** : <5s
> **Dépendances** : `ADMIN_JWT`
> **Idempotent** : oui (réutilise le projet existant si `display_name` match)
>
> **Étapes vérifiées (4)** :
> 1. Création/vérif projet `Tests fonctionnels`
> 2. `GET /projects/{uuid}` → projet lisible
> 3. `GET /projects/{uuid}/full` → groupes (peut être vide)
> 4. Affichage `PROJECT_UUID` à exporter pour le test 04
>
> **Limitation V1** : pas de gestion des ressources/fichiers projet via API admin —
> les fichiers transitent par le workspace Docker ou via un MCP filesystem.

Implémentation exécutable du scénario fonctionnel
`docs/functionnalTests/A03-project-setup.md`. Pré-requis pour la partie
"ressources projet" du cas 04.

## Préconditions

- `BASE_URL`, `ADMIN_JWT` exportés (voir A01 étape 1)

## Données utilisées

Voir `00-test-data.md` §4.3.

| Donnée | Valeur |
|--------|--------|
| `display_name` | `Tests fonctionnels` |
| `description` | `Projet utilisé par les tests fonctionnels 04` |
| Ressource initiale | (placeholder texte — voir notes) |

## Étapes

```bash
set -euo pipefail
: "${BASE_URL:?BASE_URL must be set}"
: "${ADMIN_JWT:?ADMIN_JWT must be set (cf. A01 étape 1)}"

H_ADMIN=(-H "Authorization: Bearer $ADMIN_JWT")
H_JSON=(-H "Content-Type: application/json")

PROJECT_DISPLAY_NAME="Tests fonctionnels"

# 1. Créer ou réutiliser le projet
echo "==> 1. Création/vérification projet '$PROJECT_DISPLAY_NAME'"
EXISTING_UUID=$(curl -fsS "${H_ADMIN[@]}" "$BASE_URL/api/admin/projects" \
  | jq -r --arg name "$PROJECT_DISPLAY_NAME" \
      '.[] | select(.display_name == $name) | .id' | head -1)
if [[ -z "$EXISTING_UUID" ]]; then
  PROJECT=$(curl -fsS -X POST "$BASE_URL/api/admin/projects" \
    "${H_ADMIN[@]}" "${H_JSON[@]}" \
    -d "{
      \"display_name\":\"$PROJECT_DISPLAY_NAME\",
      \"description\":\"Projet utilisé par les tests fonctionnels 04\"
    }")
  PROJECT_UUID=$(echo "$PROJECT" | jq -r '.id')
  echo "    projet créé : $PROJECT_UUID"
else
  PROJECT_UUID="$EXISTING_UUID"
  echo "    projet existant réutilisé : $PROJECT_UUID"
fi

# 2. Vérifier qu'il est lisible
echo "==> 2. GET /projects/$PROJECT_UUID"
curl -fsS "${H_ADMIN[@]}" "$BASE_URL/api/admin/projects/$PROJECT_UUID" \
  | jq -e --arg uuid "$PROJECT_UUID" '.id == $uuid' >/dev/null \
  || { echo "FAIL: projet non lisible"; exit 1; }

# 3. Récupérer la vue full (groupes + instances) — devrait être vide
echo "==> 3. GET /projects/$PROJECT_UUID/full"
FULL=$(curl -fsS "${H_ADMIN[@]}" "$BASE_URL/api/admin/projects/$PROJECT_UUID/full")
echo "$FULL" | jq -e '.id and .groups' >/dev/null \
  || { echo "FAIL: vue full mal formée"; exit 1; }
GROUPS_COUNT=$(echo "$FULL" | jq '.groups | length')
echo "    groupes : $GROUPS_COUNT"

# 4. Vérification finale
echo "==> 4. Récap"
echo "    PROJECT_UUID=$PROJECT_UUID"
echo
echo "================================================================"
echo "PROJECT_UUID=$PROJECT_UUID"
echo "================================================================"
echo "Exporter cette valeur avant de lancer le test 04 :"
echo "    export PROJECT_UUID='$PROJECT_UUID'"
echo

echo "PASS — Test A03 project-setup"
```

## Résultats attendus (récap)

| Étape | HTTP | Assertion |
|-------|------|-----------|
| 1 — POST /projects | 201 ou idempotent | `.id` UUID |
| 2 — GET /projects/{id} | 200 | `.id == PROJECT_UUID` |
| 3 — GET /projects/{id}/full | 200 | `.id` et `.groups` (tableau, possiblement vide) |

## Nettoyage (optionnel)

```bash
# DELETE /api/admin/projects/{id} — destructif (pas de corbeille)
# Ne supprimer que si on est sûr que personne d'autre ne s'en sert.
curl -fsS -X DELETE "${H_ADMIN[@]}" "$BASE_URL/api/admin/projects/$PROJECT_UUID" \
  -w "%{http_code}\n" || true
```

## Notes / limitations

- **Ressources initiales du projet** : le scénario fonctionnel d'origine prévoit
  l'ajout de fichiers de spec (`specs/feature-x.md`) au projet via l'admin API.
  En V1, la gestion des ressources/livrables d'un projet passe par les
  **groupes** et **instances de produits** (catalogue Y) du module M7, pas par
  un endpoint "fichiers projet" générique. Le test ne crée donc pas de
  ressource type fichier — la lecture/écriture par les agents passe par le
  workspace Docker monté à l'instanciation.
- En conséquence, le **cas 04** valide uniquement l'**héritage du
  `project_id`** sur la session, et la disponibilité du workspace. La
  vérification effective de "l'agent a lu un fichier projet" demande soit un
  groupe/instance, soit un MCP filesystem (cf. A02).
- Pour des tests qui exigent un fichier projet concret, prévoir une itération
  où on crée un groupe + une instance de catalogue qui pousse un fichier dans
  le workspace partagé. Hors scope V1 happy path.
