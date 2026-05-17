# M6 Supervision — Phase 2a (UI)

**Date** : 2026-05-17
**Statut** : Design validé (en attente de plan d'implémentation)
**Branche cible** : `dev`

## Objectif

Brancher l'UI d'administration sur les endpoints `/api/admin/supervision/*` livrés en Phase 1 (2026-04-24, migration 083 + workers + hooks publisher/consumer) afin de permettre à l'admin :

- de **consulter en un coup d'œil** l'état agrégé de la plateforme (sessions, agents, containers, MOM delivery) ;
- de **lister les instances** d'agents avec filtres (status, recherche, inclusion des détruites) ;
- de **consulter le détail** d'une instance (mission, container, labels, MOM counts, 10 derniers messages, erreur éventuelle) ;
- de **partager un lien direct** vers le détail d'une instance via `?instance=<uuid>` dans l'URL.

La Phase 2a ne couvre **que le polling 5s**. Le push temps-réel via WebSocket est explicitement reporté en Phase 2b (cf. décision §1).

## Contexte

### Backend (déjà livré, aucune modification)

3 endpoints `require_admin` sous `/api/admin/supervision` :

| Endpoint | Réponse | Usage UI |
|---|---|---|
| `GET /overview` | `SupervisionOverview` (sessions, agents, containers_running\|null, mom) | KPI cards |
| `GET /instances?status=&limit=` | `list[SupervisedInstance]` | Table principale |
| `GET /instances/{id}` | `InstanceDetail` (+ container_status live aiodocker, recent_messages 10) | Drawer détail |

Schémas Pydantic dans `backend/src/agflow/schemas/supervision.py` (5 classes : `SessionStatusCounts`, `AgentStatusCounts`, `MomDeliveryCounts`, `SupervisionOverview`, `SupervisedInstance`, `InstanceDetail`).

Le filtre `status` accepte `idle|busy|error` (alive only) ; `destroyed_at IS NOT NULL` est exclu par défaut côté service `agents_instances_service.list_all_for_supervision` (pas de paramètre `include_destroyed` exposé — à confirmer pendant l'implémentation, sinon ajout d'un query param).

### Frontend (actuellement)

- Entrée sidebar `/supervision` **présente mais `disabled: true`** (`frontend/src/components/layout/Sidebar.tsx:116`).
- i18n : seul `sidebar.supervision = "Supervision"` existe.
- Aucun `supervisionApi.ts`, aucun `useSupervision.ts`, aucune `SupervisionPage.tsx`.
- Pattern de référence : `SessionsPage.tsx` (PageShell + useQuery + refetchInterval 5_000 + Skeleton).

## Décisions structurantes (tranchées en brainstorming)

| # | Question | Décision | Rationale |
|---|---|---|---|
| 1 | Refresh temps-réel | **Polling 5s** (Phase 2a). WS push reporté Phase 2b. | Aucun WS supervision global n'existe en backend (seul `/api/v1/sessions/{sid}/agents/{iid}/stream` existe, dédié aux messages MOM). Ajouter un pub/sub + endpoint WS supervision ajouterait ~1.5-2j. Latence max 5s est acceptable pour de la supervision. |
| 2 | Affichage du détail | **Drawer latéral** avec URL state `?instance=<uuid>` | Reste dans le flux liste, permet lien partageable, fluide vs modal centré, plus léger qu'une route dédiée. |
| 3 | Layout des KPI | **4 cards en ligne** (1 par catégorie : Sessions, Agents, Containers, MOM) | Lisible, extensible, chaque catégorie reste atomique. |
| 4 | Filtres table | **Status (select) + recherche texte (input) + toggle "Inclure détruites"** | Couvre les 3 axes d'usage : trier par sévérité (status), trouver une instance (recherche), inspecter l'historique (destroyed). |
| 5 | Actions (kill/restart) | **Hors scope Phase 2a** | Endpoints d'action inexistants en backend. Sera Phase 2c si besoin avéré. |
| 6 | Tri de la table | **`last_activity_at DESC` côté client** | Pertinent pour voir d'abord ce qui bouge. API renvoie déjà la liste, tri in-memory suffit. |
| 7 | Recherche texte | **Filtrage côté client (in-memory)** sur le résultat API | <200 instances en pratique, pas besoin d'aller-retour serveur. Status reste un query param serveur. |
| 8 | Etat URL pour les filtres | **Pas en URL** (état local React) | Filtres jetables, pas besoin de partager une vue filtrée. Seul le drawer (`?instance=`) est dans l'URL. |

## Architecture frontend

### Arborescence des fichiers

```
frontend/src/
├── lib/
│   └── supervisionApi.ts                                 ~90 lignes
├── hooks/
│   └── useSupervision.ts                                 ~60 lignes
├── pages/
│   └── SupervisionPage.tsx                              ~130 lignes
└── components/supervision/
    ├── SupervisionKpiCards.tsx                          ~150 lignes
    ├── SupervisionFilters.tsx                            ~70 lignes
    ├── SupervisionInstancesTable.tsx                    ~180 lignes
    └── SupervisionInstanceDrawer.tsx                    ~200 lignes
```

+ 3 modifications de fichiers existants :

| Fichier | Modification |
|---|---|
| `frontend/src/App.tsx` | Ajout `<Route path="/supervision" element={<SupervisionPage />} />` |
| `frontend/src/components/layout/Sidebar.tsx:116` | Retrait de `disabled: true` |
| `frontend/src/i18n/{fr,en}.json` | Bloc `supervision.*` (~35 clés × 2 langues) |

### Découpage des composants

**`SupervisionPage.tsx`** — assembleur, lit `?instance=<id>` via `useSearchParams`, monte les 4 sous-composants, gère l'ouverture/fermeture du drawer.

**`SupervisionKpiCards.tsx`** — reçoit `overview: SupervisionOverview | undefined`, affiche 4 cards (Sessions / Agents / Containers / MOM). Skeleton si undefined. `containers_running === null` → affiche "—" + tooltip "Indisponible".

**`SupervisionFilters.tsx`** — composant contrôlé, props : `value: Filters`, `onChange: (next: Filters) => void`. Filters = `{ status: 'all'|'idle'|'busy'|'error', search: string, includeDestroyed: boolean }`.

**`SupervisionInstancesTable.tsx`** — reçoit `instances: SupervisedInstance[]`, `filters: Filters`, `onSelect: (id: string) => void`. Applique le filtre texte + sort `last_activity_at DESC`. Empty state, loading skeleton, error alert avec retry.

**`SupervisionInstanceDrawer.tsx`** — reçoit `instanceId: string | null`, `onClose: () => void`. Query enabled si `!!instanceId`. Composant `Sheet` shadcn (à confirmer présence ; sinon ajout via `npx shadcn-ui@latest add sheet`).

## Data flow (TanStack Query)

| Query key | Endpoint | refetchInterval | enabled |
|---|---|---|---|
| `['supervision', 'overview']` | `GET /overview` | 5_000 | `true` |
| `['supervision', 'instances', { status, includeDestroyed }]` | `GET /instances?status=&include_destroyed=` | 5_000 | `true` |
| `['supervision', 'instance', id]` | `GET /instances/{id}` | 5_000 | `!!id` |

Recherche texte = `useMemo` côté client sur le résultat de `['supervision','instances',...]`.

Bouton refresh manuel = `queryClient.invalidateQueries({ queryKey: ['supervision'] })`.

## Loading / Empty / Error states

| Composant | Loading | Empty | Error |
|---|---|---|---|
| KPI Cards | 4 `<Skeleton className="h-32" />` | n/a (toujours des chiffres, 0 si vide) | Petit badge `?` + tooltip "Indisponible" sur la card concernée (`containers_running === null`) |
| Table | 5 lignes `<Skeleton className="h-10" />` | Texte centré : "Aucune instance active. Lance une session pour voir des agents apparaître." | `<Alert variant="destructive">` + bouton "Réessayer" → `query.refetch()` |
| Drawer | Skeletons par section (mission/container/labels/mom/messages) | n/a | 404 → fermer drawer + toast "Instance introuvable" ; autre erreur → Alert dans le drawer |

**Comportements transverses :**

- Polling pendant erreur : retry default TanStack Query (3×), pas de toast à chaque échec.
- Instance détruite pendant ouverture du drawer : l'objet renvoyé a `destroyed_at` rempli, bullet status "destroyed" en gris. Pas de fermeture auto.
- 401/403 : interceptor existant dans `lib/api.ts` redirige vers `/login`.

## A11y

- Table : `<th scope="col">` natif + `aria-sort` sur la colonne triée.
- Drawer (`Sheet`) : focus trap natif shadcn + `aria-labelledby` sur le header + `Esc` ferme.
- KPI Cards : chiffre dans `<span aria-label="3 sessions actives">`.
- Bullets status : couleur **et** label texte ("busy", "idle"…) pour les lecteurs d'écran.
- Bouton refresh : `aria-label={t('supervision.refresh')}`.
- Skeletons : `<div role="status" aria-live="polite" aria-busy="true">`.

## i18n (bloc `supervision.*`, ~35 clés)

```text
supervision: {
  page_title, subtitle, refresh,
  kpi: {
    sessions: { title, active, closed, expired },
    agents: { title, idle, busy, error, destroyed },
    containers: { title, running, unavailable },
    mom: { title, pending, claimed, failed }
  },
  filters: {
    status: { label, all, idle, busy, error },
    search_placeholder, include_destroyed
  },
  table: {
    col: { status, mission, agent, session, last_activity },
    empty, error, retry, no_mission
  },
  drawer: {
    section: { mission, container, labels, mom, messages, error },
    container_status: { running, exited, none },
    not_found, close
  },
  status: { idle, busy, error, destroyed }
}
```

À traduire FR + EN dans `frontend/src/i18n/{fr,en}.json`.

## Tests (Vitest, pas d'E2E local)

| Fichier | Tests | Volume |
|---|---|---|
| `lib/__tests__/supervisionApi.test.ts` | Parsing Zod (overview/instance/detail), construction query params (status, include_destroyed) | 4 |
| `components/supervision/__tests__/SupervisionKpiCards.test.tsx` | Affichage des 4 cards, couleurs selon seuils (`failed>0` → destructive ; `error>0` → destructive ; `busy>0` → primary), `containers_running === null` → "—" | 4 |
| `components/supervision/__tests__/SupervisionInstancesTable.test.tsx` | Filtre recherche texte, tri par `last_activity_at`, toggle destroyed, clic ligne déclenche `onSelect(row.id)`, état vide | 6 |
| `components/supervision/__tests__/SupervisionInstanceDrawer.test.tsx` | Rendu détail, fallback labels `{}` si manquant, fermeture via `[×]`, recent_messages liste | 4 |
| `pages/__tests__/SupervisionPage.test.tsx` | Intégration : `?instance=<id>` ouvre le drawer, fermeture nettoie le searchParam | 2 |

Total : ~20 tests Vitest.

Pas de tests backend ajoutés (les 3 endpoints sont couverts par les tests existants de la Phase 1).

Validation E2E réelle = `./scripts/run-test.sh` après merge dev (LXC fresh + pytest + 8 assertions smoke).

## Backend : ajustement éventuel

Le service `agents_instances_service.list_all_for_supervision(status, limit)` n'expose pas (à vérifier pendant l'implémentation) de paramètre `include_destroyed`. La requête actuelle filtre probablement `destroyed_at IS NULL` par défaut.

