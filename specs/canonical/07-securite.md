# 07 — Sécurité

La sécurité de agflow.docker repose sur quatre principes :
1. **Auth UI distincte de l'auth API** : Keycloak OIDC pour les utilisateurs interactifs, clés API natives pour les clients externes.
2. **Tous les secrets dans Harpocrate** : la base ne stocke que des références.
3. **Signatures HMAC sur tous les hooks sortants** : aucun destinataire ne fait confiance à un payload non signé.
4. **TLS partout sur l'externe** : Cloudflare Tunnel + certificats valides pour tout endpoint exposé.

## Authentification UI

### Mode primaire : Keycloak OIDC

L'authentification primaire de l'interface administrateur passe par **Keycloak** (instance hébergée sur `security.yoops.org`, realm `yoops`). agflow.docker se comporte comme un **client OIDC** :

1. L'utilisateur clique « Se connecter » → `GET /api/admin/auth/oidc/login` → redirection vers la page de login Keycloak.
2. L'utilisateur s'authentifie chez Keycloak (mot de passe, MFA, etc.).
3. Keycloak redirige vers `GET /api/admin/auth/oidc/callback?code=…&state=…`.
4. agflow.docker échange le code contre un access token, lit le profil utilisateur (email, name, scopes), trouve ou crée la ligne `users` correspondante, génère un **JWT local** signé par agflow.docker, le renvoie au frontend.
5. Le frontend stocke le JWT et le réutilise dans `Authorization: Bearer <jwt>` pour tous les appels admin.

### Configuration

Endpoints :
- `GET /api/admin/auth-config` : retourne la config actuelle (sans le secret).
- `PUT /api/admin/auth-config` : met à jour. Le `keycloak_client_secret` fourni en clair est poussé dans Harpocrate et seul le ref est stocké en DB.
- `POST /api/admin/auth-config/test` : teste la connexion Keycloak (toujours HTTP 200, succès/échec dans `ok`).

### Fallback : admin local

En cas d'indisponibilité de Keycloak (réseau, maintenance), un **admin local** créé à l'installation reste disponible via :
- `POST /api/admin/auth/login` avec `{email, password}` → retourne un JWT local.

Le mot de passe est stocké en bcrypt en base. L'admin local porte le rôle `admin` et peut tout faire ; il est réservé aux situations exceptionnelles.

### Mode `local` exclusif

Pour les déploiements sans Keycloak (par exemple environnements de dev isolés), `auth_config.mode = 'local'` désactive complètement Keycloak. Tous les comptes vivent en base, créés via M7 (UsersPage). Cette configuration est explicite et nécessite que l'opérateur ajoute manuellement chaque utilisateur.

### Google OAuth

Endpoints `GET /api/admin/auth/google` et `GET /api/admin/auth/google/callback` permettent une authentification via Google pour les utilisateurs qui ne sont pas dans Keycloak (cas particulier : tester la plateforme avec un compte Google sans avoir configuré Keycloak). À utiliser avec parcimonie ; pour la production, Keycloak reste le mode primaire.

### Sessions JWT

