# 12 — Conventions de développement

Cette section fixe les conventions de code, de workflow Git et de tests qui s'appliquent à tout contributeur d'agflow.docker (humain ou IA). Elles sont opposables : tout changement qui ne les respecte pas doit être corrigé avant merge.

## Standard général

**Code propre, jamais quick-and-dirty.** La règle est absolue : si une tâche ne peut pas être faite proprement dans le temps imparti, on découpe et on livre proprement la partie faisable. On alerte sur le reste plutôt que de produire un compromis dégradé.

Refus explicite des « TODO, on corrigera plus tard », « pour aller plus vite », « on simplifiera après ». Trois lignes similaires valent mieux qu'une abstraction prématurée.

## Branche unique

**Toute contribution se fait sur la branche `dev`.** Pas de `feat/*`, pas de branche perso, pas de commit direct sur `main`. Avant toute édition de code, vérifier `git branch --show-current` ; si autre branche, `git checkout dev`. Si `dev` n'existe pas localement, la créer depuis `main` à jour.

Cette règle s'applique aux humains comme aux IA d'assistance. Les workflows superpowers qui suggèrent de créer des branches `feat/*` sont overridés par cette consigne.

## Commits

### Format

Commits en français, conventionnels :
- `feat:` nouvelle fonctionnalité
- `fix:` correction de bug
- `chore:` tâche de maintenance, refactor, dépendances
- `docs:` documentation
- `test:` tests
- `refactor:` réorganisation sans changement de comportement
- `style:` formatage, espaces

Un commit = un changement cohérent. Si un changement touche plusieurs domaines, on split en plusieurs commits.

### Hooks

Les hooks pre-commit / pre-push (lint, format, tests rapides) doivent passer. **Jamais de `--no-verify` ni `--no-gpg-sign`.** Si un hook bloque, on corrige l'underlying issue.

### Pas de commit/push sans demande explicite

Une IA d'assistance ne commit jamais sans qu'un humain le demande explicitement. La règle est claire : la suggestion « voici les changements proposés » n'inclut pas l'action de commit.

## Backend Python

### Stack figée

- Python 3.12+, `async/await` partout.
- FastAPI + Pydantic v2 + asyncpg (**jamais SQLAlchemy**).
- `structlog` pour les logs, **jamais `print()`**.
- `ruff` pour lint + format (configuration dans `pyproject.toml`).
- `pytest` + `pytest-asyncio` pour les tests.

### Style

- `from __future__ import annotations` en tête de fichier.
- Type hints partout.
- Fichiers **max 300 lignes**. Quand un fichier dépasse, le split par responsabilité.
- Classes SRP, méthodes 5-15 lignes.
- Pas d'emoji dans le code ni dans les commits sauf si l'utilisateur le demande explicitement.

### SQL

asyncpg direct via helpers `agflow.db.pool` :

```python
from agflow.db.pool import fetch_one, fetch_all, execute, transaction

row = await fetch_one("SELECT * FROM agents WHERE id = $1", agent_id)
rows = await fetch_all("SELECT * FROM agents WHERE role_id = $1", role_id)
await execute("UPDATE agents SET status = $1 WHERE id = $2", "active", agent_id)

async with transaction() as conn:
    await conn.execute(...)
    await conn.execute(...)
```

Pas d'ORM, pas de repository pattern, pas de query builder. Le SQL est explicite et reviewable.

### Erreurs et exceptions

- Pas de `try / except: pass`. Toujours typer l'exception attendue.
- Pas de fallback silencieux : si un secret manque, on échoue avec un message précis (fail-fast).
- Exceptions métier typées (héritant d'une `AgflowError` racine si applicable au domaine), réutilisées dans les handlers FastAPI.

### Tests

Conformes au document `docs/tests-python.md`. Couverture par zone :
- Agents/tools : 80% min.
- Services métier : 75% min.
- Routes API : 60% min.
- Code neuf : couverture +90% (delta).
- Obligatoire : tout module commençant par `db_`, `file_`, `resolve_` doit avoir des tests.

TDD : test rouge → impl → test vert → commit.

### Lint

```bash
cd backend && uv run ruff check src/ tests/
cd backend && uv run ruff format src/ tests/
```

Le format de ruff est l'unique source de vérité pour la mise en forme (pas de discussion d'espacement / virgules / etc.). Pas d'override `# noqa` sans justification commentée.

## Frontend TypeScript

### Stack figée

