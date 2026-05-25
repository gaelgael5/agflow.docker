# Résolveur unifié des placeholders d'input + support `${env-machine://}` — Design

**Date** : 2026-05-25
**Branche** : `dev`
**Statut** : Design approuvé, plan d'implémentation à écrire

## Contexte

Le projet supporte plusieurs syntaxes de placeholders dans `group_scripts.input_values` (la valeur saisie par l'utilisateur pour chaque variable d'entrée d'un script de groupe) :

| Syntaxe | Sens | Statut backend actuel |
|---|---|---|
| `${VAR}` | Référence vers une variable du `.env` de déploiement | ✅ Résolu (regex `[A-Z_][A-Z0-9_]*`) |
| `${env://NAME}` | Variable globale (table `platform_secrets`) | ✅ Résolu |
| `${vault://api:NAME}` | Secret stocké dans Harpocrate | ✅ Résolu |
| `${env-machine://<machine>:<VAR>}` | Variable d'env d'une machine distante (`infra_env_vars`) | ❌ **Non résolu** |

Deux bugs distincts en découlent :

**Bug 1 — Faux positif dans la bannière de pré-déploiement.** `check_project_env_vars` (`backend/src/agflow/services/infra_env_vars_service.py:288-352`) ne lit jamais la colonne `group_scripts.input_values`. Le check considère une variable couverte uniquement si elle apparaît dans les `infra_env_vars` de la machine cible **ou** dans les `group_variables` du groupe. Donc une valeur `${env-machine://keycloak1:KC_ADMIN_PASSWORD}` (qui pointe vers une autre machine) est ignorée et affiche un faux positif.

**Bug 2 — Résolution exécution incomplète et silencieusement défaillante.** Les comportements actuels en cas de ref non résoluble sont incohérents :
- `vault://` / `env://` (`platform_secrets_service.resolve_platform_refs:195-203`) → **substitution silencieuse par chaîne vide**
- `${VAR}` (`deployment_env_helpers.resolve_input_value:31-37`) → **littéral conservé silencieusement**
- `env-machine://` → non géré du tout, le shell verrait la chaîne brute

Un déploiement peut ainsi s'exécuter avec un mot de passe vide sans alerte.

## Objectifs

1. Centraliser la résolution des 4 syntaxes dans un service dédié, réutilisé par les 3 callsites (check, `_run_group_script`, `deployment_executor.execute_step`).
2. Adopter une politique **fail-fast** alignée pour les 4 syntaxes à l'exécution : un placeholder non résoluble (ou résolvant vers vide) fait échouer le step avec un message explicite.
3. Étendre la bannière de pré-déploiement pour qu'elle utilise le même résolveur en mode "collect-all" : check vert ⇔ exécution OK garanti par construction.
4. Reporter une **raison** détaillée par variable non résoluble dans la bannière.

## Non-objectifs

- Refs vers les outputs des `before_scripts` du même groupe (extension future).
- Résolution récursive (`${env-machine://X:VAR}` où la value sur X contient elle-même `${...}`) — résolution simple passe.
- Cache des `infra_env_vars_service.resolve_for_machine` entre group_scripts d'un même check (à mesurer, ajouter si latence > 500 ms).
- Migration des `group_scripts.input_values` existants en base : le format ne change pas, seule son interprétation côté backend évolue.
- Modification du hook `useEnvMachineVarCheck` côté frontend : il reste pour le feedback immédiat dans le dialog d'édition de script.

## Architecture

### Nouveau module `backend/src/agflow/services/input_resolver.py`

```python
class UnresolvedPlaceholderError(Exception):
    def __init__(
        self,
        kind: Literal["value_empty", "var_not_in_env",
                      "platform_secret_missing",
                      "machine_not_found",
                      "env_machine_var_not_found",
                      "env_machine_var_empty"],
        ref: str,
        detail: str,
        var_name: str | None = None,
    ): ...

async def resolve_input_values(
    input_values: dict[str, str],
    *,
    target_machine_id: UUID,
    env_text: str,
    platform_secrets_map: dict[str, str],
) -> dict[str, str]:
    """Résolution fail-fast. Lève UnresolvedPlaceholderError au 1er échec."""

async def resolve_input_values_collect(
    input_values: dict[str, str],
    *,
    target_machine_id: UUID,
    env_text: str,
    platform_secrets_map: dict[str, str],
) -> tuple[dict[str, str], list[UnresolvedPlaceholderError]]:
    """Résolution "collect-all". Retourne dict partiel + liste d'erreurs accumulées."""
```

### Module helper `backend/src/agflow/services/placeholder_parsers.py`

Regex et parsers purs, **pas d'I/O**. Permet de tester les parsers sans mocks.

```python
ENV_MACHINE_RE = re.compile(r"\$\{env-machine://([^:}]+):([^}]+)\}")
VAULT_RE = re.compile(r"\$\{vault://[^:}]+:([^}]+)\}")
ENV_RE = re.compile(r"\$\{env://([^}]+)\}")
SIMPLE_VAR_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}|\$([A-Z_][A-Z0-9_]*)")

def parse_env_machine_ref(value: str) -> tuple[str, str] | None: ...
def parse_env_text(env_text: str) -> dict[str, str]: ...
```

### Ordre de résolution

Pour chaque `input_values[var_name]`, ordre figé :

1. **`${env-machine://<machine>:<VAR>}`** → lookup machine par nom via `machines_service.get_by_name`, puis `infra_env_vars_service.resolve_for_machine(machine_id)`, attendre une value non-vide.
2. **`${vault://api:NAME}`** → lookup dans `platform_secrets_map`, attendre une value non-vide.
3. **`${env://NAME}`** → lookup dans `platform_secrets_map`, attendre une value non-vide.
4. **`${VAR}` / `$VAR`** (regex `[A-Z_][A-Z0-9_]*`) → lookup dans `env_text` parsé, attendre une value non-vide.
5. Si la valeur est entièrement littérale (pas de `${}`) **et** non-vide → conservée telle quelle.
6. Si la valeur est vide → `UnresolvedPlaceholderError(kind="value_empty", ...)`.

Un échec à toute étape lève `UnresolvedPlaceholderError` avec un `kind` parmi :
- `value_empty` — valeur entièrement vide
- `var_not_in_env` — `${VAR}` introuvable dans `.env` ou présent avec value vide
- `platform_secret_missing` — `${vault://…}` ou `${env://…}` introuvable ou vide
- `machine_not_found` — machine inconnue
- `env_machine_var_not_found` — machine OK mais variable absente OU présente avec value vide (cf. note ci-dessous)
- `unknown_ref` — substring `${…}` ne matche aucun des 4 patterns connus

**Note sur le kind absent `env_machine_var_empty`** : le plan initial prévoyait un 7ᵉ kind `env_machine_var_empty` distinct. Lors de l'implémentation (commit `6fe8aea`), on a constaté que `infra_env_vars_service.resolve_for_machine` (utilisé par le resolver) filtre déjà les valeurs vides. Du point de vue du resolver, une variable vide en DB est indistinguable d'une variable absente. Le kind a donc été supprimé et `env_machine_var_not_found` couvre les deux cas. Taxonomie finale : **6 kinds**.

### Cas limites

**Valeurs mixtes (`prefix-${env://NAME}-suffix`)** : supportées. Le resolver effectue un `re.sub` séquentiel des 4 patterns puis assemble. Toute ref non résoluble dans une valeur mixte fait échouer le résolveur (fail-fast) — pas de substitution partielle silencieuse.

**Substring `${…}` non reconnue** (ex: `${foo-bar}`, `${non.standard}`) : lève `UnresolvedPlaceholderError(kind="unknown_ref", ref=<la_substring>)`. C'est une erreur de saisie probable ; laisser le shell échouer derrière serait silencieux.

**Résolution vers chaîne vide** : toute ref qui résout vers `""` est traitée comme non résoluble (cf. les `kind` `*_empty` / `*_missing` ci-dessus). Cohérent avec le fait que `infra_env_vars_service.resolve_for_machine` filtre déjà les valeurs vides.

**Pas de récursion** : si `infra_env_vars[X][VAR] = "${OTHER}"`, le resolver renvoie `"${OTHER}"` brut. La récursion serait un trou de sécurité (boucles, refs croisées) et n'est pas dans le périmètre.

### Intégrations

- **`backend/src/agflow/api/admin/project_deployments.py:297-336`** (`_run_group_script`) — remplace la double boucle de résolution par un appel à `input_resolver.resolve_input_values(...)`. Sur `UnresolvedPlaceholderError`, retourne `{"success": False, "error": <msg>}` sans tenter l'upload SSH.
- **`backend/src/agflow/services/deployment_executor.py`** (`execute_step`) — même remplacement, en intégrant le message d'erreur dans le `StepLog` et en faisant transitionner le déploiement vers `step_failed` via le mécanisme existant `fail_step` (cf. commit 5175621).
- **`backend/src/agflow/services/infra_env_vars_service.py:288-352`** (`check_project_env_vars`) — pour chaque group_script avec via_env vars, appelle `input_resolver.resolve_input_values_collect(...)` et transforme les erreurs accumulées en `ProjectEnvVarsCheckMissingReason`.

## Schémas API

### `backend/src/agflow/schemas/infra_env_vars.py`

**Breaking change** sur `ProjectEnvVarsCheckMissing`. Pas de DB impactée (pas persisté). Un seul consommateur (la bannière `ProjectDetailPage`). Pas de compat shim.

```python
class ProjectEnvVarsCheckMissingReason(BaseModel):
    var_name: str
    kind: Literal[
        "value_empty",
        "var_not_in_env",
        "platform_secret_missing",
        "machine_not_found",
        "env_machine_var_not_found",
        "unknown_ref",
    ]
    ref: str       # ex: "${env-machine://keycloak1:KC_ADMIN_PASSWORD}"
    detail: str    # ex: "machine 'keycloak1' inconnue"

class ProjectEnvVarsCheckMissing(BaseModel):
    group_script_id: UUID
    script_id: UUID
    script_name: str
    group_id: UUID
    group_name: str
    machine_id: UUID | None
    machine_name: str | None
    target_kind: str
    # AVANT : missing_env_vars: list[str]
    missing: list[ProjectEnvVarsCheckMissingReason]
```

`ProjectEnvVarsCheck.total_missing` reste mais devient `sum(len(it.missing) for it in items)`.

## Flux de données

### Exécution (fail-fast)

```
deployment_executor.execute_step(deployment_id, step_index)
  ├─► récupère le group_script `link` + script_content
  ├─► résout target_machine_id (resolve_target_machine_id)
  ├─► reconstitue env_text (= contenu du .env accumulé)
  ├─► platform_secrets_map = await platform_secrets_service.resolve_all()
  ├─► try:
  │     resolved = await input_resolver.resolve_input_values(
  │         input_values=link.input_values or {},
  │         target_machine_id=target_machine_id,
  │         env_text=env_text,
  │         platform_secrets_map=platform_secrets_map,
  │     )
  │   except UnresolvedPlaceholderError as exc:
  │     → fail_step avec message "Variable '{exc.var_name}' non résoluble: {exc.detail}"
  │     → return (pas d'upload SSH)
  └─► sinon: rendered = substitute_script_placeholders(content, resolved) → upload + exec
```

### Pré-déploiement (collect-all)

```
GET /api/admin/projects/{id}/env-vars-check
  └─► check_project_env_vars(project_id)
       └─► pour chaque group:
            ├─► group_var_names = noms des group_variables non vides
            ├─► env_text = reconstitution depuis group_variables (k=v\n…)
            ├─► platform_secrets_map = await platform_secrets_service.resolve_all()
            └─► pour chaque group_script avec via_env vars:
                 ├─► résoudre target_machine_id (cf. logique existante target_kind)
                 │    └─► si KO (deployment_host sans host) → skip group_script
                 ├─► resolved, errors = await input_resolver.resolve_input_values_collect(
                 │       input_values=gs.input_values or {},
                 │       target_machine_id=machine_id,
                 │       env_text=env_text,
                 │       platform_secrets_map=platform_secrets_map,
                 │   )
                 ├─► pour chaque via_env var v du script:
                 │    └─► si v.name dans errors → append à items[i].missing
                 │         (avec kind, ref, detail typés)
                 └─► continue
```

## Frontend

### `frontend/src/pages/ProjectDetailPage.tsx:193-211`

```tsx
{envVarsCheck.data && envVarsCheck.data.total_missing > 0 && (
  <div className="rounded-md border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm">
    <p className="font-medium text-destructive">
      {t("projects.env_vars_missing_banner", { count: envVarsCheck.data.total_missing })}
    </p>
    <ul className="mt-2 space-y-2">
      {envVarsCheck.data.items.map((item) => (
        <li key={item.group_script_id} className="text-xs">
          <div className="text-muted-foreground">
            <span className="font-mono">{item.script_name}</span>
            {" — "}
            <span>{item.group_name}</span>
          </div>
          <ul className="ml-4 mt-0.5 space-y-0.5">
            {item.missing.map((m) => (
              <li key={m.var_name} className="text-muted-foreground">
                <span className="font-mono">{m.var_name}</span>
                {" : "}
                <span>
                  {t(`projects.env_vars_reason.${m.kind}`, { detail: m.detail })}
                </span>
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ul>
  </div>
)}
```

### `frontend/src/i18n/{fr,en}.json`

Renommage : `env_vars_missing_banner` (le terme "manquante" devient "non résoluble" — couvre mieux `vault://` introuvable).

```json
"projects": {
  "env_vars_missing_banner": "{{count}} variable(s) d'environnement non résoluble(s) pour ce projet",
  "env_vars_reason": {
    "value_empty": "valeur vide",
    "var_not_in_env": "variable introuvable dans le .env : {{detail}}",
    "platform_secret_missing": "secret plateforme introuvable : {{detail}}",
    "machine_not_found": "machine inconnue : {{detail}}",
    "env_machine_var_not_found": "variable absente sur la machine : {{detail}}",
    "unknown_ref": "référence non reconnue : {{detail}}"
  }
}
```

Le hook `useEnvMachineVarCheck` reste inchangé : feedback immédiat dans le dialog d'édition, sans round-trip API. La bannière reste la source de vérité au moment du déploiement.

## Tests

### `backend/tests/test_input_resolver.py` (nouveau)

Couvre :
- Chaque syntaxe résoluble (4 cas) → valeur correcte
- Chaque kind de `UnresolvedPlaceholderError` (6 cas) → exception levée avec `kind`/`detail` exacts
- Valeur littérale → conservée
- Combinaisons : `${env-machine://X:VAR}` où la value sur X contient `${OTHER}` → valeur retournée brute (pas de récursion)
- `resolve_input_values_collect` → dict partiel + liste d'erreurs accumulées (vs fail-fast qui s'arrête au 1er)
- Ordre figé : si la même variable matche 2 patterns, c'est `env-machine://` qui gagne

