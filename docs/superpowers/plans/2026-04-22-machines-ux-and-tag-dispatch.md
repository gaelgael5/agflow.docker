# Machines — UX dropdown actions, historique runs, dispatch par tag, certs rename/copy

## Context

Après la restructure infra (voir `2026-04-21-infra-restructure.md`), plusieurs améliorations d'usage sont apparues nécessaires sur la page `/admin/infra/machines` et sur les certificats. Elles partagent une logique : rendre la gestion plus ergonomique et découplée du mécanisme d'exécution.

Trois axes :
1. **Dropdown actions** — remplacer la liste de boutons par ligne (qui prenait toute la largeur quand il y avait 3-4 actions) par un menu déroulant unique.
2. **Historique des exécutions** — exposer via une icône 📜 un dialog listant les runs (tracés depuis `infra_machines_runs`) avec leur statut, durée, exit code.
3. **Dispatch post-exécution par tag** — remplacer le hardcodage `action_name == "create"` par un système de tags déclaratifs dans le manifest du script.

Plus deux correctifs sur les certificats :
4. **Rename** — le backend supportait déjà `PUT /api/infra/certificates/{id}` avec `{name}` mais la feature n'était pas exposée en UI.
5. **Copie clé publique toujours disponible** — avant, le bouton n'apparaissait que si `has_public_key` était à true. Maintenant le bouton est toujours là ; si la colonne `public_key` est NULL en BDD, elle est dérivée à la volée depuis la clé privée.

Aucune migration de schéma n'est nécessaire pour ces améliorations.

## Décisions d'architecture

| Sujet | Décision |
|-------|----------|
| Dropdown | Composant shadcn `DropdownMenu` (déjà installé), bouton unique « Actions ▾ » par ligne parent et par ligne enfant |
| Historique | Endpoint `GET /api/infra/machines/{id}/runs?limit=50` + hook `useInfraMachinesRuns` + dialog modal |
| Dispatch tag | Champ `tags: []` dans le manifest JSON fetché depuis l'URL de l'action. Après run réussi, chaque tag déclenche un handler dédié. |
| Handler `add_node` | Ancien `_auto_provision` renommé ; prend la variante enfant depuis `parent.named_type.sub_type_id` et provisionne une machine + certificat depuis la dernière ligne JSON de stdout |
| Dérivation clé publique | `cryptography.serialization.load_ssh_private_key` si `public_key` NULL en BDD, avec la passphrase déchiffrée |

## Dropdown actions

### Parent (machine VPS)

Avant : `parentButtonActions.map(a => <Button>…</Button>)` — N boutons.

Après :
```tsx
<DropdownMenu>
  <DropdownMenuTrigger><Button variant="outline">Actions ▾</Button></DropdownMenuTrigger>
  <DropdownMenuContent>
    {parentMenuActions.map(a => (
      <DropdownMenuItem
        className={actionColor(a.action_name)}
        onSelect={() => onScriptRun({ actionId: a.id, url: a.url, ... })}
      >
        {a.action_name}
      </DropdownMenuItem>
    ))}
  </DropdownMenuContent>
</DropdownMenu>
```

Couleurs : `create` → bleu, `destroy` → rouge, autres → neutre. Les actions sont filtrées pour exclure `install` (réservée aux enfants).

### Enfant (service)

Même pattern, mais toutes les actions de la variante enfant sont montrées. `install` → vert, `destroy` → rouge.

## Historique runs

### Backend

Endpoint déjà existant (`GET /api/infra/machines/{machine_id}/runs`) expose les lignes `infra_machines_runs` jointes avec `infra_named_type_actions` et `infra_category_actions` pour résoudre `action_name` lisible.

### Frontend

- Hook `useInfraMachinesRuns(machineId)` dans `hooks/useInfra.ts`
- Dialog `MachineRunsDialog` dans `InfraMachinesPage.tsx` :
  - Colonnes : action (badge), started_at, finished_at, résultat (badge ok/fail/en cours)
  - Icône 📜 (History) sur chaque ligne machine (parent + enfant)

## Dispatch par tag

### Manifest côté script

Avant, les scripts JSON contenaient :
```json
{ "args": [...], "command": "bash /tmp/... {LXC_ID}" }
```

Maintenant, on peut ajouter un champ `tags` :
```json
{
  "args": [...],
  "command": "...",
  "tags": ["add_node"]
}
```

