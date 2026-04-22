# Prompt-template — Générer un script de provisioning agflow

> **Mode d'emploi (humain).** Ce fichier n'est pas exécutable. C'est un prompt
> à donner tel quel à un LLM (Claude, ChatGPT, Copilot…) après avoir
> remplacé les `{{VARIABLES}}` ci-dessous. Le LLM doit produire **un seul
> fichier** : un script shell de provisioning conforme aux conventions
> agflow.
>
> **Variables à substituer avant envoi** :
>
> | Variable | Exemple VMware | Exemple AWS | Exemple Hyper-V |
> |---|---|---|---|
> | `{{TECHNO_NAME}}` | `VMware vSphere` | `AWS EC2` | `Hyper-V` |
> | `{{CLI_TOOL}}` | `govc` | `aws` (CLI v2) | `pwsh` + module `Hyper-V` |
> | `{{INSTANCE_NOUN}}` | `VM` | `EC2 instance` | `VM` |
> | `{{INSTANCE_ID_FIELD}}` | `vm_moid` | `instance_id` | `vm_id` |
> | `{{HOST_OS}}` | `bash` | `bash` | `pwsh` |
> | `{{TARGET_OS_DEFAULT}}` | `Ubuntu 24.04` | `Ubuntu 24.04 LTS AMI` | `Ubuntu 24.04` |
> | `{{SCRIPT_FILENAME}}` | `create-vmware.sh` | `create-ec2.sh` | `create-hyperv.ps1` |

---

## 1. Mission

Tu es un ingénieur DevOps senior. Tu dois écrire **un seul fichier**
`{{SCRIPT_FILENAME}}` qui provisionne un {{INSTANCE_NOUN}} sur
**{{TECHNO_NAME}}** prêt à exécuter Docker, intégré à la plateforme
**agflow.docker**.

Le script doit être **autonome** (pas de Terraform, pas de Packer, pas
d'Ansible — juste {{HOST_OS}} + {{CLI_TOOL}}) et **idempotent** (re-exécutable
sans casse).

Il doit reproduire fidèlement le comportement et les conventions du script
de référence Proxmox fourni en section 2 ci-dessous, en remplaçant
uniquement les appels Proxmox-spécifiques par leurs équivalents
{{TECHNO_NAME}}.

---

## 2. Référence canonique — `scripts/proxmox/create-lxc.sh`

C'est l'implémentation Proxmox/LXC qui sert de modèle. Lis-la intégralement
avant d'écrire quoi que ce soit. Tu dois reproduire **les patterns**, pas le
contenu littéral.

