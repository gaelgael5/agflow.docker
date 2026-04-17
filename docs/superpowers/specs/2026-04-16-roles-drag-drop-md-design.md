# Drag-and-drop de fichiers `.md` dans les sections d'un Rôle — design

**Date** : 2026-04-16
**Module** : M2 — Rôles
**Scope** : Frontend uniquement (aucune migration DB, aucun nouvel endpoint)

## Contexte

La page `/roles` permet d'organiser un rôle en sections (natives `roles` / `missions` / `competences` + sections custom créables) ; chaque section contient des documents markdown éditables. Aujourd'hui, la création d'un document passe par un dialogue (`PromptDialog`) qui demande un nom puis ouvre l'éditeur vide.

Quand un opérateur a déjà ses documents markdown sur le disque (briefs, missions pré-rédigées, fiches de compétences), ce flux est pénible : il doit créer un doc vide, copier-coller le contenu, sauver. Pour plusieurs fichiers, c'est N×3 clics + N allers-retours.

**Objectif** : permettre de glisser-déposer un ou plusieurs fichiers `.md` depuis l'explorateur de l'OS directement sur la section cible dans la sidebar. Le contenu du fichier devient le `content_md` du nouveau document, le nom du fichier (sans extension, slugifié) devient son `name`.

## Décisions validées