**Si pas exposé** → ajout d'un query param `include_destroyed: bool = False` à `GET /instances` + adaptation du service. Coût : ~1-2h backend + 1 test pytest.

**Si déjà exposé sous un autre nom** → adapter le frontend au nom réel.

À trancher au début de l'implémentation, pas en spec (dépend d'un détail à lire dans le code).

## Volume et estimation

| Catégorie | Lignes |
|---|---|
| Code frontend (5 fichiers nouveaux) | ~830 |
| i18n FR + EN | ~140 |
| Tests Vitest | ~400 |
| Modifications fichiers existants | ~10 |
| Spec (ce doc) | ~250 |
| **Total** | **~1630 lignes** |

**Effort estimé** : 3-4 jours en mode pipeline allégé (subagent seul, pas de spec-reviewer intermédiaire).

## Hors scope explicite (Phase 2a)

- WebSocket push temps-réel → **Phase 2b**.
- Actions kill/restart sur une instance → **Phase 2c** (nécessite endpoints backend).
- Graphes de tendances (charges, deltas) → **Phase 2d**.
- Filtre par session_id ou agent_id → ajout simple plus tard si besoin.
- Pagination de la table → limit 200 codé en dur, à revoir si gêne en prod.
- Stream live des messages d'une instance dans le drawer → un onglet drawer plus tard si besoin (l'endpoint MOM stream existe déjà).