- Vite + React 18 + TypeScript `strict: true` + `noUncheckedIndexedAccess: true`.
- TanStack Query pour toute donnée serveur (**jamais `useEffect + fetch` direct**).
- Tailwind CSS + shadcn/ui.
- i18next pour toute chaîne affichée (`useTranslation()`, **jamais de string brute**).
- Vitest + React Testing Library pour les tests.

### Style

- Composants fonctionnels + hooks. Pas de classes.
- Fichiers **max 300 lignes**.
- Props typées via `interface`, exports nommés.
- Pas d'emoji sauf demande explicite.
- Les noms de variables et fonctions en anglais, les chaînes user-facing via i18n.

### i18n

Toute chaîne destinée à l'utilisateur doit passer par i18next :

```tsx
// ✅
const { t } = useTranslation();
return <Button>{t("projects.deploy")}</Button>;

// ❌
return <Button>Déployer</Button>;
```

Les clés sont organisées par module (`projects.*`, `agents.*`, `infra.*`, …) dans `frontend/src/i18n/fr.json` et `en.json` qui doivent rester synchronisés (mêmes clés, valeurs traduites).

### Tests

```bash
cd frontend && npm test -- --run
cd frontend && npx tsc --noEmit
cd frontend && npm run lint
```

Conventions de tests :
- `describe` / `it` (jamais `test`).
- Co-localisés à côté du composant (`Foo.tsx` + `Foo.test.tsx`).
- Pour les pages complexes, extraire des sous-composants testables en isolation plutôt que de tout mocker.

### Composants UX particuliers

- **`StatusIndicator`** : composant frontend qui rend les badges 🔴 🟠 🟢 partout où on affiche le statut d'une variable d'environnement. Utiliser systématiquement pour les statuts secrets.
- **`TerminalWindow`** : composant unifié pour tous les terminals SSH dans l'UI (basé sur xterm.js + asyncssh côté backend).
- **`DeployWizardDialog`** : utilisé pour tout déploiement de project_runtime.
- **Dialogs Radix** : ajouter `data-[state=inactive]:hidden` sur les TabsContent qui doivent vraiment se cacher (sinon `display:flex` override `hidden` HTML).
- **Inputs natifs interdits** : `window.prompt` / `window.confirm` / `window.alert` ne sont jamais utilisés. Toujours un `<Dialog>` shadcn.

## Base de données

### Migrations

- Schéma versionné dans `backend/migrations/`.
- Fichier unique consolidé `001_init.sql` qui crée l'état complet à partir d'une base vide.
- Migrations additionnelles numérotées (`002_*.sql`, `003_*.sql`, etc.) appliquées en ordre par le runner.
- Toute nouvelle table → migration SQL + tests.

### Extensions requises

- `pgcrypto` (chiffrement, hash).
- `uuid-ossp` (génération UUID).

### Conventions

- PK = UUID v4 (`uuid_generate_v4()` ou générées côté backend).
- Timestamps `TIMESTAMPTZ` avec trigger `set_updated_at()`.
- Pas de soft-delete générique. Les soft-deletes sont nominaux (ex: `hmac_keys.status='rotated'`) avec colonnes dédiées.
- Index sur toutes les FK + sur les colonnes filtrées fréquemment.
- Contraintes nommées (`<table>_<colonne>_check`) pour pouvoir les modifier sans avoir à deviner leur nom auto-généré.

## Workflow IA

Quand une IA d'assistance (Claude Code, Codex, Aider, etc.) travaille sur le projet, elle suit les contraintes ci-dessous.

### Cycle architecte

**Cadrer → Comprendre → Planifier → Agir.** L'utilisateur est l'architecte ; une question n'est pas un feu vert pour l'exécution, une discussion n'est pas un GO. L'IA ne saute pas d'étape.

Pour les chantiers non triviaux (>3 fichiers ou >100 lignes), elle suit la chaîne :
1. Brainstorming (skill superpowers).
2. Spec dans `docs/superpowers/specs/<date>-<topic>-design.md`.
3. Plan dans `docs/superpowers/plans/<date>-<topic>.md` (tâches TDD bite-sized).
4. Exécution tâche par tâche avec review entre chaque (typiquement subagent-driven-development).

### Vérification avant validation

Avant de déclarer une tâche terminée :
1. Le code s'exécute sans erreur (lint + build).
2. Le cas nominal fonctionne (test unitaire ou manuel).
3. Les imports ajoutés existent réellement.
4. Pas de régression sur les fichiers modifiés.
5. Si modification frontend : la page charge sans erreur console.

### Pas de livraison sans demande explicite

L'IA ne commit pas, ne push pas, ne crée pas de PR sans qu'on le lui demande explicitement. La règle s'applique aussi aux modifications `.env` (jamais sans demande).

