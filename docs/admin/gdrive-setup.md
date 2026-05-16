# Connexion Google Drive — guide admin

Cette procédure prépare un projet Google Cloud pour permettre à agflow d'écrire des backups dans le Drive d'un compte Google.

## Pré-requis

- Compte Google avec accès à <https://console.cloud.google.com>
- Quota Drive disponible (15 GB gratuits, +/- 5 TB sur Google Workspace)

## Étapes

### 1. Créer un projet Google Cloud

1. <https://console.cloud.google.com/projectcreate>
2. Nom : `agflow-backups` (ou autre)
3. Créer

### 2. Activer l'API Google Drive

1. Menu burger → **APIs & Services** → **Library**
2. Chercher « Google Drive API » → **Enable**

### 3. Configurer l'OAuth consent screen

1. **APIs & Services** → **OAuth consent screen**
2. User type : **External** (sauf si Workspace Internal)
3. App name : `agflow`
4. User support email : ton email
5. **Save and continue**
6. Scopes → **Add or remove scopes** → cocher `.../auth/drive.file`
7. **Save and continue**
8. Test users : ajoute ton compte Google qui hébergera les backups
9. **Save**

### 4. Créer l'identifiant OAuth Web Client

1. **APIs & Services** → **Credentials** → **+ Create Credentials** → **OAuth client ID**
2. Application type : **Web application**
3. Name : `agflow-web`
4. **Authorized redirect URIs** : récupère l'URL exacte depuis le wizard agflow (champ « Redirect URI »). Format :
   ```
   https://<your-agflow-host>/api/admin/backup-remotes/oauth/gdrive/callback
   ```
5. **Create**
6. **Copie** le `Client ID` et le `Client secret`

### 5. Coller les credentials dans agflow

1. Dans agflow → **Backups** → **Connexions distantes** → **+ Nouvelle**
2. Kind : **Google Drive**
3. Nom logique : `Mon backup quotidien` (ou autre)
4. Client ID + Client Secret : ceux récupérés à l'étape 4
5. Nom du dossier Drive : `agflow-backups` (sera créé dans le Drive du compte autorisé)
6. Bouton **Autoriser dans Google Drive** → popup Google → connecte-toi → accorde l'accès
7. La popup se ferme automatiquement, la connexion apparaît dans le tableau

## Limitations connues

- **Pas de pagination de `list_remote`** au-delà de 1000 fichiers. Suffisant pour des backups quotidiens sur plusieurs mois ; si tu dépasses, change la politique de rétention.
- **Pas de sub-folders** dans le dossier cible. Tous les backups vivent à la racine du dossier.
- **Quota Drive** : 15 GB par compte Google gratuit. Si plein, l'upload plante avec une erreur claire.
- **Refresh token révoqué** : si l'utilisateur révoque l'accès depuis <https://myaccount.google.com/permissions>, la connexion ne fonctionne plus. Utilise le bouton **Re-autoriser** dans le tableau.

## Vérification

Dans le tableau des connexions, clique **Tester** sur la connexion gdrive. Si la réponse est verte, l'OAuth fonctionne et le dossier est accessible.