| Dimension | Choix | Alternative rejetée |
|---|---|---|
| Intent | Drop de `.md` → création de documents (mono + batch multi-fichiers) | Stockage de blobs binaires (PDF/image) — demande une migration DB lourde |
| Zone de drop | Chaque section dans la sidebar, ciblage précis avec highlight individuel | Drop sur panneau droit (destination implicite, risque d'erreur) ; overlay plein écran (clic supplémentaire) |
| Extension | `.md` uniquement (case-insensitive) | `.md + .txt + autres textes` — les rôles sont définis en markdown, pas besoin d'élargir |
| Conflit de nom | Dialogue shadcn **Remplacer / Renommer auto / Annuler** + case « Appliquer à tous » | Écrasement silencieux (dangereux) ; skip silencieux (surprenant) ; renommage auto par défaut (bruit) |
| Feedback visuel | Bordure verte dashed + fond translucide sur section survolée + toast sonner en fin | Modal de progression par fichier (overkill pour batch typique) |
| Échec partiel | Batch continue, toast résumé final (`3 créés, 2 échoués — raison par fichier`) | Rollback transactionnel (coûteux) ; stop-and-keep (état incohérent) |
| Lib drag-drop | HTML5 DataTransfer natif (~30 lignes) | `react-dropzone` (dep superflue, pas d'autre usage dans le projet) |

## Architecture et composants

### Modifications

| Fichier | Nature | Responsabilité |
|---|---|---|
| `frontend/src/components/RoleSidebar.tsx` | modif | Câble un dropzone par section (state `dragOverSection: string \| null`) et propage `onFiles(section, FileList)` au parent |
| `frontend/src/pages/RolesPage.tsx` | modif | `handleDropFiles(section, files)` : validation, détection conflits, orchestration dialog, boucle mutations, toast final |
| `frontend/src/lib/rolesApi.ts` | aucune | `createDocument` et `updateDocument` existent déjà et suffisent |
| `frontend/src/i18n/fr.json`, `en.json` | modif | Nouvelles clés : labels dialog conflit, toasts, messages d'aide drag-over |

### Nouveaux fichiers

| Fichier | Rôle |
|---|---|
| `frontend/src/hooks/useSectionDropzone.ts` | Hook encapsulant les handlers HTML5 (`dragenter/leave/over/drop`), expose `{ dragOverProps, isDragOver }` |
| `frontend/src/components/DropConflictDialog.tsx` | Dialog shadcn — 3 boutons + checkbox « Appliquer à tous ». Contrôlé par `open`/`onClose`/`onResolve({action, applyToAll})` |
| `frontend/tests/hooks/useSectionDropzone.test.tsx` | Tests unitaires du hook |
| `frontend/tests/components/DropConflictDialog.test.tsx` | Tests unitaires du dialog |

### Aucune modification backend

Les endpoints existent déjà :
- `POST /admin/roles/{role_id}/documents` — crée un document (`{section, name, content_md}`)
- `PUT /admin/roles/{role_id}/documents/{doc_id}` — met à jour `content_md`
- Validation de slug du `name` déjà en place (`backend/src/agflow/api/admin/roles.py`)

## Data flow

### Flux nominal (sans conflit)

```
User drag N fichiers OS → sidebar section MISSIONS
  ↓ dragenter
RoleSidebar: dragOverSection = "missions" → highlight vert
  ↓ drop
RoleSidebar → onFiles("missions", FileList) → RolesPage
  ↓
handleDropFiles:
  1. Filtre extension .md + taille ≤ 1 Mo → rejets = toasts erreur individuels
  2. Lecture file.text() UTF-8 pour chaque fichier valide
  3. Slugify name = filename sans extension (accents supprimés, espaces→-, [^a-z0-9-] supprimés)
  4. Comparer aux documents existants de currentRole.sections.missions
  5. Pas de conflit → boucle séquentielle createDocument(role_id, {section, name, content_md})
  6. Chaque succès déclenche invalidateQueries (via useMutation existante)
  7. Toast final: "✓ N documents créés dans MISSIONS"
```

### Flux avec conflits

Si ≥1 nom entre en collision avec un document existant :

```
handleDropFiles détecte les conflits
  ↓
Ouvre DropConflictDialog avec la liste des fichiers en conflit
  ↓
Pour chaque conflit (ou global si "Appliquer à tous" coché) :
  - Remplacer   → updateDocument(existing.id, {content_md})
  - Renommer    → findFreeName(name) = name-2, name-3, ... → createDocument
  - Annuler     → skip, compté dans "échoués" du toast final
  ↓
Toast final récapitule (X créés, Y remplacés, Z annulés)
```

### Taille max et validation

- **Limite par fichier** : 1 Mo (choisi comme valeur raisonnable pour du markdown ; un doc > 1 Mo est probablement une erreur). Constante exportée depuis `frontend/src/lib/constants.ts` (à créer si absent).
- **Limite batch** : soft warning si `files.length > 20` → dialog de confirmation `"Importer N fichiers dans {section} ?"`. Pas de limite dure.
- **Encodage** : lecture via `file.text()` (UTF-8 par défaut du navigateur). Si le contenu contient `\uFFFD` (caractère de remplacement), on traite comme erreur d'encodage et toast individuel.

### Feedback sonner

| Situation | Toast |
|---|---|
| Tout OK | `✓ 3 documents créés dans MISSIONS` |
| Mixte | `3 créés, 2 remplacés, 1 échoué — a.pdf ignoré (extension)` |
| Tout échoué | `Aucun document créé` (après toasts d'erreur individuels) |
| Rejet extension (individuel, en plus du résumé) | `foo.pdf ignoré — seul .md accepté` |
| Rejet taille (individuel) | `big.md ignoré — > 1 Mo` |

## Error handling et edge cases

| Cas | Comportement |
|---|---|
| Fichier non-.md | Toast individuel, batch continue |
| Fichier > 1 Mo | Toast individuel, batch continue |
| Contenu non-UTF8 (caractère `\uFFFD` détecté) | Toast individuel, batch continue |
| Nom résultant vide après slugify | Toast individuel, batch continue |
| Rejet backend (4xx sur `createDocument`) | `detail` du 4xx affiché dans le toast individuel, batch continue |
| Erreur réseau (5xx ou timeout) | Toast `"{name} — échec réseau"`, batch continue |
| Aucun rôle sélectionné | Sidebar non rendue, pas de cas à gérer |
| Drop hors zone section | `preventDefault` global, aucun fichier créé |
| `Esc` pendant drag | Highlight retombe (comportement navigateur) |
| `Esc` dans le dialog de conflit | = Annuler ce fichier |
| `hasDirty` sur un autre document pendant le drop | Pas de perturbation ; édition en cours préservée |
| Multi-batch rapides consécutifs | Autorisés, séquentiels côté front ; React Query dédupe les invalidations |
| > 20 fichiers | Dialog de confirmation avant exécution |
| Section native (`roles`, `missions`, `competences`) | Accepte le drop — les sections natives peuvent contenir des documents (seule leur suppression est bloquée) |

### Hors scope (YAGNI explicite)

- Pas de retry automatique sur échec réseau (l'utilisateur peut re-drop)
- Pas de drag depuis un autre onglet navigateur (`image/uri-list`, `text/uri-list`)
- Pas de preview avant création
- Pas de compression ni chunking
- Pas de support `.zip` (l'import zip existant couvre déjà ce cas avec son propre flux)

## Testing

### Unitaires Vitest (front)

| Fichier | Scénarios clés |
|---|---|
| `tests/hooks/useSectionDropzone.test.tsx` | `isDragOver` vrai après `dragenter` / faux après `dragleave` ; `onFiles` appelé sur `drop` avec le bon FileList ; `preventDefault` sur `dragover` |
| `tests/components/RoleSidebar.test.tsx` | Bordure verte rendue uniquement sur la section survolée ; drop sur MISSIONS → `onFiles("missions", ...)` ; deux sections non highlightées en même temps |
| `tests/components/DropConflictDialog.test.tsx` | 3 boutons rendus avec i18n ; callbacks appelés avec le bon `{action}` ; checkbox "Appliquer à tous" propage `applyToAll=true` |
| `tests/pages/RolesPage.test.tsx` (ajouts) | Drop `.pdf` → pas d'appel createDocument ; drop `.md > 1 Mo` → pas d'appel ; drop 3 `.md` → 3 createDocument séquentiels, toast "3 créés" ; drop avec 1 conflit → dialog ouvert + choix "Remplacer" → updateDocument ; drop 2 conflits + "Appliquer à tous: Remplacer" → dialog ouvert une fois, 2 updateDocument ; échec réseau sur fichier 2/3 → toast "2 créés, 1 échec" |

### Backend

Aucun test à ajouter — les routes `POST/PUT /admin/roles/{role_id}/documents` sont déjà couvertes par `backend/tests/test_roles_service.py` et `test_admin_roles_endpoints.py`.

### E2E manuel sur LXC 201 (après deploy)

1. Drag 1 `.md` depuis Windows → section MISSIONS → doc créé + toast
2. Drag 3 `.md` simultanés sur COMPETENCES → 3 docs, toast `3 créés`
3. Drag un `.pdf` → toast erreur, rien créé
4. Drag un `.md` en conflit → dialog 3 boutons, tester chaque action
5. Drag 4 fichiers dont 2 conflits + « Appliquer à tous: Remplacer » → dialog 1 fois, 4 docs OK
6. F5 → persistance OK
7. Accessibilité clavier : `Esc` pendant drag, Tab dans le dialog

### Non-régression

Les tests existants `RolesPage.test.tsx` (CRUD roles, édition markdown, import/export zip) restent verts — aucun changement de contrat sur les routes existantes.

## Critères d'acceptation

- Drag d'un `.md` depuis l'OS sur une section crée un document avec le contenu attendu
- Multi-drop (N fichiers) produit N documents, ordre stable
- Conflit résolu par dialog avec les 3 actions, option « tous »
- Fichiers invalides rejetés avec toast explicite, batch continue
- Résumé final fiable (compteurs créés / remplacés / échoués / raisons)
- Aucune régression sur les flows existants (CRUD classique, import zip)
- Tests unitaires Vitest tous verts, `tsc --noEmit` et `ruff` OK