### Auto-amélioration

Quand l'IA fait une erreur ou qu'elle est corrigée :
- Elle ajoute une leçon dans `LESSONS.md`.
- Format : `- [module] description courte de l'erreur et de la bonne pratique`.
- Elle relit `LESSONS.md` en début de tâche qui touche un module mentionné.
- Le fichier ne dépasse pas 50 lignes — consolider les leçons similaires.

## Tests d'intégration et machines

### Environnements de test

- **LXC 400-499** : tests automatisés par IA (Claude). Provisionnés via `./scripts/run-test.sh`. Éphémères.
- **LXC 300-399** : tests humains. Provisionnés via `remote-deploy.ps1 <id>`. Persistants.
- **LXC 201** : environnement d'intégration de référence (`agflow-docker-test`, `192.168.10.158`). **Ne pas déployer dessus directement** ; passer par `run-test.sh` ou `remote-deploy.ps1`.
- **LXC 116** : stack logs centralisée (`agflow-logs`). Ne pas modifier sauf chantier dédié.

### Pas de stack locale Windows

Le poste de dev Windows n'a **pas** d'app qui tourne (pas de Docker desktop avec la stack agflow, pas de Postgres local). Les tests d'intégration DB tournent uniquement sur LXC 400-499 via `run-test.sh`. En local on lance pytest pour les tests purs.

### Validation E2E

Après tout chantier non trivial qui touche le backend ou le déploiement, l'opérateur final lance `./scripts/run-test.sh` pour valider sur LXC fresh. Sans cette validation, le chantier n'est pas considéré comme livré.

## Outils Claude Code

### Context7 — documentation live

À utiliser **avant d'écrire du code** qui consomme FastAPI, Pydantic v2, asyncpg, aiodocker, redis-py, asyncssh, React Query, Vite, React Router, i18next, Tailwind, etc. Les APIs évoluent ; ne pas se fier à la mémoire d'entraînement.

### Serena — navigation sémantique

À utiliser **avant un refactor**, pour comprendre les dépendances entre modules ou trouver tous les usages d'une fonction.

### Skills Superpowers

- `writing-plans` : rédiger un plan d'implémentation TDD avant de coder.
- `executing-plans` ou `subagent-driven-development` : exécuter un plan tâche par tâche.
- `systematic-debugging` : méthode pour debug un bug ou test qui échoue.
- `test-driven-development` : discipline TDD rigoureuse.
- `brainstorming` : explorer le design avant d'écrire quoi que ce soit.
- `verification-before-completion` : vérifier que le travail est réellement fini avant de le dire.

### Reviewers

- `/review` ou skill `pr-review-toolkit:code-reviewer` avant de présenter un changement multi-fichiers (>3 fichiers ou >100 lignes).
- `/commit` ou skill `commit-commands:commit` quand l'utilisateur demande explicitement de committer.

## Communication entre humains et IA

### Tonalité

Les réponses de l'IA sont **courtes, concises, factuelles**. Pas de remplissage, pas de récap de ce qui vient d'être dit, pas de « excellent ! voilà ce qui a été fait ». Une fin de tâche fait 1-2 phrases : ce qui a changé, ce qui reste.

### Style français

Le projet est en français. Les commits, commentaires d'utilisateur, messages d'erreur destinés à l'utilisateur, documentation, sont en français. Les noms de variables et fonctions sont en anglais. Les accents et diacritiques (`é`, `è`, `à`, `ù`, etc.) sont obligatoires — pas de substitution ASCII.

### Demande de confirmation

Pour les actions à blast radius élevé (push, force-push, deletion DB, modification CI, message externe, etc.), l'IA confirme avant d'agir. La confirmation se fait par texte (pas une nouvelle question si l'utilisateur a déjà dit oui).

### Pas de skill mention sans invocation

L'IA ne mentionne pas une skill (« j'utilise la skill X ») sans réellement l'invoquer via le tool `Skill`. Ne pas inventer des skills inexistantes ou se contenter de citer leur titre.

## Mémoire persistante

L'IA dispose d'une mémoire file-based à `C:\Users\g.beard\.claude\projects\E--srcs-agflow-docker\memory\`. Elle y stocke :
- **user** : profil de l'utilisateur, préférences, expertise.
- **feedback** : corrections récurrentes (« ne fais pas X »).
- **project** : contexte projet (chantiers en cours, échéances, décisions).
- **reference** : pointeurs vers des ressources externes.

L'index `MEMORY.md` liste les fichiers. Toute nouvelle leçon va dans la mémoire, **pas dans cette spec** : la spec décrit le système, la mémoire suit l'humain.
