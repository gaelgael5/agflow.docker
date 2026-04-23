# agflow-logs — Stack centralisée Loki + Grafana

Stack de centralisation des logs Docker + journald du homelab. À déployer sur **LXC 116** (`agflow-logs`, IP attribuée par DHCP).

## Architecture

- **Loki** (`:3100`) — stockage des logs, rétention 7 jours, BoltDB shipper local. Exposé sur le LAN pour recevoir les pushes des Alloy distants.
- **Grafana** (`:3000` interne, exposé via Caddy `:80`) — UI de consultation, auth OIDC Keycloak (realm `yoops`, client `grafana`). Datasource Loki provisionnée automatiquement, 2 dashboards par défaut (Docker, Systemd).
- **Alloy** (local au LXC 116) — collecteur des logs Docker locaux + journald, push vers Loki.
- **Caddy** — reverse proxy `:80` → `grafana:3000`. TLS terminé par Cloudflare Tunnel en amont.

## Prérequis

- LXC 116 créé via `scripts/infra/00-create-lxc.sh 116 agflow-logs` (privileged, Docker installé).
- Client OIDC `grafana` créé dans Keycloak realm `yoops` :
  - Type confidentiel
  - Redirect URI : `https://log.yoops.org/login/generic_oauth`
  - Web origin : `https://log.yoops.org`
  - 3 client roles : `admin`, `editor`, `viewer` (assignés aux users autorisés)
  - Récupérer le client secret dans Credentials > Secret

## Déploiement

```bash
# 1. Copier l'arborescence infra/ sur le LXC 116
scp -r infra/ lxc116:/opt/agflow-logs/

# 2. Créer .env à partir du template et renseigner les secrets
ssh lxc116 "cd /opt/agflow-logs/logs-stack && cp .env.template .env && nano .env"
# → renseigner GRAFANA_ADMIN_PASSWORD et KEYCLOAK_GRAFANA_CLIENT_SECRET

# 3. Démarrer la stack
ssh lxc116 "cd /opt/agflow-logs/logs-stack && docker compose up -d"

# 4. Vérifier
ssh lxc116 "docker compose ps && curl -s http://localhost:3100/ready && curl -s http://localhost:3000/api/health"
```

## Étapes d'exposition publique

1. **DNS Cloudflare** : créer un CNAME `log.yoops.org` → `<tunnel-id>.cfargotunnel.com` (même tunnel que les autres `*.yoops.org`).
2. **Cloudflared (LXC 112)** : ajouter une ingress rule dans `/etc/cloudflared/config.yml` :
   ```yaml
   - hostname: log.yoops.org
     service: http://<IP_LXC116>:80
   ```
   Puis `systemctl reload cloudflared`.
3. Ouvrir `https://log.yoops.org` → redirect Keycloak → login → Grafana.

## Déployer Alloy sur les autres LXC

Une fois Loki accessible, déployer le collecteur Alloy sur chaque LXC du homelab :

```bash
# Depuis le poste local (Windows)
LOKI_URL="http://<IP_LXC116>:3100/loki/api/v1/push" ./scripts/infra/deploy-alloy-all.sh
```

Le script boucle sur tous les LXC actifs, copie `infra/alloy-agent/` et lance `02-install-alloy.sh` à l'intérieur.

## Références

- Loki config : <https://grafana.com/docs/loki/latest/configure/>
- Grafana OIDC : <https://grafana.com/docs/grafana/latest/setup-grafana/configure-security/configure-authentication/generic-oauth/>
- Alloy `loki.source.docker` : <https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.docker/>
- Alloy `loki.source.journal` : <https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.journal/>