### `backend/tests/test_placeholder_parsers.py` (nouveau)

Parsers purs, tests unitaires sans mocks ni DB.

### `backend/tests/test_check_project_env_vars.py` (mise à jour)

- Variable couverte par `${env-machine://X:VAR}` valide → **absente** de `missing` (le bug actuel)
- Variable couverte par `${vault://api:NAME}` → absente de `missing`
- Chaque `kind` de raison → `reason.kind` correct
- Script sans `via_env` → ignoré
- `target_kind=deployment_host` sans host assigné → group_script skip silencieux (comportement actuel préservé)

### `backend/tests/test_project_deployments.py` (mise à jour)

- Step échoue avec message explicite quand `${env-machine://...}` non résoluble
- Step réussit quand tout résout

### Frontend

`ProjectDetailPage.test.tsx` — snapshot de la bannière avec 2 items multi-reasons. L'i18n est testée ailleurs.

## Nettoyage de code mort

À la fin de l'implémentation, supprimer ce qui devient orphelin :

- **`backend/src/agflow/services/deployment_env_helpers.py`** : supprimer la fonction `resolve_input_value` (uniquement 2 callsites, tous migrés). Garder `ssh_kwargs_for_machine`, `substitute_script_placeholders`, `collect_env_from_script` (utilisés ailleurs).
- **Imports** dans `project_deployments.py:57-58` et `deployment_executor.py:19-25` : retirer `resolve_input_value` de la liste.
- **Tests** : supprimer/migrer les tests unitaires de `resolve_input_value` (s'ils existent isolément) — sinon le test du callsite couvre déjà.

À **conserver** (pas mort, utilisé ailleurs) :
- `platform_secrets_service.resolve_platform_refs` : 7 callsites (`agent_generator`, `compose_renderer_service`, `infra_env_vars_service.resolve_for_machine`, `project_deployments_service`). `input_resolver` l'**appellera** en interne pour les patterns `vault://` / `env://` — pas de duplication de regex.
- `platform_secrets_service.resolve_all` : producteur du `platform_secrets_map`, utilisé par tout le monde.

Vérification finale : `grep -r "resolve_input_value" backend/` doit retourner zéro hit après le chantier.

## Risques et points d'attention

- **`infra_env_vars_service.resolve_for_machine`** déjà existant : vérifier qu'il fait bien le rollup parent + résolution des refs `@platform_secret:…`. Pré-requis du resolver.
- **Performance du check** : N group_scripts × M machines distinctes référencées via `env-machine://`. À mesurer sur un projet avec beaucoup de scripts. Si > 500 ms, ajouter un cache `dict[machine_id, dict[str, str]]` au niveau du `check_project_env_vars` (mais pas dans `input_resolver` lui-même, qui doit rester sans état).
- **i18n** : la clé `env_vars_missing_banner` est renommée — vérifier qu'aucun autre composant ne la consomme avec l'ancien message.

## Périmètre / découpage

Un seul plan d'implémentation suffit. Ordre des tâches indicatif :
1. `placeholder_parsers.py` + tests purs
2. `input_resolver.py` (fail-fast) + tests
3. `input_resolver.resolve_input_values_collect` + tests
4. Migration des callsites `_run_group_script` et `execute_step` + tests
5. Refonte `check_project_env_vars` + tests
6. Mise à jour schéma API + frontend (bannière + i18n)
7. Smoke E2E (manuel) sur LXC fresh via `./scripts/run-test.sh`

## Références

- Bug discovery — conversation 2026-05-25 sur `ProjectDetailPage` (variable `KC_ADMIN_PASSWORD` du script `create-oidc-client`, groupe `primary`)
- Frontend resolver existant : `frontend/src/lib/missingVars.ts`, `frontend/src/hooks/useEnvMachineVarCheck.ts`
- Spec deploy wizard : `docs/superpowers/specs/2026-05-24-deploy-wizard.md` (résolveur impacte aussi `execute_step`)
