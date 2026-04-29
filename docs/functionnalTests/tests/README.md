# Tests fonctionnels exécutables (curl)

> **📋 Cartouche — Index du répertoire**
>
> **Rôle** : point d'entrée pour la campagne de tests fonctionnels.
> **Contenu** : 12 fichiers de tests exécutables + 1 doc de référence + 1 helper bash sourceable.
> **Lecture** : commencer par `00-test-data.md` (données + conventions),
> puis suivre l'ordre d'exécution recommandé ci-dessous.
> **Prérequis machine** : `curl`, `jq`, `wscat` (cf. section dédiée).

Ce répertoire contient la **traduction exécutable** des 12 scénarios de
`docs/functionnalTests/` (9 applicatifs + 3 opérateur) sous forme de scripts curl.
Chaque fichier `.md` décrit un test isolé : préconditions, étapes, assertions,
nettoyage.

## Organisation

| Fichier | Type | Décrit le scénario |
|---------|------|--------------------|
| `00-test-data.md` | Référence | Variables, fixtures, valeurs attendues partagées par tous les tests |
| `01-single-agent-request.md` | Test applicatif | Cas 01 |
| `02-parallel-agents.md` | Test applicatif | Cas 02 |
| `03-inter-agent-communication.md` | Test applicatif | Cas 03 |
| `04-project-resources-and-mcp.md` | Test applicatif | Cas 04 |
| `05-streaming-live-results.md` | Test applicatif | Cas 05 |
| `06-long-running-session-extension.md` | Test applicatif | Cas 06 |
| `07-discovery-before-instantiation.md` | Test applicatif | Cas 07 |
| `08-one-shot-task-no-session.md` | Test applicatif | Cas 08 |
| `09-post-mortem-logs-and-files.md` | Test applicatif | Cas 09 |
| `A01-platform-bootstrap.md` | Test opérateur | Scénario A01 |
| `A02-mcp-integration.md` | Test opérateur | Scénario A02 |
| `A03-project-setup.md` | Test opérateur | Scénario A03 |

## Ordre d'exécution recommandé

Sur un environnement vierge :

1. **A01** → bootstrape la plateforme et émet `API_KEY`
2. **A02** (optionnel, requis pour 04) → installe et binde le MCP
3. **A03** (optionnel, requis pour 04) → crée le projet de fixtures
4. **07** → discovery (le moins invasif)
5. **01** → premier vrai cycle session+agent
6. **02, 03, 05, 06** → variantes
7. **08** → one-shot indépendant
8. **04** → projet + MCP (a besoin de A02 et A03)
9. **09** → post-mortem, idéalement juste après 01

## Pré-requis machine

- `curl` ≥ 7.70
- `jq` ≥ 1.6
- `wscat` (pour 05 et 09 streaming) — `npm install -g wscat`
- `bash` ≥ 4 (les boucles et arrays utilisent la syntaxe bash)

## Pré-requis environnement

Voir `00-test-data.md` section 1. À minima :

```bash
export BASE_URL="https://docker-agflow-staging.yoops.org"
export WS_URL="${BASE_URL/https:/wss:}"
export API_KEY="agflow_..."        # fourni par A01 ou par l'opérateur
```

## Convention "FAIL fast"

Chaque test renvoie un exit code 0 (succès) ou 1 (échec) en fin de fichier. Une
assertion qui échoue affiche un message `FAIL: <description>` puis stoppe l'exécution.

Les tests sont **indépendants** (sauf 09 qui dépend d'une session précédente). On
peut donc les exécuter dans n'importe quel ordre, à condition que le bootstrap A01
soit fait au préalable.

## Limites volontaires (V1)

- Pas de chemin d'erreur (session expirée, scope manquant, etc.) — itération future.
- Pas de test de charge.
- Pas d'orchestration parallèle entre tests (chacun s'exécute séquentiellement).
- Les WebSockets sont validés par `wscat` en tâche de fond avec timeout — pas
  d'assertion stricte sur l'ordre des frames.

## Exécution rapide d'un test isolé

Chaque fichier est conçu pour être exécutable directement par copier-coller dans un
shell, ou en mode batch :

```bash
# extrait tous les blocs bash du fichier et les exécute
sed -n '/^```bash/,/^```/p' 01-single-agent-request.md \
  | grep -v '^```' \
  | bash -e
```

> Cette extraction est indicative ; la commande supporte tous les tests de ce
> répertoire qui suivent la convention "un seul bloc bash exécutable par
> section + nettoyage final".