Le JWT émis par agflow.docker (qu'il vienne du callback Keycloak ou du login local) :
- Est signé avec une clé privée stockée dans Harpocrate (ref `${vault://api:agflow_jwt_signing_key}`).
- Contient `sub` (user_id), `email`, `role`, `scopes`, `exp` (configurable, par défaut 12h).
- Est validé à chaque requête via `Depends(require_admin)` ou `Depends(require_operator)` selon les routes.

## Authentification API publique

L'API publique (`/api/v1/*`) est consommée par des clients externes (ag.flow, scripts intégrateurs, agents one-shot). Elle utilise des **clés API natives** générées et gérées par agflow.docker, **indépendantes** de Keycloak.

### Format

Chaque clé est de la forme `agfd_<prefix>_<secret>` où :
- `agfd_` : préfixe identifiant la plateforme (visible en clair).
- `<prefix>` : 8 caractères alphanumériques, visibles en clair (pour identifier la clé sans révéler le secret).
- `<secret>` : 32 caractères alphanumériques, le secret réel.

Le hash bcrypt + HMAC du secret est stocké en base. **La valeur en clair n'est exposée qu'au moment de la création** (`POST /api/admin/api-keys` → `ApiKeyCreated.full_key`). Après, seul le `prefix` est consultable.

### Vérification

À chaque requête :
1. Le backend extrait l'en-tête `Authorization: Bearer agfd_<prefix>_<secret>`.
2. Trouve la ligne `api_keys` par `prefix`.
3. Vérifie que la clé n'est pas révoquée ni expirée.
4. Compare le hash du secret avec `key_hash` (constant-time comparison).
5. Si match : authentification OK, mise à jour de `last_used_at`.

### Scopes

Chaque clé porte une liste de **scopes** qui contrôlent ce qu'elle peut faire :
- `sessions:read`, `sessions:write` — lire ou créer des sessions.
- `agents:read`, `agents:write` — lister ou instancier des agents.
- `messages:read`, `messages:write` — lire ou envoyer des messages.
- `projects:read`, `runtimes:write` — lire des projets ou créer des runtimes.
- `*` — wildcard admin (réservé aux clés d'administration).

Les scopes disponibles sont listés via `GET /api/v1/scopes`.

### Rate limiting

Chaque clé a une `rate_limit` (requêtes par minute, défaut 120). Le backend incrémente un compteur Redis (ou table `rate_limit_counters` en fallback) par clé + fenêtre temporelle. Dépassement → `429 Too Many Requests`.

### Rotation et révocation

- Les clés ont une `expires_at` optionnelle (durées prédéfinies : 3m, 6m, 9m, 12m, never).
- Rotation : créer une nouvelle clé, mettre à jour les clients, révoquer l'ancienne.
- Révocation : `DELETE /api/admin/api-keys/{id}` → la clé est immédiatement inutilisable.

## Gestion des secrets

### Architecture

```
┌───────────────────────────────────────────────────┐
│  agflow.docker (backend)                           │
│                                                     │
│  ┌──────────────────┐    ┌─────────────────────┐ │
│  │ harpocrate_dek   │───>│ harpocrate_vaults   │ │
│  │ (clé locale)     │    │ (api_key chiffrée)  │ │
│  └──────────────────┘    └──────────┬──────────┘ │
│                                      │ déchiffre   │
│                                      ▼            │
│                          ┌─────────────────────┐  │
│                          │ vault_client        │  │
│                          │ (SDK Harpocrate)    │  │
│                          └──────────┬──────────┘  │
└─────────────────────────────────────┼─────────────┘
                                      │ HTTPS
                                      ▼
                       ┌────────────────────────────┐
                       │ Harpocrate (service externe)│
                       │ — end-to-end encrypted vault│
                       └────────────────────────────┘
```

### Stockage

Toutes les valeurs sensibles (clés API providers IA, mots de passe machines, tokens Swarm, secrets HMAC, clés privées SSH, secrets Keycloak, etc.) sont stockés **uniquement dans Harpocrate**. La base de données ne contient que :
- Des **références canoniques** : `${vault://api:NAME}` ou des refs custom.
- Des **alias** (le nom court par lequel on accède à la valeur, ex: `auth_config.keycloak_client_secret_ref`).

### Multi-coffres

L'administrateur peut déclarer plusieurs `harpocrate_vaults`. L'un porte le flag `is_default` et reçoit les nouveaux secrets sauf override. Cela permet de séparer secrets prod / dev, ou de migrer d'un coffre à un autre.

### Lecture

Toute lecture d'un secret passe par `vault_client.get_secret(ref)` qui :
1. Identifie le coffre cible (par défaut : default vault).
2. Déchiffre localement l'`api_key` du coffre via `harpocrate_dek`.
3. Fait l'appel HTTPS à Harpocrate avec cette clé.
4. Retourne la valeur en clair (en mémoire, pas persistée).

### Le chicken-and-egg : `harpocrate_dek`

La clé qui ouvre Harpocrate ne peut pas elle-même être dans Harpocrate. C'est la seule exception à la règle « tout dans le coffre ».

`harpocrate_dek` est :
- Stockée en base dans une table singleton dédiée.
- Chiffrée par une variable d'environnement `AGFLOW_LOCAL_KEY` fournie au démarrage du process (typiquement un secret monté depuis Docker secrets ou Kubernetes secrets côté infrastructure).
- Sans `AGFLOW_LOCAL_KEY`, le backend ne peut pas déchiffrer `harpocrate_dek`, donc ne peut pas lire `harpocrate_vaults.api_key`, donc ne peut accéder à aucun secret.

C'est volontaire : un dump de la base seul ne permet pas de remonter aux secrets.

### Résolveur de placeholders

Tout texte rendu par la plateforme (script, compose, env, prompt, MCP config) qui contient une référence est passé au **résolveur unifié** (`input_resolver`). Voir détails dans le module 06.

### Tests de connexion

- `POST /api/admin/harpocrate-vaults/{id}/test-connection` : vérifie que l'API key permet de lire un secret de test.
- `POST /api/admin/secrets/vault` (lors de la création) : vérifie que la clé peut écrire avant de confirmer.
- `POST /api/admin/restore/vault/test` : test de bas niveau d'un couple URL+key (utilisé par le wizard de restore).

## Signatures HMAC sur les hooks

### Pourquoi

Quand agflow.docker envoie un événement à un destinataire externe (typiquement un workflow ag.flow notifiant la fin d'une task), le destinataire doit pouvoir vérifier que :
- Le hook vient bien d'agflow.docker (pas d'un usurpateur).
- Le contenu n'a pas été altéré en transit.

### Mécanisme

Chaque hook sortant porte trois headers en plus du payload JSON :
- `X-Agflow-Hmac-Key-Id: <key_id>` : identifie la clé partagée utilisée.
- `X-Agflow-Signature: <hex>` : signature `HMAC-SHA256(secret, body_bytes)`.
- `X-Agflow-Event: <event_type>` : type d'événement (`task.completed`, etc.).

### Clés HMAC (`hmac_keys`)

Une clé HMAC est créée via `POST /api/admin/hmac-keys` avec :
- `key_id` : identifiant court alphanumérique (ex: `wf-prod-2026-05`).
- `secret_hex` : un secret hexadécimal de 32 à 128 caractères (générer côté client avec `os.urandom`).
- `description` : libellé humain.

Le secret est immédiatement haché et le hash stocké en base. Le secret en clair est aussi poussé dans Harpocrate sous le ref `${vault://api:hmac_keys/{key_id}}` pour la signature.

### Rotation

`DELETE /api/admin/hmac-keys/{key_id}` n'efface pas la clé : elle passe en statut `rotated`. Les hooks signés avec cette clé restent vérifiables pour l'audit historique, mais aucun nouveau hook n'utilisera cette clé.

Pour rotater :
1. Créer une nouvelle clé avec un nouveau `key_id`.
2. Mettre à jour les sessions / clients pour qu'ils utilisent la nouvelle clé.
3. Soft-delete l'ancienne après validation.

### Idempotence côté destinataire

Le destinataire doit accepter de recevoir le même hook plusieurs fois (retries du dispatcher) et le traiter idempotemment, typiquement en utilisant `(task_id, event)` comme clé d'unicité.

## TLS et exposition externe

### Cloudflare Tunnel

Tous les endpoints exposés à l'extérieur (UI, API publique, hooks sortants) passent par **Cloudflare Tunnel** :
- Le tunnel termine TLS chez Cloudflare avec un certificat valide.
- Pas de port ouvert sur internet côté infrastructure.
- Le tunnel est routé vers le backend agflow.docker en HTTP local (uniquement accessible via le tunnel).

### Certificats SSH machines

Pour les connexions SSH vers les machines cibles, agflow.docker utilise :
- **Soit** un mot de passe stocké dans Harpocrate (acceptable, non recommandé en production).
- **Soit** un certificat SSH (RSA 4096 ou Ed25519). La clé privée vit dans Harpocrate, la clé publique est consultable via `GET /api/infra/certificates/{id}/public-key` pour l'ajouter au `authorized_keys` côté machine.

### Génération de certificats

`POST /api/infra/certificates/generate` génère une paire de clés directement dans le backend (la clé privée part dans Harpocrate sans jamais être exposée par l'API). L'opérateur récupère ensuite la clé publique pour la déployer.

## Audit et traçabilité

### Logs structurés

Tous les événements sensibles (login, création de clé API, modification de coffre, lancement de déploiement, exécution de script, etc.) génèrent un event structlog JSON avec :
- `event` : nom canonique (ex: `auth.login.success`, `api_key.created`).
- `level` : `info` ou `warning` ou `error`.
- `user_id`, `email` (quand applicable).
- `resource_id`, `resource_type` (quand applicable).
- Pas de valeurs sensibles (mots de passe, secrets, tokens).

Ces logs sont collectés par Alloy et indexés dans Loki. Voir module 11.

### `last_used_at` et `last_login`

- `api_keys.last_used_at` : mis à jour à chaque utilisation. Permet de repérer les clés inactives.
- `users.last_login` : mis à jour à chaque login. Permet de repérer les comptes dormants.

### Approbation et désactivation

Un utilisateur créé par auto-discovery Keycloak est en statut `pending` jusqu'à approbation par un admin (`POST /api/admin/users/{id}/approve`). Cela évite qu'un utilisateur Keycloak random puisse se connecter dès qu'il existe dans le realm.

`POST /api/admin/users/{id}/disable` désactive instantanément. Le JWT déjà émis reste valide jusqu'à son `exp` ; pour révocation immédiate, il faut soit attendre l'expiration soit invalider via la blacklist Redis (TODO infrastructure si besoin de révocation immédiate).

## Threat model en bref

| Menace | Mitigation |
|---|---|
| Vol de la DB | Tous les secrets sont dans Harpocrate ; `harpocrate_dek` est chiffré par `AGFLOW_LOCAL_KEY` injectée au runtime |
| Vol de `AGFLOW_LOCAL_KEY` seule | Permet de déchiffrer `harpocrate_dek`, mais ne donne pas accès à Harpocrate sans la base (les `api_key_ref` y sont) |
| Vol simultané DB + AGFLOW_LOCAL_KEY | Permet de lire les clés API Harpocrate. Mitigé par : auth additionnelle Harpocrate, ACLs côté Harpocrate, rotation régulière |
| Compromission d'une clé API native (`agfd_`) | Révocation immédiate via UI. Rate limit limite l'usage abusif en attendant la détection. Scopes limitent l'impact |
| Hook spoofé | Signature HMAC obligatoire ; un hook non signé ou mal signé est rejeté par le destinataire |
| Man-in-the-middle | TLS partout via Cloudflare Tunnel + certificats valides |
| Injection dans un script de déploiement | Les `input_values` sont résolus puis substitués mais **pas évalués shell** ; Jinja en sandbox bloque l'exécution de Python arbitraire ; `shlex.quote` utilisé pour les valeurs passées en arguments shell |
| Élévation de privilège via création d'utilisateur Keycloak | Utilisateurs auto-créés sont en statut `pending` jusqu'à approbation manuelle par un admin |