```bash
#!/bin/bash
###############################################################################
# Script 00 : Creation / Configuration LXC Proxmox pour Docker
#
# A executer sur l'HOTE PROXMOX (pas dans le container).
#
# Deux modes automatiques :
#   - Si le container N'EXISTE PAS  -> creation + configuration Docker
#   - Si le container EXISTE DEJA   -> reconfiguration Docker (avec backup)
#
# Resout :
#   - AppArmor "permission denied"
#   - Network unreachable (pas de DHCP)
#   - Docker sysctl errors
#   - Nesting / cgroup permissions
#   - UID/GID remapping (unprivileged -> privileged)
#
# Inclut :
#   - Generation de clefs SSH (sauvegardees sur l'hote)
#   - Configuration openssh-server dans le container
#   - Installation Docker via 01-install-docker.sh (si present dans le meme dossier)
#
# Usage : ./00-create-lxc.sh <CTID> [hostname]
# Exemple : ./00-create-lxc.sh 200 agflow-docker-test
#
# Pre-requis (creation uniquement) : un template Ubuntu dans le storage local.
#   pveam update
#   pveam download local ubuntu-24.04-standard_24.04-2_amd64.tar.zst
###############################################################################
set -euo pipefail

# ── Configuration par defaut ─────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CTID="${1:-}"
# Sanitize hostname: replace underscores/dots with hyphens, lowercase, strip invalid chars
CT_NAME_RAW="${2:-agflow-docker}"
CT_NAME=$(echo "${CT_NAME_RAW}" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]/-/g' | sed 's/--*/-/g' | sed 's/^-//;s/-$//')
CORES=4
MEMORY=8192
SWAP=1024
DISK_SIZE=30
STORAGE="local-lvm"
BRIDGE="vmbr0"
SSH_KEY_DIR="/root/.ssh/lxc-keys"

if [ -z "${CTID}" ]; then
    echo "Usage: $0 <CTID> [hostname]"
    echo ""
    echo "Containers disponibles :"
    pct list
    exit 1
fi

CONF="/etc/pve/lxc/${CTID}.conf"

# ══════════════════════════════════════════════════════════════════════════════
# Detecter le mode : CREATION ou RECONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════
if pct status "${CTID}" &>/dev/null; then
    MODE="reconfigure"
    echo "==========================================="
    echo "  Container ${CTID} detecte -> RECONFIGURATION"
    echo "==========================================="
else
    MODE="create"
    echo "==========================================="
    echo "  Container ${CTID} inexistant -> CREATION"
    echo "==========================================="
fi
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# MODE CREATION
# ══════════════════════════════════════════════════════════════════════════════
if [ "${MODE}" = "create" ]; then

    # ── Detecter le template Ubuntu ──────────────────────────────────────────
    TEMPLATE=$(pveam list local 2>/dev/null | grep -i "ubuntu-24" | awk '{print $1}' | head -1)
    [ -z "${TEMPLATE}" ] && TEMPLATE=$(pveam list local 2>/dev/null | grep -i "ubuntu-22" | awk '{print $1}' | head -1)
    [ -z "${TEMPLATE}" ] && TEMPLATE=$(pveam list local 2>/dev/null | grep -i "ubuntu" | awk '{print $1}' | head -1)

    if [ -z "${TEMPLATE}" ]; then
        echo "ERREUR : Aucun template Ubuntu trouve."
        exit 1
    fi

    # ── Creer le container (directement privileged) ──────────────────────────
    echo "[1/3] Creation du container LXC..."
    pct create "${CTID}" "${TEMPLATE}" \
      --hostname "${CT_NAME}" \
      --cores "${CORES}" \
      --memory "${MEMORY}" \
      --swap "${SWAP}" \
      --rootfs "${STORAGE}:${DISK_SIZE}" \
      --net0 "name=eth0,bridge=${BRIDGE},firewall=1,ip=dhcp,type=veth" \
      --nameserver "8.8.8.8" \
      --searchdomain "1.1.1.1" \
      --ostype ubuntu \
      --unprivileged 0 \
      --features "nesting=1,keyctl=1" \
      --tags "agflow,docker" \
      --description "agflow.docker platform"

    # ── Ajouter la config Docker (Proxmox-specific, voir section 5) ──────────
    cat >> "${CONF}" << 'EOF'

# Docker dans LXC — permissions necessaires
lxc.apparmor.profile: unconfined
lxc.cap.drop:
lxc.mount.auto: proc:rw sys:rw cgroup:rw
lxc.cgroup2.devices.allow: a
lxc.mount.entry: /sys/kernel/security sys/kernel/security none bind,optional 0 0
EOF

    STEP_BOOT=3
    STEP_TOTAL=3

else
    # ── MODE RECONFIGURATION ─────────────────────────────────────────────────
    # 1. Stop container
    # 2. Backup config
    # 3. Lire les parametres existants (arch, cores, memory, hostname, net0…)
    # 4. Si etait unprivileged -> remapper UIDs filesystem 100000-165535 -> 0-65535
    # 5. Reecrire la config avec les flags Docker-ready ci-dessus
    pct stop "${CTID}" 2>/dev/null || true
    cp "${CONF}" "${CONF}.backup.$(date +%Y%m%d%H%M%S)"
    # … (cf. script complet pour le détail du remapping UID)
    STEP_BOOT=6
    STEP_TOTAL=6
fi

# ══════════════════════════════════════════════════════════════════════════════
# COMMUN : Demarrage + Reseau + SSH + Utilisateur agflow + Docker
# ══════════════════════════════════════════════════════════════════════════════

# ── Demarrage ────────────────────────────────────────────────────────────────
pct start "${CTID}"
sleep 5

# ── Configuration reseau DHCP via systemd-networkd ──────────────────────────
pct exec "${CTID}" -- bash -c '
if [ ! -f /etc/systemd/network/20-eth0.network ]; then
    cat > /etc/systemd/network/20-eth0.network << NETEOF
[Match]
Name=eth0
[Network]
DHCP=yes
[DHCP]
UseDNS=yes
UseRoutes=yes
NETEOF
    systemctl restart systemd-networkd
fi
'

# ── Configuration SSH (clef root ed25519, stockee sur HOTE) ─────────────────
mkdir -p "${SSH_KEY_DIR}"
KEY_FILE="${SSH_KEY_DIR}/id_ed25519_lxc${CTID}"
if [ ! -f "${KEY_FILE}" ]; then
    ssh-keygen -t ed25519 -f "${KEY_FILE}" -N "" -C "proxmox-host->lxc-${CTID}" -q
fi
PUB_KEY=$(cat "${KEY_FILE}.pub")

pct exec "${CTID}" -- bash -c "
command -v sshd &>/dev/null || { apt-get update -qq && apt-get install -y -qq openssh-server; }
sed -i 's/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
sed -i 's/^#*PubkeyAuthentication.*/PubkeyAuthentication yes/' /etc/ssh/sshd_config
mkdir -p /root/.ssh && chmod 700 /root/.ssh
grep -qF '${PUB_KEY}' /root/.ssh/authorized_keys 2>/dev/null || echo '${PUB_KEY}' >> /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
systemctl enable ssh && systemctl restart ssh
"

# ── Installation Docker (script externe) ─────────────────────────────────────
DOCKER_SCRIPT="${SCRIPT_DIR}/01-install-docker.sh"
if [ -f "${DOCKER_SCRIPT}" ]; then
    pct push "${CTID}" "${DOCKER_SCRIPT}" /root/01-install-docker.sh
    pct exec "${CTID}" -- chmod +x /root/01-install-docker.sh
    pct exec "${CTID}" -- /root/01-install-docker.sh
fi

# ── Utilisateur agflow ──────────────────────────────────────────────────────
AGFLOW_PASS=$(tr -dc 'A-Za-z0-9_!@#$%^&*' </dev/urandom 2>/dev/null | head -c 24 || echo "agflow$(date +%s)")
AGFLOW_KEY_FILE="${SSH_KEY_DIR}/id_ed25519_agflow_lxc${CTID}"
[ -f "${AGFLOW_KEY_FILE}" ] || ssh-keygen -t ed25519 -f "${AGFLOW_KEY_FILE}" -N "" -C "agflow@lxc-${CTID}" -q
AGFLOW_PUB_KEY=$(cat "${AGFLOW_KEY_FILE}.pub")

pct exec "${CTID}" -- bash -c "
id agflow &>/dev/null || useradd -m -s /bin/bash -G sudo,docker agflow || useradd -m -s /bin/bash agflow
echo 'agflow:${AGFLOW_PASS}' | chpasswd
mkdir -p /home/agflow/.ssh && chmod 700 /home/agflow/.ssh
grep -qF '${AGFLOW_PUB_KEY}' /home/agflow/.ssh/authorized_keys 2>/dev/null || echo '${AGFLOW_PUB_KEY}' >> /home/agflow/.ssh/authorized_keys
chmod 600 /home/agflow/.ssh/authorized_keys
chown -R agflow:agflow /home/agflow/.ssh
"

# ── Cle Wetty (terminal web agflow) — VALEUR FIXE, NE PAS MODIFIER ──────────
WETTY_PUB="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHNerDXuUIaAU/m7AUJJaqDDKA8YJzqBRvppg85M7PpZ agflow-wetty"

pct exec "${CTID}" -- bash -c "
grep -qF '${WETTY_PUB}' /home/agflow/.ssh/authorized_keys 2>/dev/null || {
    echo '${WETTY_PUB}' >> /home/agflow/.ssh/authorized_keys
    chown agflow:agflow /home/agflow/.ssh/authorized_keys
}
echo 'agflow ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/agflow
chmod 440 /etc/sudoers.d/agflow
"

# ── Recuperer les infos systeme ──────────────────────────────────────────────
CT_IP=$(pct exec "${CTID}" -- bash -c "ip -4 addr show eth0 2>/dev/null | grep inet | awk '{print \$2}' | cut -d/ -f1 | head -1")
CT_DISTRO=$(pct exec "${CTID}" -- bash -c ". /etc/os-release && echo \"\${NAME} \${VERSION_ID}\"")
docker_version=$(pct exec "${CTID}" -- docker --version 2>/dev/null || echo "non installe")

# ── Sortie JSON (DERNIERE LIGNE — convention pipeline agflow) ───────────────
echo "{\"status\":\"ok\",\"ctid\":\"${CTID}\",\"ip\":\"${CT_IP}\",\"ip_type\":\"dhcp\",\"distro\":\"${CT_DISTRO}\",\"user\":\"agflow\",\"password\":\"${AGFLOW_PASS}\",\"ssh_key\":\"${AGFLOW_KEY_FILE}\",\"docker\":\"${docker_version}\"}"
```

