# Mission : Templates Jinja2

## Déclencheur
L'utilisateur veut créer, modifier ou comprendre un template Jinja2 utilisé pour la génération de prompts ou de missions.

## Objectif
Guider l'écriture de templates Jinja2 fonctionnels dans le contexte agflow.

## Concept
Les templates Jinja2 contrôlent le rendu des fichiers générés. Il y a deux types :
- **Templates de prompt** (agent-prompt/) : génèrent le `prompt.md` principal de l'agent
- **Templates de missions** (roles/) : génèrent les fichiers de missions dans le workspace

## Accès
Page **Templates** dans le menu latéral. L'éditeur intégré supporte la coloration syntaxique Jinja2 + Markdown.

## Variables disponibles

### Template de prompt (agent-prompt/*.j2)
| Variable | Type | Description |
|----------|------|-------------|
| `role` | objet | Rôle de l'agent (display_name, identity_md) |
| `agent` | objet | Agent complet (slug, display_name, description) |
| `missions` | liste | Profils de missions générés (name, description, path) |
| `api_contracts` | liste | Contrats API attachés (slug, description, ref_dir, tags) |
| `ref_prefix` | string | Préfixe de référence (@workspace) |
| `paths` | dict | Chemins configurés (prompt, roles, missions, contracts, skills) |
| `load_section` | fonction | Charge une section du rôle (roles/, missions/, competences/) |

### Template de mission (roles/*.j2)
| Variable | Type | Description |
|----------|------|-------------|
| `profile` | objet | Profil de mission (name, description) |
| `documents` | liste | Documents sélectionnés (display_name, content) |
| `role` | objet | Rôle parent |

## Syntaxe Jinja2

### Variables
```
{{ variable }}
{{ objet.propriete }}
{{ liste[0].champ }}
```

### Blocs conditionnels
```
{% if missions %}
## Missions
{% for m in missions %}
- {{ m.description }} : `{{ m.path }}`
{% endfor %}
{% endif %}
```

### Fonction load_section
Charge tous les fichiers d'une section du rôle :
```
{% for doc in load_section("competences") %}
{{ doc.content }}
{% endfor %}
```

### Filtres utiles
```
{{ texte | upper }}
{{ liste | length }}
{{ valeur | default("fallback") }}
```

## Configuration du moteur
agflow utilise ces réglages Jinja2 :
- `trim_blocks=True` : supprime le retour à la ligne après un bloc `{% %}`
- `lstrip_blocks=True` : supprime les espaces avant un bloc `{% %}`
- `keep_trailing_newline=True` : préserve le retour à la ligne final
- `autoescape=False` : pas d'échappement HTML (le rendu est du Markdown)

Ces réglages signifient que les blocs `{% %}` ne génèrent pas de lignes vides parasites.

## Exemple complet — template de prompt
```
# {{ role.display_name }}

{{ role.identity_md }}
{% if missions %}

### Missions
{% for m in missions %}
- {{ m.description }} : `{{ m.path }}`
{% endfor %}
{% endif %}
{% if api_contracts %}

## API disponibles
{% for contract in api_contracts %}

### {{ contract.description }}
{% for tag in contract.tags %}
- {{ tag.description }} : `{{ ref_prefix }}/{{ contract.ref_dir }}/{{ contract.slug }}/{{ tag.slug }}.md`
{% endfor %}
{% endfor %}
{% endif %}
```

## Erreurs fréquentes
- **Ligne vide en trop** : ajouter un `-` dans le tag (`{%- if ... %}`) pour supprimer le whitespace
- **Variable undefined** : vérifier le nom exact dans le tableau des variables disponibles
- **load_section ne retourne rien** : la section n'existe pas dans le rôle ou est vide
- **Le rendu est échappé** : autoescape est désactivé, mais si le template est utilisé dans un autre contexte, vérifier

## Critère de succès
Le template génère un fichier Markdown propre, sans lignes vides parasites, avec toutes les sections conditionnelles qui s'affichent correctement.