### Backend — `api/infra/machines.py` `ws_exec`

```python
# 1. Récupérer les tags du manifest à la fetch
raw_tags = manifest.get("tags") or []
manifest_tags = [str(t) for t in raw_tags] if isinstance(raw_tags, list) else []

# 2. Après exit 0, dispatcher
if success and manifest_tags:
    output_json = _parse_last_json(stdout_lines)
    for tag in manifest_tags:
        await _handle_tag(tag, ws, conn, machine_id, output_json)
```

`_handle_tag` est un dispatcher simple :
```python
async def _handle_tag(tag, ws, conn, machine_id, output_json):
    if tag == "add_node":
        await _handle_add_node(ws, conn, machine_id, output_json)
    else:
        _log.info("tag.unknown", tag=tag)
```

`_handle_add_node` est l'ancien `_auto_provision` renommé : lit la clé SSH du parent (via `cat {ssh_key}`), crée le certificat SSH, puis crée la machine enfant avec `type_id = parent.named_type.sub_type_id` et `parent_id = parent_machine_id`.

### Sémantique préservée

- Le handler `install` (qui fait `status = initialized` + merge metadata) reste piloté par `action_name == "install"` pour l'instant. Migration future possible vers un tag `install_node` si besoin.

### Extensibilité

Ajouter un nouveau tag demande uniquement :
1. Écrire un handler `async def _handle_<tag>(...)`
2. Ajouter un `elif tag == "<nom>": await _handle_<tag>(...)` dans `_handle_tag`

## Certificats — rename et dérivation de clé publique

### Rename (UI)

- Le backend avait déjà `PUT /api/infra/certificates/{cert_id}` acceptant `CertificateUpdate` (dont `name: str | None`)
- Ajout frontend :
  - `infraCertificatesApi.rename(id, name)` dans `lib/infraApi.ts`
  - Bouton ✏️ (Edit2) sur chaque ligne
  - Dialog `RenameDialog` avec un seul champ Nom
  - Clés i18n `cert_rename`, `cert_rename_title`, `cert_renamed`

### Copie toujours disponible

- Les boutons Copy/Download 📋/⬇ sont retirés du `c.has_public_key && (...)` guard
- Toujours visibles sur chaque ligne
- Backend `get_public_key(cert_id)` dans `infra_certificates_service.py` :
  1. Si la colonne `public_key` est non-null → retourne directement
  2. Sinon : déchiffre `private_key` + `passphrase` via `crypto_service`, charge avec `serialization.load_ssh_private_key`, sérialise la clé publique OpenSSH
  3. Si la clé n'est pas décodable (format non-OpenSSH par exemple) → retourne None → 404 côté endpoint → toast d'erreur UI

## Fichiers touchés

### Backend
- `api/infra/machines.py` — `manifest_tags` capture + `_handle_tag` + `_handle_add_node` (renommage de `_auto_provision`)
- `services/infra_certificates_service.py` — `get_public_key` avec dérivation à la volée

### Frontend
- `pages/InfraMachinesPage.tsx` — DropdownMenu pour actions parent et enfant, MachineRunsDialog
- `pages/InfraCertificatesPage.tsx` — bouton Edit2 + RenameDialog, boutons Copy/Download sans guard
- `hooks/useInfra.ts` — useInfraMachinesRuns
- `lib/infraApi.ts` — `infraCertificatesApi.rename`
- `i18n/fr.json`, `i18n/en.json` — `actions_menu`, `cert_rename*`, `runs_*`, `runs_history`

## Vérification end-to-end

1. Sur `/admin/infra/machines`, vérifier que chaque ligne parent a un bouton « Actions ▾ » (si au moins une action sans `install` est configurée sur la variante)
2. Créer une action `create` dans la catégorie VPS (`/admin/infra/categories`)
3. Lier l'URL du script `create-lxc.json` (qui a `"tags": ["add_node"]`) à cette action sur la variante Proxmox
4. Lancer l'action `create` depuis le dropdown → après exit 0, la machine enfant LXC doit apparaître dans la liste
5. Cliquer 📜 sur la machine Proxmox → voir l'historique avec le run `create` terminé en succès
6. Sur `/admin/infra/certificates`, cliquer ✏️ → renommer → vérifier que la table se met à jour
7. Cliquer 📋 sur un certificat sans `has_public_key` → la clé publique dérivée doit être copiée dans le presse-papier