---

## 3. Contrat invariant agflow (NON-NÉGOCIABLE)

Ces points doivent apparaître **à l'identique** dans ton script, quelle que
soit la techno cible. Si tu en omets un, le script est rejeté.

### 3.1 Contrat d'entrée

- Premier argument : `<ID>` (identifiant numérique ou string de
  l'instance — ex. CTID Proxmox, MOID VMware, instance-id AWS).
  Obligatoire. Affiche un usage et exit 1 si absent.
- Deuxième argument optionnel : `[hostname]` (défaut : `agflow-docker`).
- **Sanitization du hostname** : lowercase, remplace tout caractère hors
  `[a-z0-9-]` par `-`, collapse les `-` consécutifs, strip leading/trailing
  `-`. Reproduire la ligne :
  ```bash
  CT_NAME=$(echo "${CT_NAME_RAW}" | tr '[:upper:]' '[:lower:]' \
    | sed 's/[^a-z0-9-]/-/g' | sed 's/--*/-/g' | sed 's/^-//;s/-$//')
  ```

### 3.2 Mode dual `create` | `reconfigure`

- Détecter automatiquement via une commande de la techno cible
  (équivalent de `pct status`).
- Mode `create` : provisionne from scratch.
- Mode `reconfigure` : backup config existante AVANT toute modification,
  puis applique uniquement le delta.

### 3.3 Sortie JSON normalisée (DERNIÈRE LIGNE de stdout)

Format strict, une seule ligne, JSON valide parsable par
`jq -e '.status=="ok"'` :

```json
{"status":"ok","{{INSTANCE_ID_FIELD}}":"...","ip":"...","ip_type":"dhcp|static","distro":"...","user":"agflow","password":"...","ssh_key":"...","docker":"..."}
```

- Aucun `echo` ni `print` après cette ligne.
- Si erreur fatale en cours d'exécution, exit non-zéro **avant** d'émettre
  cette ligne (la pipeline interprète son absence comme un échec).
- La clé d'identifiant porte le nom `{{INSTANCE_ID_FIELD}}` (pas `ctid`).

### 3.4 Utilisateur `agflow` (identique partout)

- Username : `agflow` exactement.
- Shell : `/bin/bash`.
- Groupes : `sudo` + `docker` (créer le user dans ces groupes ; fallback
  sans `docker` si le groupe n'existe pas encore au moment de la création).
- Password : 24 caractères aléatoires depuis `/dev/urandom`, charset
  `A-Za-z0-9_!@#$%^&*`. Reproduire :
  ```bash
  AGFLOW_PASS=$(tr -dc 'A-Za-z0-9_!@#$%^&*' </dev/urandom 2>/dev/null | head -c 24)
  ```
- Sudo NOPASSWD : `echo 'agflow ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/agflow`
  + `chmod 440`.
- Clé SSH dédiée `ed25519` générée côté hôte, stockée dans
  `${SSH_KEY_DIR}/id_ed25519_agflow_{{INSTANCE_ID_FIELD}}${ID}`.
  Le chemin `${SSH_KEY_DIR}` doit être un répertoire dédié sur l'hôte
  (équivalent de `/root/.ssh/lxc-keys`) — adapte le segment `lxc-keys` à
  la techno (ex. `vsphere-keys`, `ec2-keys`).

### 3.5 Clé Wetty — VALEUR LITTÉRALE OBLIGATOIRE

Cette ligne exacte doit apparaître dans le script et être ajoutée au
`/home/agflow/.ssh/authorized_keys` :

```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHNerDXuUIaAU/m7AUJJaqDDKA8YJzqBRvppg85M7PpZ agflow-wetty
```

Ne pas régénérer, ne pas paramétrer. C'est la clé du service Wetty
(terminal web) hébergé sur le LXC 201 — toute instance agflow doit
l'accepter.

### 3.6 Idempotence

Chaque opération doit pouvoir être ré-exécutée sans casse :

- `if file/key/user exists then skip else create`.
- `grep -qF` avant `>> authorized_keys`.
- `command -v X &>/dev/null || install X`.
- Backup de toute config réécrite (`cp X X.backup.$(date +%Y%m%d%H%M%S)`).

### 3.7 Stockage des clés SSH côté HÔTE

Toutes les clés SSH (root + agflow) sont générées et conservées **sur la
machine qui exécute le script** (l'hôte d'orchestration), pas dans la
{{INSTANCE_NOUN}}. Cela permet à la pipeline agflow de récupérer la clé
privée pour reprise de contrôle ultérieure.

### 3.8 Configuration réseau

- DHCP par défaut.
- Récupération de l'IP **après** le boot et publication dans la sortie JSON.
- Test de connectivité (`ping -c 1 8.8.8.8`) — log warning, pas exit.

### 3.9 Délégation Docker

Si un fichier `01-install-docker.sh` (ou équivalent) existe dans le même
répertoire que le script, le pousser dans la {{INSTANCE_NOUN}} et l'exécuter.
Sinon, log « install Docker ignoré ». **Ne pas inliner** l'install Docker.

---

## 4. Spécifications techno cible — RÉPONDS EXPLICITEMENT AVANT D'ÉCRIRE

Avant de produire le script, **réponds dans ton chain-of-thought** aux
questions suivantes pour {{TECHNO_NAME}}. Tes réponses guideront la
traduction des appels Proxmox.

| # | Pattern Proxmox | Question pour {{TECHNO_NAME}} |
|---|---|---|
| Q1 | `pct status <CTID>` | Comment vérifier si une {{INSTANCE_NOUN}} avec cet ID existe déjà via `{{CLI_TOOL}}` ? |
| Q2 | `pct create … --net0 ip=dhcp` | Quelle commande crée une {{INSTANCE_NOUN}} from template avec CPU/RAM/disque/NIC ? |
| Q3 | `pveam list local` | Comment lister les images/templates {{TARGET_OS_DEFAULT}} disponibles ? Quel défaut ? |
| Q4 | Édition directe de `/etc/pve/lxc/${CTID}.conf` | Comment modifier la config d'une {{INSTANCE_NOUN}} existante (mode reconfigure) ? |
| Q5 | `pct start` | Comment démarrer/arrêter une {{INSTANCE_NOUN}} ? |
| Q6 | `pct exec <CTID> -- <cmd>` | Comment exécuter une commande shell dans la {{INSTANCE_NOUN}} ? Si rien d'équivalent : injection cloud-init `runcmd:` au boot. |
| Q7 | `pct push <CTID> src dst` | Comment copier un fichier hôte → {{INSTANCE_NOUN}} ? |
| Q8 | `pct exec … ip addr show eth0` | Comment récupérer l'IP DHCP attribuée après boot ? |
| Q9 | Injection clé SSH via `pct exec` post-boot | Quel mécanisme d'injection initiale (cloud-init `users:`, vmware-tools, EC2 instance metadata, autounattend.xml…) ? |
| Q10 | `lxc.apparmor.profile: unconfined` etc. | Y a-t-il un équivalent de ces 5 lignes pour autoriser Docker ? Sinon, **les omettre purement** (les VMs vraies n'en ont pas besoin). |

**Si une question n'a pas d'équivalent direct sur {{TECHNO_NAME}}**, choisis
le mécanisme natif le plus simple et explicite-le en commentaire dans le
script. N'invente pas d'options de CLI : si tu n'es pas sûr, utilise une
commande standard documentée et indique en commentaire `# TODO: vérifier
syntaxe exacte pour la version installée`.

---

## 5. Conventions de code

- **Shebang & sécurité** : `#!/bin/bash` + `set -euo pipefail` (ou
  `Set-StrictMode -Version Latest; $ErrorActionPreference = 'Stop'` pour
  PowerShell).
- **Commentaires en français**, sans accents (compatible terminaux POSIX
  legacy) : `Verification` pas `Vérification`.
- **Headers ASCII** : utiliser `═`, `─`, `══` comme dans la référence pour
  délimiter les sections principales.
- **Étapes numérotées** : `[1/N] Description...` avec `N = total d'étapes`.
- **Pas de couleurs ANSI** (compromet le parsing par la pipeline).
- **Aucun secret en dur**. Credentials techno (token vSphere, clé AWS…) lus
  depuis l'environnement (`${VSPHERE_PASSWORD:?missing}`) ou config locale
  (`~/.govmomi/credentials`).
- **Dernière ligne stdout = JSON pur**. Tout log informatif AVANT.
- **Fichier unique** : pas de sourcing externe (sauf `01-install-docker.sh`
  cf. §3.9).

---

## 6. Critères d'acceptation — vérifie chaque item AVANT de rendre

- [ ] Le script commence par `#!/bin/bash` + `set -euo pipefail` + en-tête
      ASCII descriptif.
- [ ] Les 10 questions Q1-Q10 ont reçu une réponse implicite dans le code.
- [ ] La sanitization du hostname est **identique** à celle de la référence.
- [ ] Le mode `create` vs `reconfigure` est détecté automatiquement.
- [ ] Le mode `reconfigure` fait un backup horodaté avant toute écriture.
- [ ] L'utilisateur `agflow` est créé avec les paramètres exacts de §3.4.
- [ ] La chaîne littérale `agflow-wetty` apparaît dans le script
      (`grep -F 'agflow-wetty' {{SCRIPT_FILENAME}}` doit matcher).
- [ ] La clé Wetty est ajoutée à `/home/agflow/.ssh/authorized_keys`.
- [ ] La sortie se termine par **un seul** JSON contenant **toutes** les clés
      `status, {{INSTANCE_ID_FIELD}}, ip, ip_type, distro, user, password,
      ssh_key, docker` — testable avec
      `jq -e '.status=="ok" and .user=="agflow"'`.
- [ ] Aucune commande après le `echo` du JSON final.
- [ ] Re-exécution avec le même ID : pas d'erreur (idempotent).
- [ ] `bash -n {{SCRIPT_FILENAME}}` ne renvoie aucune erreur de syntaxe.
- [ ] `shellcheck {{SCRIPT_FILENAME}}` (si dispo) : pas d'erreur SC2086,
      SC2046, SC2154.

---

## 7. Anti-patterns à NE PAS commettre

- ❌ Utiliser Terraform / Packer / Ansible / Pulumi (le script doit être
  autonome, pas une couche IaC déclarative).
- ❌ Inliner l'installation Docker (déléguer à `01-install-docker.sh`
  comme la référence).
- ❌ Mettre des credentials en dur, même en exemple.
- ❌ Émettre du log après le JSON final.
- ❌ Utiliser `set -e` sans `-u` et `-o pipefail`.
- ❌ Régénérer ou paramétrer la clé Wetty (valeur fixe imposée).
- ❌ Recopier les flags `lxc.apparmor.profile`, `lxc.cgroup2.devices.allow`,
  `nesting=1`, `keyctl=1` : c'est du Proxmox-LXC pur, sans équivalent sur
  une VM virtualisée.
- ❌ Inventer des sous-commandes `{{CLI_TOOL}}` que tu n'es pas sûr de
  connaître. En cas de doute, commente `# TODO: vérifier`.
- ❌ Produire plusieurs fichiers ou un README. **Un seul fichier**,
  `{{SCRIPT_FILENAME}}`.

---

## 8. Format de réponse attendu

Réponds en deux parties :

1. **Section « Réponses Q1-Q10 »** : tableau ou bullets recensant tes
   décisions techniques pour chaque question de §4.
2. **Section « Script »** : un seul bloc ```` ```bash ```` (ou ```` ```pwsh ```` )
   contenant `{{SCRIPT_FILENAME}}` complet, prêt à `chmod +x` et exécuter.

Aucun autre texte avant ou après. Pas de README, pas de notes
d'installation hors-script (les commentaires d'en-tête du script suffisent).
