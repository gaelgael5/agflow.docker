# Mission : Paramétrage complet d'un agent

## Déclencheur
L'utilisateur veut configurer un agent existant ou comprendre les options de paramétrage.

## Objectif
Guider la configuration technique complète d'un agent dans la page Agents.

## Onglet Général

### Identité
- **Slug** : identifiant unique (lowercase, tirets). Non modifiable après création.
- **Nom d'affichage** : nom visible dans l'interface
- **Description** : description courte de l'agent

### Dockerfile
- Sélectionner le Dockerfile qui détermine l'image Docker (et donc le CLI agent : claude-code, mistral, aider...)
- L'indicateur coloré montre l'état de l'image : vert = prête, rouge = non buildée ou supprimée
- Le Dockerfile détermine les variables d'environnement requises (secrets)

### Rôle
- Sélectionner le rôle qui définit la personnalité de l'agent
- Le rôle fournit : identité, rôles de personnalité, missions, compétences

### Variables d'environnement
- Liste héritée du Dockerfile.json (section Environments)
- Chaque variable peut être overridée ou exclue au niveau agent
- Les secrets sont référencés par `${VAR_NAME}` et résolus à la génération

### Mounts
- Volumes Docker hérités du Dockerfile.json
- Le workspace (`/app/workspace`) est le répertoire de travail de l'agent
- Peuvent être overridés ou exclus au niveau agent

## Onglet Services MCP

### Ajouter un serveur MCP
- Ouvrir la modale de recherche
- Chercher par nom (/name), tag (/tag), groupe (/group), pseudo (/pseudo) ou sémantique (@terme)
- Cliquer Ajouter — le serveur apparaît dans la liste

### Configurer un serveur MCP
- Runtime : choisir npx, docker, uvx selon le serveur
- Paramètres : variables spécifiques au serveur (ex: chemin de workspace)
- Les serveurs déjà ajoutés sont marqués « Ajouté » dans la modale

## Onglet Skills
- Même principe que les MCP : recherche + ajout depuis le catalogue
- Les skills sont des packs de bonnes pratiques injectés dans le prompt

## Profils de missions

### Concept
Un profil = une sélection de documents du rôle + un template de rendu. Chaque profil génère un fichier .md dans le workspace de l'agent.

### Configuration d'un profil
- **Nom** : identifiant du profil (ex: "Onboarding", "Diagnostic")
- **Description** : courte description de la mission
- **Documents** : cocher les documents du rôle à inclure (missions/, competences/, roles/)
- **Template** : slug du template Jinja2 à utiliser pour le rendu
- **Culture** : langue du template (fr, en)
- **Répertoire de sortie** : chemin relatif dans le workspace (défaut: workspace/missions)

### Résultat
Chaque profil génère un fichier `{slug}.md` dans le répertoire de sortie, référencé dans le prompt via `@workspace/missions/{slug}.md`.

## Contrats API
- Onglet dédié pour attacher des specs OpenAPI à l'agent
- Chaque contrat génère des fiches .md et des scripts .sh dans le workspace
- Voir la mission dédiée "Composition & génération" pour les détails

## Prompt template
- **Slug** : template Jinja2 utilisé pour générer le prompt.md principal
- **Culture** : langue du template
- Le template reçoit : role, missions, api_contracts, ref_prefix, paths

## Flag Assistant
- Cocher "Utiliser comme assistant" pour que cet agent soit le chat intégré en haut à droite de l'interface
- Un seul agent peut être assistant à la fois

## Génération
- Bouton RefreshCw : génère tous les fichiers (prompt.md, .env, run.sh, mcp.json, workspace/)
- Les fichiers générés sont visibles dans l'explorateur en bas de page
- Après modification du paramétrage, toujours régénérer avant de tester

## Points de vigilance
- Un secret rouge = l'agent ne démarrera pas → configurer le secret d'abord
- Modifier le Dockerfile change les variables requises → vérifier les secrets
- Les profils de missions sans documents sélectionnés génèrent un fichier vide
- Le prompt template doit exister dans les Templates Jinja2 avant d'être référencé
