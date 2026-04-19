# Module Templates Jinja2 — design

**Date** : 2026-04-17
**Module** : Nouveau module "Templates" entre Dockerfiles et Rôles
**Scope** : Backend CRUD filesystem + Frontend page + éditeur CodeMirror

## Contexte

La plateforme a besoin de templates Jinja2 pour générer les fichiers agent (prompt.md, run.sh, config…). Les templates sont multilingues : un fichier `.j2` par culture, la culture étant déduite du nom de fichier.

Ce lot couvre le **module CRUD standalone** — pas l'intégration dans la génération agent (lot suivant).

## Stockage disque

```
/app/data/templates/
  agent-prompt/
    template.json          ← { "display_name": "...", "description": "..." }
    fr.md.j2               ← variante française
    en.md.j2               ← variante anglaise
  mcp-config/
    template.json
    fr.toml.j2
    en.toml.j2
```

**template.json** — métadonnées communes, pas de champ culture :
```json
{
  "display_name": "Prompt Agent",
  "description": "Template Jinja2 pour générer le prompt système"
}
```

Les cultures disponibles se déduisent des fichiers `*.j2` présents sur disque. Convention de nommage : `{culture}.{ext}.j2` (ex: `fr.md.j2`, `en.toml.j2`). La culture est le premier segment avant le premier point.

## Backend

### Dépendance

`jinja2` ajouté dans `pyproject.toml` (sera utilisé par la génération dans le lot suivant, mais installé dès maintenant).

### Service filesystem

`backend/src/agflow/services/template_files_service.py` — même pattern que `role_files_service.py` :
- `list_all()` → scan `data/templates/*/template.json`
- `get(slug)` → lit template.json + liste les .j2
- `create(slug, display_name, description)` → crée le répertoire + template.json
- `update(slug, display_name, description)` → met à jour template.json
- `delete(slug)` → shutil.rmtree
- `list_files(slug)` → liste les .j2 avec culture déduite
- `read_file(slug, filename)` → contenu du .j2
- `write_file(slug, filename, content)` → écrit le .j2
- `delete_file(slug, filename)` → supprime le .j2

### API REST

`backend/src/agflow/api/admin/templates.py` — routeur sous `/api/admin/templates` :

| Méthode | Route | Action |
|---|---|---|
| GET | `/` | Liste tous les templates |
| POST | `/` | Créer un template (slug + display_name + description) |
| GET | `/{slug}` | Détail : métadonnées + liste fichiers .j2 avec culture |
| PUT | `/{slug}` | Modifier métadonnées |
| DELETE | `/{slug}` | Supprimer le template et son répertoire |
| POST | `/{slug}/files` | Ajouter un fichier .j2 (filename + content) |
| PUT | `/{slug}/files/{filename}` | Modifier le contenu d'un .j2 |
| DELETE | `/{slug}/files/{filename}` | Supprimer un .j2 |

### Schémas Pydantic

```python
class TemplateCreate(BaseModel):
    slug: str
    display_name: str
    description: str = ""

class TemplateUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None

class TemplateSummary(BaseModel):
    slug: str
    display_name: str
    description: str
    cultures: list[str]  # déduit des fichiers .j2

class TemplateFileInfo(BaseModel):
    filename: str
    culture: str
    size: int

class TemplateDetail(BaseModel):
    slug: str
    display_name: str
    description: str
    files: list[TemplateFileInfo]

class FileCreate(BaseModel):
    filename: str
    content: str = ""

class FileUpdate(BaseModel):
    content: str
```

## Frontend

### Route et navigation

- Route `/templates` dans `App.tsx`
- Entrée "Templates" dans `Sidebar.tsx` entre Dockerfiles et Rôles
- Clés i18n `templates.*` FR/EN

### Page `TemplatesPage.tsx`

Layout identique à DockerfilesPage :
- **Gauche** : liste des templates (display_name, description, badges cultures)
- **Droite** : quand un template est sélectionné, liste ses fichiers .j2. Clic sur un fichier → éditeur
- **Actions header** : créer template, ajouter fichier .j2, supprimer
- **Sauvegarde** : Ctrl+S ou bouton Save

### Éditeur `JinjaEditor.tsx`

Nouveau composant basé sur CodeMirror :
- Dépendances npm : `codemirror`, `@codemirror/view`, `@codemirror/state`, `@codemirror/lang-html`, `@codemirror/theme-one-dark`
- Coloration : Jinja (`{{ }}`, `{% %}`, `{# #}`) via le mode HTML (les délimiteurs Jinja sont reconnus par le parser HTML)
- Props : `value: string`, `onChange: (value: string) => void`, `readOnly?: boolean`
- Thème dark cohérent avec le reste de l'app

### API client

`frontend/src/lib/templatesApi.ts` — fonctions CRUD
`frontend/src/hooks/useTemplates.ts` — hook TanStack Query

## Hors scope (lot suivant)

- Intégration dans `agent_generator.py` (champ `template_id` sur l'agent, rendu Jinja au moment de la génération)
- Preview du rendu template dans l'UI
- Autocomplétion des variables Jinja dans l'éditeur

## Vérification

1. Créer un template "agent-prompt" avec display_name et description
2. Ajouter `fr.md.j2` avec du contenu Jinja (`{{ role.display_name }}`, `{% for doc in documents %}`)
3. Ajouter `en.md.j2`
4. Vérifier que les cultures apparaissent en badges
5. Éditer un fichier .j2 → coloration syntaxique visible
6. Sauvegarder → contenu persisté sur disque
7. Supprimer un fichier → disparu
8. Supprimer le template → répertoire supprimé
